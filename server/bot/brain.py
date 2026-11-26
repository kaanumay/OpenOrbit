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

from . import abstract_sim as S
from . import catalog as K
from . import personality as PS
from . import playstyle as PL

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
    lv, company = bot.level, bot.company
    from . import palladium as PD
    palladium = PD.wants(bot)
    for m in K.MAPS:
        if not K.can_enter(m, company, lv):
            continue
        owner = K.H.company(m)
        if owner and owner != company and not foreign:
            continue
        r = K.evaluate_map(m, value['dps'], value['ehp'], courage)
        if not r['targets']:
            continue
        earnings = (r['ep_per_hour'] * (0.6 + o['ambition']) / 10.0 + r['credits_per_hour'] * (0.5 + o['frugality']) / 10.0
                  + r['uridium_per_hour'] * 25.0 + r['honor_per_hour'] * 5.0) * S.x1_cut(bot, m)    # own X-1 pays less from level 7
        if m in PD.FIELDS and palladium:
            # Palladium for free gate energy (bot/palladium.py): part of the time collecting, valued as the uridium the energy saves
            earnings = earnings * (1 - PD.COLLECT_SHARE) + PD.per_hour(bot, m) * PD.COLLECT_SHARE * PD.value_u(bot) * 25.0
        risk = r['deaths_per_hour'] * (1.6 - o['risk']) * 0.35
        route = K.route(bot.game_map, m, company, lv)
        if route is None:
            continue
        jump = len(route) - 1
        pvp = K.pvp_map(m, company)
        preference = 1.0 + (0.25 * (o['aggression'] - 0.5) if pvp else 0.1) + (0.15 if m == bot.game_map else 0)
        if owner and owner != company:
            preference -= 0.35 * (1 - o['risk'])
        # crowding: bots on a map share the same aliens (real players drift to empty maps; avoids piling onto the starting maps)
        crowd = len(y.on_map.get(m, ())) - (1 if m == bot.game_map else 0) if y is not None else 0
        utility = (earnings / 1000.0) * preference * (1 - min(0.9, risk)) / (1 + 0.04 * max(0, crowd)) - jump * 0.03 * (1.2 - o['patience'])
        utility *= PL.map_bias(bot, m, y.now if y is not None else time.time())      # misjudging (map knowledge), favourite map, habits
        out.append((utility, m, r))
    if palladium and out:
        # Palladium for free gates (user request 2026-11-26): its worth in uridium is small next to grinding, but a pilot who wants gates
        # goes for it: 5-1/5-3 gain a share of the best map's utility (by ambition), shared out by the crowd like any map
        best = max(u for u, _, _ in out)
        crowd = (lambda m: len(y.on_map.get(m, ())) - (1 if m == bot.game_map else 0)) if y is not None else (lambda m: 0)
        out = [(u + PD.pull(bot) * max(0.0, best) * PD.FIELDS[m] / max(PD.FIELDS.values()) / (1 + 0.04 * max(0, crowd(m)))
                if m in PD.FIELDS else u, m, r) for u, m, r in out]
    if out and y is not None:
        # the pirate maps are never left empty (user request 2026-11-26): with fewer than PIRATE_FEW bots there, one a capable pilot can
        # hunt on (it is in out: it has targets there) gains a share of the best map's utility, more for a bold one
        from . import blacklight as BLK
        best = max(u for u, _, _ in out)
        few = lambda m: max(0, BLK.PIRATE_FEW - len(y.on_map.get(m, ())) + (1 if m == bot.game_map else 0)) / BLK.PIRATE_FEW
        out = [(u + (0.5 + 0.4 * o['risk']) * max(0.0, best) * few(m) if m in BLK.PIRATE_MAPS else u, m, r) for u, m, r in out]
    if out and y is not None and bot.k.get('clan'):
        # clan mates draw each other (user request 2026-11-26), whatever their company, most on the pirate maps where every company meets
        from . import society as SO, blacklight as BLK
        mates = lambda m: sum(1 for x in y.on_map.get(m, ()) if x is not bot and SO.same_clan(bot, x))
        out = [(u * (1 + (0.16 if m in BLK.PIRATE_MAPS else 0.08) * min(4, mates(m))) if u > 0 else u, m, r) for u, m, r in out]
    pull = {m: event_pull(bot, m, y.now if y is not None else time.time()) for _, m, _ in out}
    if any(v > 1.0 for v in pull.values()):
        # an open-map event draws who it fits: a share of the best map's utility on top (the event map's own aliens may pay little;
        # its draw is the event), as long as the pilot can fight there at all (r['targets'])
        best = max(u for u, _, _ in out)
        out = [(u + EVENT_PULL_SHARE * (pull[m] - 1.0) * max(0.0, best), m, r) for u, m, r in out]
    out.sort(key=lambda x: -x[0])
    return out


EVENT_MAPS_SEC = 60.0            # the open-map events' maps are looked up once a minute
EVENT_PULL_SHARE = 0.6           # an event map gains this share of the best map's utility per unit of pull (event_pull - 1): a keen
#                                  PvP pilot (pull ~2) ranks 4-4 near its best map, a calm one (pull ~1.1) hardly moves (behaviour weight)
_event_maps = {'t': -1e9, 'maps': {}}


def event_maps(now):
    """The open-map events on now -> {map: kind}: 'pvp' (Spaceball's 4-4, Galactic Strife's 4-1..4-4), 'ctb' (the X-2 maps of Capture the
    Beacon), 'aliens' (an active event's map section with event aliens: events.sections)."""
    if abs(now - _event_maps['t']) < EVENT_MAPS_SEC:
        return _event_maps['maps']
    import event_calendar as CAL
    from . import events as EV, modes as MD
    out = {}
    for m in K.MAPS:
        if any(s.get('alien_spawns') for _, s in EV.sections(m)):
            out[m] = 'aliens'
    ids = {v: k for k, v in K.H.NAMES.items()}
    gs = MD.EX.get('galactic_strife') or {}
    if gs and CAL.is_active(gs.get('event', 'galactic_strife'), now):
        out.update({ids[n]: 'pvp' for n in gs.get('maps', ()) if n in ids})
    if MD.EX.get('capture_the_beacon') and CAL.is_active('capture_the_beacon', now):
        import capture_beacon as CB
        out.update({m: 'ctb' for m in CB.X2.values()})
    sb = MD.EX.get('spaceball') or {}
    if sb and CAL.is_active('spaceball', now):
        out[int(sb['map'])] = 'pvp'
    _event_maps.update(t=now, maps=out)
    return out


def event_pull(bot, m, now):
    """How much an open-map event on map m draws this pilot (1: not at all). PvP events draw the aggressive and competitive (Capture the
    Beacon: raiders to the enemy X-2 more than defenders to their own, from the beacon level), event aliens the ambitious ones strong
    enough for them. Gone when the event ends (map choice at the next decision). Behaviour weights, not game values."""
    kind = event_maps(now).get(m)
    if kind is None:
        return 1.0
    o = bot.traits
    if kind == 'aliens':
        from . import events as EV
        return 1.0 + 0.5 * (0.4 + o['ambition']) if bot.permission.get('event', True) and EV.event_types(bot, m) else 1.0
    if not bot.permission.get('pvp', True):
        return 1.0
    pvp = o['aggression'] * (0.5 + o['rivalry'])
    if kind == 'ctb':
        import capture_beacon as CB
        if bot.level < CB.D.get('min_level', 13):
            return 1.0
        return 1.0 + (0.4 if m == CB.X2.get(bot.company) else 0.8) * pvp
    return 1.0 + pvp


def decision(bot, y, now=None):
    """The bot's new goal (the same one if unchanged). The running goal's commitment and the LLM intent are taken into account."""
    now = now or time.time()
    from . import weapons as WP, skylab as SK, appearance as GR
    from .goals import shopping as SHP
    kept = SHP.held(bot)                               # the uridium it saves for its ship wish is out of reach of these purchases
    bot.k['uridium'] -= kept
    try:
        WP.resupply(bot)                               # buys when ammo and rockets run low (like a player, between jobs)
        SK.invest(bot, now)                            # upgrades Skylab (if money and resources allow)
        GR.shopping(bot, now)                          # ship design and drone formation (by showiness and money)
        from . import pet as BP
        BP.buy(bot)                                    # the P.E.T. (R.E.X.) once it has spare uridium
        from . import technology as TECH
        TECH.produce(bot)                                # Assembly: technology items
        TECH.resupply(bot)                               # launcher rocket
        from . import loot as LT, galaxy_gates as GT
        LT.assembly(bot)                                # Assembly: the most valuable recipe whose materials it has (key, item ...)
        GT.generator(bot)                                 # Galaxy Gate generator: a spin if it has energy (or uridium)
        from . import modes as MD
        MD.passive(bot, now)                              # Dispatch, Galaxy Trek
    finally:
        bot.k['uridium'] += kept
    MD.after_match(bot, now)                          # a match it just played: history, mood, teammates
    b = Context(bot, y, now)
    current = bot.target
    mood = bot.mood
    mood.update(now)
    intent = bot.k.get('intent')
    if intent and intent.get('end_time', 0) < now:
        intent = bot.k['intent'] = None
    duration = now - bot.goal_start
    run = current is not None and current.name in ('gate', 'mod', 'pvp_match') and not bot.plan.get('finished')   # the intent must not split the run: there is no way from there
    commit = bot.plan.get('min', getattr(current, 'min_sec', 0)) if current is not None else 0
    if current is not None and not current.finished(bot, b) and (run or duration < commit and not intent):
        urgent = [h for h in GOALS.values() if h.urgent and h is not current and allowed(h, y) and h.eligible(bot, b)]
        if not urgent:
            shop = GOALS.get('shopping')
            if (not run and shop is not None and current is not shop and allowed(shop, y) and bot.r.random() < 0.2
                    and b.shopping[0] is not None):
                from .goals import shopping as SH
                SH.buy(bot, b.shopping[0])            # pops into the shop between two kills and goes on with the same job
            return current
    candidates = []
    for h in GOALS.values():
        if not allowed(h, y) or not h.eligible(bot, b):
            continue
        p = h.points(bot, b)
        if h is current and not h.finished(bot, b):
            # commitment: a human does not abandon a job halfway; it decreases as they get bored (as the same job drags on)
            p += 0.25 * max(0.0, 1 - mood['boredom']) + (0.3 if duration < commit else 0)
        if intent and intent.get('target') == h.name:
            p += intent.get('pay', 0.6)
        p *= PL.goal_factor(bot, h.name, now)              # what this pilot enjoys, today's session theme (playstyle.py)
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
        bot.plan.setdefault('min', sec.min_sec * PL.commit_factor(bot))     # how long it sticks to it this time (patience, mood)
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
