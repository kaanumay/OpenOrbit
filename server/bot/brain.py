"""Decision engine (utility AI): at every decision moment the bot scores the suitable goals and picks one.

Goal modules are under bot/goals/, each registered with @target (new content = new module; the brain does not change). A goal has:
  eligible(bot, b)   can it be chosen in this context
  points(bot, b)     0..~1: from personality, mood and context
  start(bot, b)      when chosen, sets up its plan (bot.plan)
  abstract(bot, dt, y)       its effect when not on the player's map (statistical)
  concrete(bot, g, w, now)   when on the player's map, steers its ship (ship.py; otherwise default wandering/hunting)
  finished(bot, b)   whether the goal is complete (new decision early)

Choice: points x mood effect + commitment share (the running goal, strong until min_sec elapses) + intent share (LLM or tool) ->
softmax (temperature rises with impatience: impulsive bots are more variable). To behave like a human, small noise is added to the points and
the decision intervals are irregular.
"""
import time

from . import catalog as K
from . import personality as PS

GOALS = {}            # name -> Goal instance


def target(cls):
    """Registers the goal class (when the module is imported)."""
    GOALS[cls.name] = cls()
    return cls


class Goal:
    name = ''
    permission = None          # the pack's access setting (if off it is never chosen): 'pvp', 'quest', 'shop', 'clan', ...
    bot_modes = ('normal', 'advanced')     # in which bot modes (simple.py's goal is only 'simple')
    min_sec = 60        # once chosen it lasts at least this long (internal commitment)
    urgent = False         # can break the commitment (escape, after death)

    def eligible(self, bot, b):
        return True

    def points(self, bot, b):
        return 0.0

    def start(self, bot, b):
        pass

    def abstract(self, bot, dt, y):
        pass

    def concrete(self, bot, g, w, now):
        return False                # False: the body's default behavior

    def finished(self, bot, b):
        return False

    def __repr__(self):
        return '<Hedef %s>' % self.name


class Context:
    """The decision moment's information, computed once (every goal reads the same). Heavy work is lazy (on first request)."""

    def __init__(self, bot, y, now=None):
        self.bot, self.y = bot, y
        self.now = now or time.time()
        self.value = bot.value()
        self._game_map = None
        self._shopping = None

    @property
    def game_map(self):
        """Map candidates to grind [(utility, map, evaluation)] (best to worst)."""
        if self._game_map is None:
            self._game_map = map_candidates(self.bot, self.value, self.y)
        return self._game_map

    @property
    def shopping(self):
        """(the best item that can be bought, the goal being saved for) -> shopping.candidate()."""
        if self._shopping is None:
            from .goals import shopping
            self._shopping = shopping.candidate(self.bot)
        return self._shopping

    def setting(self, name, vars=None):
        return self.y.setting(name, vars) if self.y is not None else vars


def map_candidates(bot, value, y=None):
    """The maps it can enter, by grinding utility. Utility: the gain the personality wants (EP / credits / uridium) - death risk x caution
    - travel cost; hunters and risk-takers like other companies' maps, cautious ones like their own company's. The pack's map limit (the highest
    map class) and the cross-company travel setting are obeyed."""
    o = bot.traits
    courage = PS.clamp(0.3 + 0.6 * o['risk'] + 0.2 * bot.mood['confidence'] - 0.3)
    foreign = y.setting('foreign_map', True) if y is not None else True
    out = []
    lv, firma = bot.level, bot.firma
    for m in K.MAPS:
        if not K.can_enter(m, firma, lv):
            continue
        owner = K.H.company(m)
        if owner and owner != firma and not foreign:
            continue
        r = K.evaluate_map(m, value['dps'], value['ehp'], courage)
        if not r['targets']:
            continue
        earnings = (r['ep_per_hour'] * (0.6 + o['ambition']) / 10.0 + r['credits_per_hour'] * (0.5 + o['frugality']) / 10.0
                  + r['uridium_per_hour'] * 25.0 + r['honor_per_hour'] * 5.0)
        risk = r['deaths_per_hour'] * (1.6 - o['risk']) * 0.35
        route = K.route(bot.game_map, m, firma, lv)
        if route is None:
            continue
        jump = len(route) - 1
        pvp = K.pvp_map(m, firma)
        preference = 1.0 + (0.25 * (o['aggression'] - 0.5) if pvp else 0.1) + (0.15 if m == bot.game_map else 0)
        if owner and owner != firma:
            preference -= 0.35 * (1 - o['risk'])
        # crowding: bots on a map share the same aliens (real players drift to empty maps; avoids piling onto the starting maps)
        crowd = len(y.on_map.get(m, ())) - (1 if m == bot.game_map else 0) if y is not None else 0
        utility = (earnings / 1000.0) * preference * (1 - min(0.9, risk)) / (1 + 0.04 * max(0, crowd)) - jump * 0.03 * (1.2 - o['patience'])
        out.append((utility, m, r))
    out.sort(key=lambda x: -x[0])
    return out


def decision(bot, y, now=None):
    """The bot's new goal (the same one if unchanged). The running goal's commitment and the LLM intent are taken into account."""
    now = now or time.time()
    from . import weapons as WP, skylab as SK, appearance as GR
    WP.resupply(bot)                                   # buys when ammo and rockets run low (like a player, between jobs)
    SK.invest(bot, now)
    GR.shopping(bot, now)                          # ship design and drone formation (by showiness and money)                            # upgrades Skylab (if money and resources allow)
    from . import technology as TECH
    TECH.produce(bot)                                    # Assembly: technology items
    TECH.resupply(bot)                                   # launcher rocket
    from . import loot as LT, galaxy_gates as GT
    LT.assembly(bot)                                # Assembly: the most valuable recipe whose materials it has (key, item ...)
    GT.generator(bot)                                 # Galaxy Gate generator: a spin if it has energy (or uridium)
    from . import modes as MD
    MD.passive(bot, now)                              # Dispatch, Galaxy Trek
    b = Context(bot, y, now)
    current = bot.target
    mood = bot.mood
    mood.update(now)
    intent = bot.k.get('intent')
    if intent and intent.get('end_time', 0) < now:
        intent = bot.k['intent'] = None
    duration = now - bot.goal_start
    run = current is not None and current.name in ('gate', 'mod') and not bot.plan.get('finished')   # the intent must not split the run: there is no way from there
    if current is not None and not current.finished(bot, b) and (run or duration < current.min_sec and not intent):
        urgent = [h for h in GOALS.values() if h.urgent and h is not current and allowed(h, y) and h.eligible(bot, b)]
        if not urgent:
            return current
    candidates = []
    for h in GOALS.values():
        if not allowed(h, y) or not h.eligible(bot, b):
            continue
        p = h.points(bot, b)
        if h is current and not h.finished(bot, b):
            # commitment: a human does not abandon a job halfway; it decreases as they get bored (as the same job drags on)
            p += 0.25 * max(0.0, 1 - mood['boredom']) + (0.3 if duration < h.min_sec else 0)
        if intent and intent.get('target') == h.name:
            p += intent.get('pay', 0.6)
        p *= 1 + bot.r.uniform(-0.08, 0.08)
        candidates.append((h, p))
    if not candidates:
        return current
    temperature = 0.05 + 0.12 * (1 - bot.o('patience'))
    sec = PS.softmax_pick(candidates, temperature, bot.r)
    if sec is not current or sec.finished(bot, b):
        # when a finished goal is chosen again it starts over: before, only boredom grew, and a bot that finished shopping stayed "shopping"
        # forever and never bought anything again (player report 2026-10-31: they were not buying upgrades with millions of uridium)
        if current is not None and sec is not current:
            mood.it(boredom=-0.35)
        bot.target, bot.goal_start, bot.plan = sec, now, {}
        bot.k['target'] = sec.name
        sec.start(bot, b)
    else:
        mood.it(boredom=0.04 * (1.3 - bot.o('patience')))
    return sec


def allowed(h, y):
    if y is None:
        return 'normal' in h.bot_modes
    return y.mode in h.bot_modes and (h.permission is None or y.permission(h.permission))


def force(bot, name, plan=None, pay=1.0, duration=600, now=None):
    """A tool or the LLM asked for a goal: added as an intent (a strong share in the next decision) and decided at once."""
    now = now or time.time()
    bot.k['intent'] = dict(target=name, pay=pay, end_time=now + duration, plan=plan or {})
    bot.next_decision = now


def next_decision_interval(bot):
    """Time between two decisions (s): impatient and impulsive bots think often, patient ones rarely."""
    return bot.r.uniform(8, 22) * (0.6 + bot.o('patience'))


# goal modules (so that they register)
from .goals import load as _load  # noqa: E402
_load()
