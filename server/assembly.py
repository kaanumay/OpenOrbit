"""Assembly (roadmap stage 5): production with the client's own recipes (data/recipes.json <- tools/il2cpp/client_data.py).

Flow (the save holds the login list; production requests come from the client's code):
  at login                   AssemblyRecipeContentModule: recipes and their states (Available {currentBuildCount, isNew} /
                             Build {buildAmount, remainingTimeMillis, prevBuildCount} / ReadyToCollect {prevBuildCount, buildAmount} /
                             Unavailable {type})
  AssemblyBuildRequest       {recipeLootId, targetItemId, amount}: materials are spent (inventory.py), the timer starts -> status update
                             (AssemblyRecipeStatusUpdateCommand); when the time is up: ReadyToCollect
  AssemblyCollectRequest     the result x amount is given (the shop's reward function), state Available or Unavailable by the usage limit
  AssemblyCollectAllRequest  all that are ready
  AssemblySkipRequest        remaining time with uridium (1 U per minute, adaptation)
  AssemblyRecipeSelectRequest  recipe seen (isNew is cleared)
  AssemblySetFilterRequest   the window's filter in the profile
Which recipes: those in the save's list that are open that day (ALWAYS_VISIBLE and ON_SCHEDULE on the calendar; single player: all always
open) and those not in the save (event_recipes): ones that ask for an event currency (event_calendar.py 'currency') while the event runs or
when the player holds that currency, Champion Token ones while the player holds tokens, the rest (designs, ONLY_WHEN_OWNED drafts;
single-player adaptation) always; ones that ask for a material with no source yet (NO_SOURCE) and test recipes are hidden. A recipe that
asks for the currency of an active event is timed (AssemblyRecipeTemporaryTypeModule: the event's remaining time); a recipe that drops off
the list is removed with AssemblyRecipeRemoveCommand (those with production in progress stay). Usage: ALWAYS_USABLE unlimited, USABLE_ONCE
once, USABLE_ONCE_PER_SCHEDULE / USABLE_LIMIT_PER_SCHEDULE once / max_uses times per period (period: the event period if the recipe is tied
to an active event, otherwise the calendar day). CostScalingFactor: within the same period the materials grow by this ratio with every
production. Recipes that ask for a ship (Plus ships): the base ship is spent from the inactive ones; the client's counter also counts the
active one (inventory.client_count); only when producing with the active ship does the game show its "ship in use" warning.
In the profile: assembly {uretim: {recipe: {count, end_time, previous}}, counter: {recipe: total}, daily: {recipe: [day, count]}, seen: [recipe],
filters: {}}.
"""
import json, math, os, time

import inventory as INV
import settings as SET
import technology as TECH
import upgrades as UPG
import ranks as RT
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'data', 'recipes.json'), encoding='utf8'))['recipes']
INGREDIENTS = {loot for r in T.values() for loot in r.get('parts', {})}      # counters sent at login (shop.count_msgs)
ALREADY_OWNS, ALREADY_USED, ALREADY_USED_LIMIT = 0, 1, 2          # RecipeUnavailableType (client)
# recipes unlocked by a condition (wiki): the Spartan drone design once the Kronos gate is completed
UNLOCK = {'recipe_blueprint-spartan': lambda p: ((p.d.get('kapilar') or {}).get('kapilar', {}).get('kronos') or {}).get('done', 0) > 0,
          'recipe_blueprint-immunizer-cpu': lambda p: True}        # Quarantine Zone is permanent in single player (stage 8)
SKIP_U_PER_MIN = 1                                                # adaptation: remaining minutes cost 1 uridium
NO_LIMIT = 'ALWAYS_USABLE'
# materials with no source yet (roadmap E8: Flower box hunt): their recipes are hidden. The source of Proxium (Permafrost Fissure's UFO and Ufonit
# boxes: event_gates.json 'permafrost') and of Duothrin, Trittothrin, Quadrothrin made from it now exists; so does that of Opitite and
# Tarnom (Plutus' Experiments: plutus_experiments.py)
NO_SOURCE = {'resource_collectable_flower-token'}
CHAMPION = 'resource_collectable_champion-token'                  # monthly reward (rank.py): token recipes while the player holds tokens
TEST = 'recipe_recipe-test'
BOT = set()                       # Saturn Transmitter (recipe_blueprint-ss-cpu) open: Saturn aliens count as players in the PvP quest
                                  # (official forum 127576; combat_items alien_cpu ss-cpu, world npc_reward)
# official server record (2026-10-25): at login, after the recipe list, two empty lists and the window's three filters (filterType 2, 1, 0;
# all categories if none is stored)
FILTER_TYPES = (2, 1, 0)
ALL_FILTERS = ['ships_and_designs', 'ammunition', 'weapons', 'pet', 'generators', 'drones', 'extras', 'boosters', 'hardware', 'modules',
               'techs']
LIST_CHECK_SEC = 60                                                # recipe list when an event starts / ends
# recipes that give a leveled P.E.T. gear/protocol give level 4 (client text: "Obtain Targeting Protocol X Level 4 for your
# P.E.T."); equipping depends on the P.E.T. level (pet.level_need). Level 1 used to be given: the hangar showed "Level 0" and every P.E.T. could equip it
PET_LEVEL = 4


def event_recipes(p, now=None):
    """Recipes not in the save: ones that ask for an event currency (event_calendar.py 'currency') while the event runs or when the player holds that
    currency, Champion Token ones while the player holds tokens, the rest always; excluded are ones that ask for a material with no source,
    test recipes, ones unlocked by a condition (UNLOCK) and ones that ask for a bot player (BOT)."""
    import event_calendar as CAL
    currency = {l for e in CAL.EVENTS.values() for l in e.get('currency', [])} | {CHAMPION}
    cur = {l for k in CAL.active(now) for l in CAL.EVENTS[k].get('currency', [])} | {l for l in currency if p.resource(l) > 0}
    run, chromin = chromin_recipes(now), set(CAL.EVENTS.get('chromin', {}).get('currency', []))
    out = []
    for k, r in T.items():
        ps = set(r['parts'])
        if 'recorded' in r or k in UNLOCK or k in BOT or k.startswith(TEST) or ps & NO_SOURCE:
            continue
        if run is not None and ps & chromin and k not in run:          # Chromin run: only that run's recipes
            continue
        if ps & cur or not ps & currency:
            out.append(k)
    return sorted(out)


def chromin_recipes(now=None):
    """Recipes of the running Chromin Rush run (events.json chromin.run_recipes: official forum, 6-9 recipes per run) or
    None (no run, or its list is unknown). Runs after the last known day repeat every 52 weeks: the day in earlier years is looked up."""
    import datetime
    import event_calendar as CAL
    span = CAL.period('chromin', now)
    runs = CAL.EVENTS.get('chromin', {}).get('run_recipes') or {}
    if not span or not runs:
        return None
    start = datetime.date.fromtimestamp(span[0])
    for k in range(40):
        d = (start - datetime.timedelta(days=364 * k)).isoformat()
        if d in runs:
            return set(runs[d])
    return None


def recipe_event(key, now=None):
    """The active event that ties the recipe to its currency (event_calendar.py 'currency'; None if there is none)."""
    import event_calendar as CAL
    ps = set(T[key]['parts'])
    return next((k for k in sorted(CAL.active(now)) if ps & set(CAL.EVENTS[k].get('currency', []))), None)


def recorded_end(key, now=None):
    """End of a timed recipe on the official server (recipes.json temporary: "season" is the end of the Season Pass season, a number is the end in the save) or
    None (untimed, end already passed, or tied to an event currency: its duration comes from the local calendar, recipe_event)."""
    import event_calendar as CAL
    g = T[key].get('temporary')
    if g and set(T[key]['parts']) & {l for e in CAL.EVENTS.values() for l in e.get('currency', [])}:
        return None
    if g == 'season':
        import season
        g = season.current_end(now)
    return g if isinstance(g, (int, float)) and g > (now or time.time()) else None


def period_of(key, now=None):
    """The period for 'once / at most per period' and for CostScalingFactor: for a recipe tied to an active event, the day the event started;
    otherwise the calendar day (a forced-open event has no period: the day)."""
    import event_calendar as CAL
    ev = recipe_event(key, now)
    span = CAL.period(ev, now) if ev else None
    return '%s:%s' % (ev, today(span[0])) if span else today(now)


def mod(name, **f):
    f['_'] = name
    return f


def today(now=None):
    return time.strftime('%Y-%m-%d', time.localtime(now or time.time()))


class Assembly:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # shop (reward and inventory updates; binds the session)
        self.send = None              # notification of a production finished by the timer (binds the session)
        self.next_tick = self.next_list = 0.0
        self.free_last = SET.get('assembly_free')
        self.shown = None             # the recipe list in the client (content); ones that drop off when the event ends are removed
        self.up = UPG.Upgrade(profile, log)   # Upgrade and Disassembly tabs (upgrades.py)

    @property
    def st(self):
        d = self.p.d.setdefault('assembly', {})
        for k, v in (('uretim', {}), ('counter', {}), ('daily', {}), ('seen', []), ('filters', {})):
            d.setdefault(k, v)
        return d

    # ------------------------------------------------------------ tarifler
    def visible(self):
        """Recipes shown in the window, in the save's order; then ONLY_WHEN_OWNED recipes held in storage, ones unlocked by a condition, ones not in the
        save (event_recipes) and ones with production in progress or uncollected (even if the event has ended)."""
        out = sorted((k for k, r in T.items() if 'recorded' in r and k not in BOT), key=lambda k: T[k]['recorded'])
        out += sorted(k for k, r in T.items() if 'recorded' not in r and r['visibility'] == 'ONLY_WHEN_OWNED' and self.p.resource(k) > 0)
        out += [k for k, cond in UNLOCK.items() if k not in out and cond(self.p)]
        seen = set(out)
        out += [k for k in event_recipes(self.p) if k not in seen]
        seen = set(out)
        return out + sorted(k for k in self.st['uretim'] if k in T and k not in seen)

    def used_today(self, key):
        """Production count in this period (period_of: the event period or the day)."""
        g = self.st['daily'].get(key)
        return g[1] if g and g[0] == period_of(key) else 0

    def limit_left(self, key):
        """Remaining uses (None: unlimited)."""
        r = T[key]
        if r['usage'] == NO_LIMIT:
            return None
        if r['usage'] == 'USABLE_ONCE':
            return max(0, 1 - self.st['counter'].get(key, 0))
        cap = 1 if r['usage'] == 'USABLE_ONCE_PER_SCHEDULE' else (r['max_count'] or 1)
        return max(0, cap - self.used_today(key))

    def cost(self, key, amount):
        """Materials x amount; CostScalingFactor: each production today costs one more layer (1.1 ...)."""
        if SET.get('assembly_free'):
            return {}
        r = T[key]
        f = r['scale'] ** self.used_today(key) if r['scale'] != 1 else 1
        return {loot: int(math.ceil(n * f * amount)) for loot, n in r['parts'].items()}

    def status(self, key, now=None):
        now = now or time.time()
        b = self.st['uretim'].get(key)
        if b:
            if now < b['end_time']:
                return mod('AssemblyRecipeBuildStatusModule', buildAmount=b['count'], remainingTimeMillis=int((b['end_time'] - now) * 1000),
                           prevBuildCount=b['previous'])
            return mod('AssemblyRecipeReadyToCollectStatusModule', prevBuildCount=b['previous'], buildAmount=b['count'])
        left = self.limit_left(key)
        if left == 0:
            kind = ALREADY_USED if T[key]['usage'] in ('USABLE_ONCE', 'USABLE_ONCE_PER_SCHEDULE') else ALREADY_USED_LIMIT
            return mod('AssemblyRecipeUnavailableStatusModule', type=kind)
        return mod('AssemblyRecipeAvailableStatusModule', currentBuildCount=self.build_count(key), isNew=key not in self.st['seen'])

    def build_count(self, key):
        """The client's "Crafting Limit: <this>/<MaxUses>" counter; reaching MaxUses locks Build. For unlimited recipes MaxUses is the maximum amount of one
        production (U-LF-4, LF-P01 ...): the counter is 0 (live test H32: Build locked after one production)."""
        r = T[key]
        if r['usage'] == NO_LIMIT:
            return 0
        if r['usage'] == 'USABLE_ONCE':
            return self.st['counter'].get(key, 0)
        return self.used_today(key)

    def recipe(self, key, now=None):
        """A recipe that asks for the currency of an active event is timed (remaining time in the window); one that is timed on the official server (recipes.json temporary)
        is timed until the end of the Season Pass season or the end in the save; other recipes are untimed."""
        import event_calendar as CAL
        now = now or time.time()
        ev = recipe_event(key, now)
        end = None if ev else recorded_end(key, now)
        typ = (mod('AssemblyRecipeTemporaryTypeModule', remainingTimeMillis=CAL.time_left(ev, now) * 1000) if ev else
               mod('AssemblyRecipeTemporaryTypeModule', remainingTimeMillis=int((end - now) * 1000)) if end else
               mod('AssemblyRecipeRegularTypeModule'))
        return mod('AssemblyRecipeModule', recipeLootId=key, targetItemId=0, type=typ, status=self.status(key, now))

    def content(self):
        """The recipe list at login (in place of the command in the save)."""
        keys = self.visible()
        self.shown = set(keys)
        return ('AssemblyRecipeContentModule', {'recipes': [self.recipe(k) for k in keys] + self.up.recipes()})

    def login_msgs(self):
        """At login: the recipe list, two empty lists and the filters (the official server's order)."""
        return [self.content()] + [('AssemblyRecipeContentModule', {'recipes': []})] * 2 + self.filter_msgs()

    def filter_msgs(self):
        """The window's filters (the AssemblySetFilterRequest module, per filterType; all categories if none is stored): sent back
        at login (E10)."""
        return [('AssemblyWindowSettingsModule', {k: v for k, v in m.items() if k != '_'})
                for m in (self.st['filters'].get(str(t)) or {'filterType': t, 'assemblyItemFilters': list(ALL_FILTERS)}
                          for t in FILTER_TYPES)]

    def update(self, key, target=0, now=None):
        return ('AssemblyRecipeStatusUpdateCommand', dict(targetItemId=target, status=self.status(key, now), lootId=key))

    # ------------------------------------------------------------ requests
    def build(self, f):
        key, amount = f.get('recipeLootId', ''), max(1, int(f.get('amount') or 1))
        r = T.get(key)
        if not r or key not in self.visible() or key in self.st['uretim']:
            self.log('   Assembly: cannot produce %s (%s)' % (key, 'no such recipe' if not r else 'in progress' if key in self.st['uretim'] else 'not visible'))
            return [self.update(key)] if r else []
        left = self.limit_left(key)
        if left is not None:
            amount = min(amount, left)
        if amount <= 0 or (not r['stackable'] and amount > 1):
            amount = 1 if amount > 0 else 0
        if amount <= 0:
            return [self.update(key)]
        need = self.cost(key, amount)
        miss = INV.missing(self.p, need)
        if miss:
            self.log('   Assembly: not enough materials %s x%d (missing %s)' % (key, amount, miss))
            in_use = [l for l in miss if l.startswith('ship_') and INV.client_count(self.p, l) >= need[l]]
            # the base ship exists but is active: the game's rule and text ("You cannot upgrade a ship that is currently in use. Please change ships
            # before upgrading."); the client code that shows this warning (AssemblyViewSystem.PromptShipChange) is never called
            return ([legacy('0|A|STM|assembly_warning_ship_in_use')] if in_use else []) + [self.update(key)]
        removed = INV.spend(self.p, need, reason='buy_SPECIAL', detail=key)
        now = time.time()
        with self.p.lock:
            self.st['uretim'][key] = dict(count=amount, end_time=now + SET.duration(r['sure_sn'] * amount, 'assembly'), previous=self.st['counter'].get(key, 0))
            if key not in self.st['seen']:
                self.st['seen'].append(key)
            if r['usage'] != NO_LIMIT or r['scale'] != 1:
                self.st['daily'][key] = [period_of(key), self.used_today(key) + amount]
            self.p.dirty = True
        self.p.ach('assembly_build', recipe=key, count=amount)
        self.log('   Assembly: %s x%d started (%d s; %s)' % (key, amount, r['sure_sn'] * amount, need))
        return INV.update_msgs(self.m, self.p, list(need), removed) + [self.update(key, f.get('targetItemId', 0))]

    def collect(self, f, now=None):
        key = f.get('recipeLootId', '')
        b = self.st['uretim'].get(key)
        now = now or time.time()
        if not b or now < b['end_time']:
            return [self.update(key)] if key in T else []
        with self.p.lock:
            del self.st['uretim'][key]
            self.st['counter'][key] = self.st['counter'].get(key, 0) + b['count']
            self.p.dirty = True
        msgs = []
        for loot, n in T[key]['result'].items():
            msgs += self.grant(loot, n * b['count'])
        self.p.ach('assembly_collect', recipe=key, count=b['count'])
        # logbook (MSJ-10): the client (ReturnLogBookInfoText) translates the "his_assembly_..." text; %recipename% is the name of the lootId in info
        # (items_<lootId>_fullname; the result's name exists for all of them, the recipe's name is missing for 35 recipes), %buildamount% is count
        RT.note(self.p, 'his_assembly_recipe_collected_multi' if b['count'] > 1 else 'his_assembly_recipe_collected',
                next(iter(T[key]['result'])), b['count'])
        self.log('   Assembly: %s x%d collected (%s)' % (key, b['count'], T[key]['result']))
        return msgs + [self.update(key, f.get('targetItemId', 0))]

    def grant(self, loot, n):
        """Result: a technology item goes to the counter, the rest via the shop's reward function (ammo, equipment, ship, booster, resource ...)."""
        if loot.startswith('tech_'):
            TECH.add(self.p, loot, n)
            return INV.update_msgs(self.m, self.p, [loot])
        if self.m:
            return self.m.reward(loot, n, level=PET_LEVEL)
        self.p.add_resource(loot, n)
        return []

    def collect_all(self, f):
        """AssemblyCollectAllRequest.allRequests: AssemblyRecipeKeyModule {lootId, targetId}."""
        msgs = []
        before = self.up_state()
        for c in f.get('allRequests') or []:
            g = dict(recipeLootId=c.get('lootId') or c.get('recipeLootId', ''), targetItemId=c.get('targetId') or c.get('targetItemId', 0))
            msgs += self.up.collect(g) if g['recipeLootId'] in UPG.UP else self.collect(g)
        return msgs + ([self.content()] if self.up_state() != before else [])        # H61

    def skip(self, f):
        key = f.get('recipeLootId', '')
        b = self.st['uretim'].get(key)
        now = time.time()
        if not b or now >= b['end_time']:
            return [self.update(key)] if key in T else []
        price = max(1, int(math.ceil((b['end_time'] - now) / 60.0)) * SKIP_U_PER_MIN)
        if INV.missing(self.p, {'currency_uridium': price}):
            self.log('   Assembly: not enough uridium to skip (%d)' % price)
            return [self.update(key)]
        INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail=key)
        with self.p.lock:
            b['end_time'] = now
            self.p.dirty = True
        self.log('   Assembly: %s time skipped (%d U)' % (key, price))
        return INV.update_msgs(self.m, self.p, ['currency_uridium']) + [self.update(key)]

    def select(self, f):
        key = f.get('recipeLootId', '')
        if key not in T or key in self.st['seen']:
            return []
        with self.p.lock:
            self.st['seen'].append(key)
            self.p.dirty = True
        return [self.update(key)]

    def set_filter(self, f):
        with self.p.lock:
            self.st['filters'][str(f.get('filterType', 0))] = f.get('assemblyWindowSettingsModule') or {}
            self.p.dirty = True
        return []

    def up_state(self):
        return {k: b['end_time'] for k, b in self.up.st.items()}

    def handle(self, name, f):
        self.up.m, self.up.send, self.up.refresh = self.m, self.send, self.content
        if self.up.handles(name, f):
            before = self.up_state()
            msgs = self.up.handle(name, f)
            if self.up_state() != before:
                # targeted upgrade added, skipped or collected: the client applies the status update only to the (recipe, target) row in its list
                # and redraws the Update/Upgrade panel only when the recipe list arrives (live test H39: after Build the upgrade was not
                # shown; H61: after Skip and Collect the panel stayed on the old counter / on "Collect")
                msgs = msgs + [self.content()]
            return msgs
        fn = {'AssemblyBuildRequest': self.build, 'AssemblyCollectRequest': self.collect, 'AssemblyCollectAllRequest': self.collect_all,
              'AssemblySkipRequest': self.skip, 'AssemblyRecipeSelectRequest': self.select,
              'AssemblySetFilterRequest': self.set_filter}.get(name)
        return fn(f) if fn else None

    # ------------------------------------------------------------ time
    def tick(self, now):
        """Every second: productions whose time is up become ready (ReadyToCollect to the client); every minute the recipe list (event ended:
        AssemblyRecipeRemoveCommand, started: new list)."""
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        free = SET.get('assembly_free')
        if free != self.free_last:                # setting changed: the client's material counters are refreshed
            self.free_last = free
            if self.m and self.send:
                self.send(self.m.count_msgs())
        if now >= self.next_list and self.shown is not None and self.send:
            self.next_list = now + LIST_CHECK_SEC
            keys = self.visible()
            gone = sorted(self.shown - set(keys))
            if gone:
                self.send([('AssemblyRecipeRemoveCommand', {'recipes': [mod('AssemblyRecipeKeyModule', lootId=k, targetId=0)
                                                                         for k in gone]})])
                self.log('   Assembly: %d recipes dropped off the list (%s ...)' % (len(gone), gone[0]))
            if set(keys) - self.shown:
                self.send([self.content()])
            self.shown = set(keys)
        self.up.m, self.up.send, self.up.refresh = self.m, self.send, self.content
        self.up.tick(now)
        done = [k for k, b in self.st['uretim'].items() if not b.get('notified') and now >= b['end_time']]
        for k in done:
            with self.p.lock:
                self.st['uretim'][k]['notified'] = True
                self.p.dirty = True
        if done and self.send:
            self.send([self.update(k, now=now) for k in done])
