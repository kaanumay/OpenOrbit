"""Play style: HOW a pilot plays, next to WHO they are (personality.py traits and archetype).

Everyone can do everything, but nobody is good at everything, and everyone enjoys different things:
  talent      per skill domain the ceiling the pilot can reach (combat, pvp, survival, economy, navigation, focus)
  skill       the current level per domain: starts at a share of the talent (newbie, or a veteran on a new account) and grows with
              practice in that domain at the pilot's own learning speed (fast learners, slow learners, plateaus)
  likes       how much the pilot enjoys each activity (grinding, quests, PvP, gates, exploring, social play, idling, trading, boxes):
              a multiplier on the decision engine's goal scores
  quirks      0-2 habits that make a pilot recognizable (box hunter, map loyal, nomad, kamikaze, coward, afk, hoarder,
              shopaholic, lone wolf, ore trader, weekend warrior, binge player, short sessions, portal camper)
  spending    saver / balanced / spender / impulsive; wallet: most never pay, some buy small uridium packs, a few are whales
  combat      preferred range, orbiting, target choice (nearest / weakest / richest), roaming radius
  rhythm      session length factor, weekend factor, a personal shift of the play-habit hours
Dynamic state (k['play'], saved in the pack state): skill, practice hours, motivation (success lifts it, deaths and stagnation lower
it; a long low stretch means a break of a few days), the favourite map (time spent), the session's theme (today: PvP), the day's form.

The static profile is personality['play'] when the pack (or the panel) set one; otherwise it is derived from the name, deterministic,
so old packs get a stable play style without regenerating the roster (like personality.taste). The roster's random stream is not
touched: adding play styles does not change any existing roster.
"""
import math, random, time, zlib

from . import personality as PS

DOMAINS = ('combat', 'pvp', 'survival', 'economy', 'navigation', 'focus')
ACTIVITIES = ('grind', 'quest', 'pvp', 'gate', 'explore', 'social', 'rest', 'trade', 'collect')
GOAL_ACTIVITY = {'grinding': 'grind', 'quest': 'quest', 'pvp': 'pvp', 'duel': 'pvp', 'gate': 'gate', 'mod': 'gate',
                 'exploring': 'explore', 'group': 'social', 'assist': 'social', 'resting': 'rest', 'selling': 'trade'}
PRACTICE = {        # goal -> skill domains it trains (weight per hour)
    'grinding': dict(combat=1.0, survival=0.4, focus=0.3), 'quest': dict(combat=0.8, navigation=0.6, survival=0.3, focus=0.3),
    'pvp': dict(pvp=1.0, survival=0.6, combat=0.2), 'duel': dict(pvp=1.0, survival=0.3), 'gate': dict(combat=0.9, survival=0.7, focus=0.6),
    'mod': dict(combat=0.9, survival=0.6, focus=0.5), 'exploring': dict(navigation=1.0, survival=0.3), 'group': dict(combat=0.7, pvp=0.2),
    'assist': dict(pvp=0.7, survival=0.3), 'selling': dict(economy=0.4, navigation=0.5), 'resting': dict(economy=0.1)}
PRACTICE_TAU_H = 14.0          # hours of practice that close ~63% of the gap between skill and talent (at learning speed 1)

TALENT_BIAS = {
    'grinder': dict(combat=.12, focus=.12, economy=.03), 'hunter': dict(pvp=.2, survival=.05, combat=.03, focus=-.03),
    'social': dict(focus=-.1, pvp=-.08, navigation=.02), 'trader': dict(economy=.22, navigation=.05, pvp=-.08),
    'quester': dict(navigation=.12, combat=.04), 'casual': dict(combat=-.06, pvp=-.06, survival=-.04, economy=-.06, navigation=-.04, focus=-.14),
    'leader': dict(pvp=.08, economy=.06, survival=.04)}
LIKES = {
    'grinder': dict(grind=1.35, quest=.9, pvp=.6, gate=1.1, explore=.75, social=.7, rest=.8, trade=1.1, collect=1.0),
    'hunter':  dict(grind=.8, quest=.7, pvp=1.6, gate=1.0, explore=1.0, social=.9, rest=.7, trade=.7, collect=.8),
    'social':  dict(grind=.9, quest=.9, pvp=.7, gate=.9, explore=.9, social=1.6, rest=1.3, trade=.8, collect=1.0),
    'trader':  dict(grind=1.0, quest=.9, pvp=.5, gate=.8, explore=.8, social=.9, rest=1.0, trade=1.6, collect=1.3),
    'quester': dict(grind=.9, quest=1.6, pvp=.7, gate=1.0, explore=1.2, social=.8, rest=.9, trade=.9, collect=1.0),
    'casual':  dict(grind=.9, quest=1.0, pvp=.8, gate=.8, explore=1.2, social=1.1, rest=1.4, trade=.8, collect=1.2),
    'leader':  dict(grind=1.0, quest=.9, pvp=1.2, gate=1.2, explore=.8, social=1.4, rest=.8, trade=.9, collect=.8)}
QUIRKS = {          # name -> (base chance, what it does; read through has())
    'box_hunter': 0.07,        # chases bonus boxes: more box income, fewer kills, wide box pickup radius
    'map_loyal': 0.09,         # sticks to its favourite map
    'nomad': 0.06,             # keeps changing maps, explores a lot
    'kamikaze': 0.05,          # hardly ever flees, dies more
    'coward': 0.06,            # flees early, avoids battle maps
    'afk': 0.07,               # long idle stretches inside sessions
    'hoarder': 0.05,           # sits on uridium, buys only big goals
    'shopaholic': 0.05,        # buys whatever it can, likes looks
    'lone_wolf': 0.07,         # no groups, few friends
    'ore_trader': 0.05,        # collects every ore, sells often
    'weekend_warrior': 0.07,   # plays little on weekdays, a lot on weekends
    'binge': 0.05,             # rare but very long sessions
    'short_sessions': 0.07,    # many short logins
    'portal_camper': 0.04,     # PvP: waits near portals for passers-by
}
WALLET_WEEK = {'none': 0, 'small': (2000, 8000), 'whale': (25000, 90000)}       # uridium bought per week (payment packs)
STATE_VERSION = 1


def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def _rng(p):
    return random.Random(zlib.crc32(('play|%s|%s' % (p.get('_name') or '', p.get('archetype'))).encode()))


def generate(p, r=None):
    """A static play profile for a personality (deterministic from the name when r is not given)."""
    r = r or _rng(p)
    a = p.get('archetype', 'casual')
    tr = p.get('traits') or {}
    t = lambda k: tr.get(k, 0.5) - 0.5
    g = r.gauss(0.52, 0.13)                                        # general aptitude: some are good at most things
    link = dict(combat=0.1 * t('ambition') + 0.06 * t('patience'), pvp=0.14 * t('aggression') + 0.08 * t('rivalry'),
                survival=-0.16 * t('risk') + 0.06 * t('patience'), economy=0.18 * t('frugality') + 0.05 * t('patience'),
                navigation=0.06 * t('ambition') + 0.05 * t('patience'), focus=0.2 * t('patience') + 0.06 * t('ambition'))
    talent = {d: round(clamp(g + TALENT_BIAS.get(a, {}).get(d, 0) + link[d] + r.gauss(0, 0.15), 0.08, 0.98), 3) for d in DOMAINS}
    veteran = r.random() < 0.12                                   # an old player on a new account: knows the game already
    start = round(r.uniform(0.75, 0.95) if veteran else clamp(r.betavariate(2.2, 3.2), 0.12, 0.8), 3)
    learn = round(clamp(r.lognormvariate(0, 0.42), 0.3, 2.6), 3)
    quirks = []
    for q, base in QUIRKS.items():
        w = base
        if q == 'kamikaze':
            w *= 0.4 + 2 * tr.get('risk', 0.5)
        elif q == 'coward':
            w *= 0.4 + 2 * (1 - tr.get('risk', 0.5))
        elif q == 'lone_wolf':
            w *= 0.3 + 2 * (1 - tr.get('sociability', 0.5))
        elif q == 'hoarder':
            w *= 0.3 + 2 * tr.get('frugality', 0.5)
        elif q == 'shopaholic':
            w *= 0.3 + 2 * (1 - tr.get('frugality', 0.5))
        elif q == 'afk':
            w *= 0.4 + 1.6 * (1 - tr.get('ambition', 0.5))
        if r.random() < w:
            quirks.append(q)
    for a1, a2 in (('kamikaze', 'coward'), ('nomad', 'map_loyal'), ('binge', 'short_sessions'), ('hoarder', 'shopaholic')):
        if a1 in quirks and a2 in quirks:
            quirks.remove(r.choice((a1, a2)))
    r.shuffle(quirks)
    quirks = quirks[:2]
    likes = {k: round(clamp(v * r.lognormvariate(0, 0.3), 0.25, 2.6), 3) for k, v in LIKES.get(a, LIKES['casual']).items()}
    boost = {'box_hunter': ('collect', 1.9), 'nomad': ('explore', 1.7), 'ore_trader': ('trade', 1.8), 'afk': ('rest', 1.8),
             'lone_wolf': ('social', 0.35), 'coward': ('pvp', 0.4), 'kamikaze': ('pvp', 1.4), 'portal_camper': ('pvp', 1.5)}
    for q in quirks:
        if q in boost:
            k, f = boost[q]
            likes[k] = round(clamp(likes[k] * f, 0.15, 3.0), 3)
    fr, pa = tr.get('frugality', 0.5), tr.get('patience', 0.5)
    styles = dict(saver=0.08 + 2.2 * fr ** 2, balanced=0.75, spender=0.08 + 1.5 * (1 - fr) ** 2, impulsive=0.04 + 1.0 * (1 - fr) * (1 - pa))
    if 'hoarder' in quirks:
        styles = dict(saver=1.0)
    elif 'shopaholic' in quirks:
        styles = dict(spender=0.6, impulsive=0.4)
    spend = r.choices(list(styles), list(styles.values()))[0]
    w = r.random()
    wallet = 'whale' if w < 0.045 else 'small' if w < 0.2 else 'none'
    week = 0 if wallet == 'none' else round(r.uniform(*WALLET_WEEK[wallet]))
    roam = r.choices(('wide', 'local', 'camper'), (0.3 + 0.6 * (1 - pa), 0.5, 0.1 + 0.4 * pa + 0.5 * ('map_loyal' in quirks)))[0]
    session = clamp(r.lognormvariate(0, 0.3), 0.45, 2.2) * (1.9 if 'binge' in quirks else 0.5 if 'short_sessions' in quirks else 1.0)
    logins = clamp(r.lognormvariate(0, 0.42), 0.35, 2.4) * (0.55 if 'binge' in quirks else 1.7 if 'short_sessions' in quirks else 1.0)
    out = dict(v=1, talent=talent, start=start, learn=learn, likes=likes, quirks=quirks, spend=spend, wallet=wallet, wallet_week=week,
               range=round(clamp(r.lognormvariate(0, 0.22), 0.6, 1.6), 3),
               orbit=round(clamp(0.25 + 0.5 * tr.get('aggression', 0.5) + r.gauss(0, 0.18)), 3),
               target=r.choices(('nearest', 'weakest', 'richest'), (0.55, 0.2 + 0.2 * (1 - tr.get('risk', 0.5)), 0.25 + 0.2 * tr.get('ambition', 0.5)))[0],
               roam=roam, session=round(session, 3), logins=round(logins, 3), shift=r.choice((-2, -1, -1, 0, 0, 0, 0, 1, 1, 2)),
               weekday=0.4 if 'weekend_warrior' in quirks else round(clamp(r.gauss(1.0, 0.12), 0.7, 1.25), 3),
               weekend=2.1 if 'weekend_warrior' in quirks else round(clamp(r.gauss(1.1, 0.2), 0.6, 1.7), 3),
               motivation=round(clamp(r.gauss(0.72, 0.12), 0.35, 0.95), 3),
               daily_h=round(r.uniform(6, 11) if p.get('habit') == 'devoted' else r.uniform(2.5, 8) * (0.75 + 0.5 * tr.get('ambition', 0.5))
                             * (0.7 if a == 'casual' else 1.0), 2))
    out['summary'] = summary(out, a)
    return out


def summary(pl, archetype=None):
    """A short English description (panel, LLM persona, behavior judge)."""
    tal = pl['talent']
    best = max(DOMAINS, key=lambda d: tal[d])
    worst = min(DOMAINS, key=lambda d: tal[d])
    likes = sorted(pl['likes'].items(), key=lambda x: -x[1])
    words = dict(combat='killing aliens', pvp='PvP fights', survival='staying alive', economy='spending wisely', navigation='finding good maps',
                 focus='staying focused')
    act = dict(grind='grinding', quest='quests', pvp='PvP', gate='gates and modes', explore='exploring', social='playing with others',
               rest='hanging out', trade='collecting and selling ore', collect='hunting boxes')
    s = 'loves %s and %s, not into %s; good at %s, weak at %s; %s spender' % (
        act[likes[0][0]], act[likes[1][0]], act[likes[-1][0]], words[best], words[worst], pl['spend'])
    if pl.get('wallet') == 'whale':
        s += ', pays a lot'
    elif pl.get('wallet') == 'small':
        s += ', buys small uridium packs'
    if pl.get('quirks'):
        s += '; ' + ', '.join(q.replace('_', ' ') for q in pl['quirks'])
    return s


def profile(bot_or_p):
    """The static play profile (personality['play']), created on first use."""
    p = bot_or_p if isinstance(bot_or_p, dict) else bot_or_p.k['personality']
    pl = p.get('play')
    if not isinstance(pl, dict) or pl.get('v') != 1:
        pl = p['play'] = generate(p)
    return pl


def state(bot):
    """The dynamic state (k['play']): skill per domain, practice hours, motivation, map time, break, wallet clock."""
    st = bot.k.get('play')
    if not isinstance(st, dict) or st.get('v') != STATE_VERSION:
        pl = profile(bot)
        # a pilot that already played before play styles existed (old pack state) counts its play time as practice
        h = (bot.k.get('stats') or {}).get('duration_sec', 0) / 3600.0 * 0.5
        st = bot.k['play'] = dict(v=STATE_VERSION, xp={d: round(h, 2) for d in DOMAINS}, motivation=pl['motivation'], maps={}, brk=0.0,
                                  paid=bot.hour(), theme=None, form=1.0,
                                  skill={d: round(pl['talent'][d] - pl['talent'][d] * (1 - pl['start'])
                                                  * math.exp(-pl['learn'] * h / PRACTICE_TAU_H), 4) for d in DOMAINS})
    return st


def skill(bot, d):
    return state(bot)['skill'][d]


def has(bot, quirk):
    return quirk in profile(bot)['quirks']


def like(bot, activity):
    return profile(bot)['likes'].get(activity, 1.0)


# ------------------------------------------------------------------------------------------------ learning
def practice(bot, goal, dt):
    """dt seconds spent on a goal train its domains: skill moves toward the talent, fast at first, slowly near the ceiling."""
    w = PRACTICE.get(goal)
    if not w or dt <= 0:
        return
    pl, st = profile(bot), state(bot)
    h = dt / 3600.0
    w = dict(w, focus=w.get('focus', 0) + 0.15)                     # every online minute trains attention a little
    for d, k in w.items():
        st['xp'][d] = st['xp'].get(d, 0.0) + h * k
        s = st['skill'][d]
        gap = pl['talent'][d] - s
        if gap > 0:
            st['skill'][d] = s + gap * (1 - math.exp(-pl['learn'] * h * k / PRACTICE_TAU_H))
    if goal in ('grinding', 'quest', 'group') and bot.game_map:
        m = st['maps']
        key = str(bot.game_map)
        m[key] = m.get(key, 0.0) + dt
        if len(m) > 12:
            del m[min(m, key=m.get)]


# ------------------------------------------------------------------------------------------------ effects
def combat_efficiency(bot):
    """Share of the theoretical grinding speed the pilot realizes (targeting, positioning, ammo, attention) x the day's form."""
    st = state(bot)
    return (0.55 + 0.9 * st['skill']['combat']) * (0.82 + 0.36 * st['skill']['focus']) * st.get('form', 1.0) \
        * (0.8 if has(bot, 'box_hunter') else 1.0) * (0.85 if has(bot, 'afk') else 1.0)


def cargo_care(bot):
    """Share of the cargo boxes a pilot bothers to pick up (x the patience rule): ore traders all, many players few."""
    k = state(bot).get('ore', 1.0)
    if has(bot, 'ore_trader'):
        return 1.25 * k
    return clamp(-0.55 + 1.1 * like(bot, 'trade') / 1.3 + 0.3 * skill(bot, 'economy'), 0.03, 1.15) * k


def wants_to_sell(bot):
    """A full hold ends the current grinding stretch of a pilot that cares about ore (it goes to sell)."""
    if bot.cargo_fill() < 0.97 or not (cargo_care(bot) >= 0.5 or has(bot, 'ore_trader')):
        return False
    st = state(bot)
    if bot.hour() - st.get('sold', 0) < sell_gap(bot) / 3:
        st['ore'] = max(0.25, st.get('ore', 1.0) * 0.7)     # the hold filled again in minutes: it skips the cheap ore for this session
        return False
    return True


def box_factor(bot):
    return 2.2 if has(bot, 'box_hunter') else 0.4 + 0.6 * like(bot, 'collect')


def death_factor(bot):
    """Multiplier of the alien death risk: awareness (survival) and habits."""
    return (1.75 - 1.4 * skill(bot, 'survival')) * (1.6 if has(bot, 'kamikaze') else 0.6 if has(bot, 'coward') else 1.0)


def pvp_factor(bot):
    """PvP strength beyond gear: aim, movement, timing."""
    return 0.55 + 0.95 * skill(bot, 'pvp')


def flee_shift(bot):
    """Added to the HP ratio at which the ship flees (concrete layer): unaware pilots flee late, cowards early."""
    s = skill(bot, 'survival')
    return -0.1 * (1 - s) + (0.18 if has(bot, 'coward') else -0.15 if has(bot, 'kamikaze') else 0.0)


def thrift(bot):
    """Frugality as used for ammo and shopping reserves: the trait shifted by the spending style."""
    return clamp(bot.o('frugality') + {'saver': 0.2, 'balanced': 0.0, 'spender': -0.2, 'impulsive': -0.3}[profile(bot)['spend']]
                 + (0.25 if has(bot, 'hoarder') else 0.0))


def impulse_chance(bot):
    """Chance that a shopping trip buys something that is not the best choice (taste, mood, misjudging)."""
    pl = profile(bot)
    base = {'saver': 0.02, 'balanced': 0.05, 'spender': 0.1, 'impulsive': 0.22}[pl['spend']]
    return base + 0.2 * (1 - skill(bot, 'economy')) ** 1.5 + (0.12 if has(bot, 'shopaholic') else 0.0)


def shop_horizon(bot):
    """(hours of income it saves for, share of the goal's efficiency a smaller purchase must reach)."""
    return {'saver': (8.0, 0.9), 'balanced': (2.5, 0.7), 'spender': (0.8, 0.45), 'impulsive': (0.4, 0.3)}[profile(bot)['spend']]


def sell_shift(bot):
    """Added to the cargo threshold for going to sell: an ore trader goes early, an unfocused pilot forgets until it overflows."""
    return (-0.2 if has(bot, 'ore_trader') else 0.0) + 0.25 * (1 - skill(bot, 'focus')) ** 2


def map_bias(bot, m, now):
    """Multiplier on a map's grinding utility: misjudging (navigation skill, stable for 6-hour windows), the favourite map, habits."""
    pl, st = profile(bot), state(bot)
    nav = st['skill']['navigation']
    u = zlib.crc32(('%s|%s|%d' % (bot.name, m, int(now // 21600))).encode()) / 4294967295.0
    noise = math.exp((u - 0.5) * 2.2 * (1 - nav))
    maps = st['maps']
    total = sum(maps.values())
    fav = 1.0
    if total > 1800:
        share = maps.get(str(m), 0.0) / total
        loyal = 0.9 if has(bot, 'map_loyal') else 0.0 if has(bot, 'nomad') else 0.35
        fav = 1 + loyal * share
    if has(bot, 'nomad') and str(m) == str(bot.game_map):
        fav *= 0.85
    if avoided(bot, m, now):
        fav *= 0.2                                        # kept dying there: stays away for a while
    import map_links as H
    if H.map_class(m) in ('X-4',) or str(H.name(m)).startswith('4-'):
        fav *= 0.5 if has(bot, 'coward') else 1.2 if has(bot, 'kamikaze') or has(bot, 'portal_camper') else 1.0
    return noise * fav


def goal_factor(bot, goal, now=None):
    """Multiplier on a goal's score: how much the pilot enjoys it, today's session theme, quirks."""
    a = GOAL_ACTIVITY.get(goal)
    if a is None:
        return 1.0
    st = state(bot)
    f = like(bot, a) ** 0.8
    if st.get('theme') == a:
        f *= 1.45
    if goal == 'resting' and has(bot, 'afk'):
        f *= 1.3
    return f


# ------------------------------------------------------------------------------------------------ sessions, motivation, wallet
def on_login(bot, now):
    """A new session: today's theme, the day's form, the wallet top-up (payment packs), motivation decay since last time."""
    pl, st = profile(bot), state(bot)
    _relax(bot, now)
    st['login'] = now
    st['ore'] = 1.0
    st['auction'] = bot.r.random() < interest(bot, 'auction')     # does it look at the auction in this session
    focus = st['skill']['focus']
    st['form'] = round(clamp(bot.r.gauss(1.0, 0.08 + 0.14 * (1 - focus)), 0.6, 1.4), 3)
    if bot.r.random() < 0.6:
        acts = [a for a in ACTIVITIES if a not in ('rest', 'trade', 'collect')]
        st['theme'] = bot.r.choices(acts, [pl['likes'][a] ** 2.5 for a in acts])[0]
    else:
        st['theme'] = None
    if pl.get('wallet_week'):
        due = pl['wallet_week'] * (now - st.get('paid', now)) / 604800.0
        if due >= 0.25 * pl['wallet_week']:            # buys a pack once enough "budget" built up
            n = int(due)
            bot.k['uridium'] += n
            bot.ist('wallet_uridium', n)
            st['paid'] = now
            st['motivation'] = clamp(st['motivation'] + 0.05)
            bot.event('topup', now, uridium=n)


def cap_session(bot, now, end):
    """The planned session end, cut to what is left of the pilot's daily play time (a little over is human)."""
    if 'daily_h' not in profile(bot):
        return end
    return min(end, now + max(900.0, daily_left(bot, now) * bot.r.uniform(1.0, 1.25)))


def session_factor(bot):
    """Session length multiplier: habit factor x motivation."""
    pl, st = profile(bot), state(bot)
    return pl['session'] * (0.65 + 0.6 * st['motivation'])


def online_factor(bot, now):
    """Login tendency multiplier: weekday/weekend habit, how often they log in, motivation; 0 during a break."""
    pl, st = profile(bot), state(bot)
    if now < st.get('brk', 0):
        return 0.0
    if 'daily_h' in pl and daily_left(bot, now) <= 0:
        return 0.03                                        # played enough today (sleep, work): only now and then a little more
    wd = time.localtime(now).tm_wday
    day = pl['weekend'] if wd >= 5 else pl['weekday']
    return day * pl['logins'] * (0.4 + 0.85 * st['motivation'])


def hour_shift(bot):
    return profile(bot)['shift']


MOTIVE = dict(level=0.04, new_ship=0.08, purchase=0.008, i_killed=0.02, quest_done=0.012, gate_done=0.05, mode_done=0.03,
              joined_clan=0.05, friend_accept=0.02, joined_group=0.01, gate_lost=-0.06, fled=-0.01, auction_won=0.02)


def on_event(bot, kind, f):
    """Bot.event hook: success lifts motivation, deaths lower it (more for a frustrated, unskilled pilot); a death also teaches:
    an aggressive pilot killed by someone wants revenge, a careful one avoids the map where it keeps dying."""
    if kind not in MOTIVE and kind != 'death':
        return
    st = state(bot)
    if kind == 'death':
        d = -0.05 if f.get('killer') else -0.025
        d *= 1.4 - 0.8 * st['skill']['survival']
        _after_death(bot, st, f)
    else:
        d = MOTIVE[kind]
    st['motivation'] = clamp(st['motivation'] + d, 0.02, 1.0)


def _after_death(bot, st, f):
    now = bot.hour()
    m = str(bot.game_map)
    deaths = st.setdefault('deaths', {})
    recent = [t for t in deaths.get(m, []) if now - t < 1800] + [now]
    deaths[m] = recent[-4:]
    if len(deaths) > 8:
        del deaths[min(deaths, key=lambda k: max(deaths[k]))]
    o = bot.traits
    careful = (1 - o['risk']) * (0.5 + st['skill']['survival'])
    if (len(recent) >= 2 and bot.r.random() < 0.35 + 0.6 * careful and not has(bot, 'kamikaze')
            or f.get('killer') and (has(bot, 'coward') or bot.r.random() < 0.5 * careful)):
        st.setdefault('avoid', {})[m] = now + bot.r.uniform(1800, 5400) * (0.6 + careful)
    killer = f.get('killer')
    if bot.r.random() < 0.12 + 0.15 * (1 - o['patience']):
        from . import brain as B
        B.force(bot, 'resting', pay=0.5, duration=900, now=now)         # a breather after dying (gets a drink, complains in chat)
    if killer and st['motivation'] < 0.5 and bot.r.random() < 0.3 * (1 - o['patience']) + 0.1:
        bot.session_end = min(bot.session_end, now + bot.r.uniform(60, 400))      # fed up: logs off soon (rage quit)
    if killer and bot.r.random() < min(0.9, 1.7 * o['aggression'] * o['rivalry'] * like(bot, 'pvp') ** 0.7):
        from . import brain as B
        B.force(bot, 'pvp', pay=0.6 + 0.6 * o['aggression'], duration=bot.r.uniform(900, 2400), now=now)
        bot.memory.event(killer, 'insult', now, multiplier=0.5)


def commit_factor(bot):
    """How long a pilot sticks to a newly chosen goal this time, as a multiple of the goal's minimum: patient pilots longer, and
    never the same length twice (a fixed minimum made every bot re-decide on a 5-minute tick)."""
    return clamp(math.exp(bot.r.gauss(0, 0.45)) * (0.6 + 0.9 * bot.o('patience')), 0.35, 4.0)    # (gauss: lognormvariate loops on a stubbed random)


def trip_items(bot, most):
    """How many items one shopping trip buys at most: a saver one or two (and thinks again later), an impulsive buyer all it can."""
    lo, hi = {'saver': (1, 2), 'balanced': (1, 5), 'spender': (3, 10), 'impulsive': (5, most)}[profile(bot)['spend']]
    return min(most, bot.r.randint(lo, hi))


def reserve(bot):
    """Share of the money a pilot keeps untouched when shopping {'C', 'U'}."""
    pl = profile(bot)
    k = {'saver': 0.35, 'balanced': 0.08, 'spender': 0.03, 'impulsive': 0.0}[pl['spend']]
    if 'hoarder' in pl['quirks']:
        return {'C': 0.55, 'U': 0.85}
    return {'C': k, 'U': min(0.9, k * 1.5)}


def misjudge(bot, loot):
    """How much better or worse than it is a pilot thinks an item is (weak money sense: big errors). Stable for a few hours."""
    e = skill(bot, 'economy')
    u = zlib.crc32(('%s|%s|%d' % (bot.name, loot, int(bot.hour() // 10800))).encode()) / 4294967295.0
    return math.exp((u - 0.5) * 3.0 * (1 - e) ** 1.3)


def interest(bot, what):
    """How much a pilot bothers with a side system (0-1, stable per pilot): some never touch the auction or the Skylab, traders and
    careful planners use them a lot. Before, every bot bid on every lot and upgraded the Skylab every session."""
    pl = profile(bot)
    u = (zlib.crc32(('%s|%s' % (bot.name, what)).encode()) % 1000) / 999.0
    if what == 'auction':
        base, never = 0.05 + 0.6 * min(1.0, like(bot, 'trade') / 1.5) + 0.3 * pl['talent']['economy'] - 0.15, 0.4
    elif what == 'skylab':
        base, never = 0.15 + 0.5 * pl['talent']['economy'] + 0.25 * bot.o('patience'), 0.25
    else:
        base, never = 0.5, 0.2
    if u < never:
        return 0.0
    return clamp(base * (0.5 + (u - never) / (1 - never)))


def quiet(bot):
    """A lurker: never opens a topic or greets in public chat (still answers when spoken to). Mostly the untalkative ones."""
    pl = profile(bot)
    q = pl.get('quiet')
    if q is None:
        t = bot.o('talkativeness')
        u = (zlib.crc32(('%s|quiet' % bot.name).encode()) % 1000) / 999.0
        q = pl['quiet'] = u < 0.7 * (1 - t) ** 2 * max(0.15, 1.5 - pl['likes']['social']) + (0.2 if 'lone_wolf' in pl['quirks'] else 0.0)
    return q


def gadget_level(bot):
    """From which level a pilot knows about and buys advanced extras (CPUs, jump drives): a beginner with little money sense later."""
    return 4 + int(round(8 * (1 - skill(bot, 'economy'))))


def sell_gap(bot):
    """Minimum seconds between two ore sales: humans batch their trips; an ore trader goes more often."""
    if has(bot, 'ore_trader'):
        return 480.0
    return 60.0 * (12 + 30 * bot.o('patience')) * (1.4 - 0.4 * min(1.5, like(bot, 'trade')))


def avoided(bot, m, now):
    return now < (state(bot).get('avoid') or {}).get(str(m), 0)


def rest_minutes(bot):
    """How long one break lasts: one longer AFK rather than micro naps (an afk pilot much longer)."""
    return bot.r.uniform(4, 14) * (0.6 + 0.5 * like(bot, 'rest')) * (2.5 if has(bot, 'afk') else 1.0)


def played_today(bot, now):
    """Seconds online in the last 24 hours (closed sessions plus the running one)."""
    st = state(bot)
    days = [d for d in st.get('days', []) if d[0] > now - 86400]
    st['days'] = days
    run = (now - st['login']) if bot.online and st.get('login') else 0.0
    return sum(d[1] for d in days) + run


def daily_left(bot, now):
    return profile(bot)['daily_h'] * 3600 - played_today(bot, now)


def repair_urge(bot):
    """Multiplier of the wish to pay for a quick repair (portal / on the spot) instead of the free one at the station."""
    pl = profile(bot)
    return {'saver': 0.4, 'balanced': 1.0, 'spender': 1.9, 'impulsive': 2.4}[pl['spend']] * (2.0 if pl.get('wallet') == 'whale' else 1.0)


def _relax(bot, now):
    """Motivation drifts back toward the pilot's own baseline (half-life one day)."""
    st, pl = state(bot), profile(bot)
    t = st.get('mt') or now
    if now > t:
        f = 0.5 ** ((now - t) / 86400.0)
        st['motivation'] = pl['motivation'] + (st['motivation'] - pl['motivation']) * f
    st['mt'] = now


def on_logout(bot, now):
    """Stagnation lowers motivation; a pilot that is fed up takes a break of a few days (then comes back fresh)."""
    st, pl = state(bot), profile(bot)
    _relax(bot, now)
    if st.get('login'):
        st.setdefault('days', []).append([now, now - st['login']])
        st['login'] = None
    lv = st.get('lv_seen')
    on = bot.k['stats'].get('duration_sec', 0)
    if lv is None or bot.level > lv:
        st['lv_seen'], st['lv_on'] = bot.level, on
    elif on - st.get('lv_on', on) > 8 * 3600:                # 8 online hours without a level
        st['motivation'] = clamp(st['motivation'] - 0.04, 0.02, 1.0)
        st['lv_on'] = on
    if st['motivation'] < 0.22 and bot.r.random() < 0.5:
        st['brk'] = now + bot.r.uniform(1, 4) * 86400
        st['motivation'] = pl['motivation']
        bot.ist('break')
        bot.event('break', now, days=round((st['brk'] - now) / 86400, 1))
    st['theme'] = None


def describe(bot):
    """The play style as the LLM persona sees it (English, numberless, includes the current skill as words)."""
    pl, st = profile(bot), state(bot)
    lvl = lambda v: 'excellent' if v > 0.8 else 'good' if v > 0.62 else 'average' if v > 0.42 else 'weak' if v > 0.25 else 'bad'
    words = dict(combat='alien combat', pvp='PvP', survival='survival instinct', economy='money sense', navigation='map knowledge', focus='focus')
    sk = ', '.join('%s %s' % (words[d], lvl(st['skill'][d])) for d in DOMAINS)
    theme = st.get('theme')
    return 'Play style: %s. Skills now: %s.%s' % (pl.get('summary') or summary(pl), sk,
                                                   (' Today you feel like %s.' % theme) if theme else '')
