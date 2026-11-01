"""Bot manager: loads the pack, runs the bots' online schedule, decisions and abstract simulation, and saves the state.

A single instance on the game server (BOT): game.py provides the pack via the OO_BOT environment variable, and the manager runs tick() once a second in its own
thread. The simulation script (tools/bot_simulation.py) and the tests drive the same class with a fake clock (the now parameter).

On each tick only the bots that have work are processed: offline ones ask "should I log in" once a minute; online ones think at their own decision moments,
abstract effects are applied in a batch every ABSTRACT_SEC. The worlds (ship.py) learn the bots on their maps through hooks.
"""
import json, os, random, threading, time, traceback

import map_links as H
from . import brain as B
from . import catalog as K
from . import personality as PS
from . import memories as MEM
from . import abstract_sim as S
from .state import Bot
from . import speech as SPC
from . import game_settings as GS
from .chat_engine import ChatEngine
from .goals import quest as QU
from .goals import shopping as SHOP

ABSTRACT_SEC = 5.0
PVP_SEC = 10.0
SIGNUP_SEC = 60.0
LOGIN_RETRY_SEC = 60.0
VERSION = 1
ACTIVE = None                   # the game server's manager (game.py sets it up; ship.py reads it)
PRIME_POPULATION = 1.3              # multiplier for the tendency to be online in prime time
FRONTS = (16, 16, 29, 13, 14, 15)        # 4-4 iki kat, 4-5, 4-1, 4-2, 4-3

DEFAULTS = {                 # the pack's settings (panel/bots.py validates the same keys)
    'speed': 1.0,                # progress speed multiplier
    'online_ratio': 0.6,     # multiplier for the bots' tendency to be online
    'max_online': 0,     # most online at the same time (0: unlimited)
    'catchup_hours': 4,          # most hours simulated from the time elapsed while the player was away (0: no catch-up)
    'catch_up_rate': 0.35,       # progress rate during catch-up
    'signup_sec': 15,            # progressive: on average one new pilot signs up per company every this many seconds (0: all from the start)
    'company_power': [1.0, 1.0, 1.0],        # companies' development multiplier (MMO, EIC, VRU)
    'jumpstart_hours': 60,      # jumpstart: average game hours (lognormal distribution)
    'pvp_level': 6,
    'foreign_map': True,    # can enter other companies' maps
    'chat_min': 6,            # most bot lines per minute in global/company chat
    'help_max': 3,        # most bots that come to one call for help
    'max_concrete': 40,        # most bots shown as ships on the player's map
    'bots_per_clan': 12,         # one bot clan per this many bots
    'rude_chat': 1,          # trash talk: 0 off, 1 mild, 2 harsh, 3 very harsh (no swearing and no real threats in any of them)
    'moderator': False,        # chat moderator bots (bot/moderation.py)
    'mod_count': 2,
    'rule_caps': True, 'rule_flood': True, 'rule_insult': True, 'rule_ads': True,
    'mute_min': 10,           # mute duration
    'ban_threshold': 3,           # ban after this many mutes
    'ban_hours': 24,
    'prime_start': 19,     # evening prime hours (local time): online and PvP rise, companies gather on one map
    'prime_end': 23,
    'prime_pvp': 2.0,          # multiplier for PvP desire in prime time (1: no difference)
    'big_battle': True,       # in prime time the companies' PvP bots gather on a shared front map
    'permissions': {'shop': True, 'quest': True, 'pvp': True, 'sohbet': True, 'clan': True, 'clan_found': True, 'friend': True,
                'group': True, 'auction': True, 'attack_player': True, 'assist': True, 'box_stealing': True, 'cargo': True, 'rocket': True, 'custom_ammunition': True, 'ekstra': True, 'mine': True, 'lab': True, 'skylab': True, 'technology': True, 'booty': True, 'assembly': True, 'gate': True, 'event': True, 'modes': True, 'clan_diplomacy': True, 'clan_order': True, 'gate_filler': True},
}


class Manager(ChatEngine):
    def __init__(self, package, state_path=None, log=print, now=None):
        self.package = package
        self.state_path = state_path
        self.log = log
        self.settings = dict(DEFAULTS, **(package.get('settings') or {}))
        self.settings['permissions'] = dict(DEFAULTS['permissions'], **(self.settings.get('permissions') or {}))
        self.mode = package.get('mode', 'normal')
        self.game_settings = GS.Profile(self.settings.get('game_settings'))      # the bots' game-setting profile (separate from the player's)
        self.lock = threading.RLock()
        self.bots = []
        self.name_index = {}                  # name lowercased -> Bot
        self.on_map = {}             # map -> {Bot}: online bots
        self.worlds = []             # hooks of ship.py: map_changed(bot, old), bot_online(bot, open)
        self.humans = {}             # name lowercased -> (name, map, company): real players on the server (the worlds report them)
        self.last_pvp = self.last_save = self.now = now or time.time()   # now: the simulation's clock (correct with a fake clock too)
        self.running = False
        self._thread = None
        self.society = False            # on the game server tied to the community and chat (society.register)
        self.last_social = 0.0
        self.signup_queue = {}         # company -> [Bot]: pilots that have not signed up yet (progressive, they join in turn)
        self.next_signup = {}        # company -> moment
        self.prepare_chat()
        self.load(now)

    # ------------------------------------------------------------ settings
    def setting(self, name, vars=None):
        return self.settings.get(name, vars)

    def permission(self, name):
        return bool(self.settings['permissions'].get(name, True))

    def speed(self, bot):
        """The bot's progress speed: the pack's speed x its company's strength."""
        fg = self.settings.get('company_power') or [1, 1, 1]
        return float(self.settings.get('speed', 1.0)) * float(fg[bot.firma - 1])

    # ------------------------------------------------------------ loading / saving
    def load(self, now=None):
        now = now or time.time()
        save = {}
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding='utf8') as f:
                    save = json.load(f)
            except (OSError, ValueError) as e:
                self.log('   bots: could not read state (%s), starting over' % e)
        old = {str(k): v for k, v in (save.get('bots') or {}).items()}
        self.name_log_n = int(save.get('name_log') or 0)
        new_ = []
        # progressive new pack: pilots do not join the game all at once but one by one as if signing up on a real server (performance,
        # natural spread across the maps); the jumpstart cast counts as having already played
        ordered = self.mode != 'simple' and self.package.get('progression') != 'jumpstart' and self.setting('signup_sec', 15) > 0
        from . import llm_provider as PRV
        multilingual = PRV.multilingual()
        for roster_row in self.package.get('roster', []):
            k = old.get(str(roster_row['no']))
            if k is None:
                k = dict(no=roster_row['no'], name=roster_row['name'], company=roster_row['company'], personality=roster_row['personality'], registered=not ordered)
                new_.append(k)
            else:
                k.update(name=roster_row['name'], company=roster_row['company'], personality=roster_row['personality'])      # the name may have been changed in the panel
            if self.mode == 'advanced' and not multilingual:
                k['personality'] = dict(k['personality'], lang='en')      # the built-in language model is English only (llm.py; free with other providers)
            b = Bot(k)
            b.permission = self.settings['permissions']
            b.rude = int(self.setting('rude_chat', 1))       # rough chat level (llm.style, chat_engine)
            b.hour = lambda: self.now
            b.game_settings = self.game_settings
            b.memory.listener = (lambda b: lambda name, kind, now: MEM.from_event(self, b, name, kind, now))(b)     # memory book (strong provider)
            b.next_login = now + b.r.uniform(0, 20)
            self.bots.append(b)
            self.name_index[b.name.lower()] = b
        self.apply_name_log(loading=True)            # bots renamed or deleted in the panel while the game was closed
        if self.mode == 'simple':
            from . import simple
            simple.prepare(self, now)
            return
        if new_ and self.package.get('progression') == 'jumpstart':
            self.jumpstart([b for b in self.bots if b.k in new_], now)
        for b in sorted(self.bots, key=lambda b: b.r.random()):
            if not b.saved:
                self.signup_queue.setdefault(b.firma, []).append(b)
        for f in self.signup_queue:
            self.next_signup[f] = now + self.setting('signup_sec', 15) * b.r.uniform(0.2, 1.0)
        t = save.get('t')
        if t and self.setting('catchup_hours', 0) > 0 and now - t > 600:
            self.catch_up(min(now - t, self.setting('catchup_hours') * 3600) * self.setting('catch_up_rate', 0.35), now)
        self.initial_population(now)
        from . import moderation as MOD
        MOD.sec(self)

    def apply_name_log(self, loading=False):
        """Bots renamed or deleted in the panel (name_log.py): the running bots' names, the bots' memory and contact lists; while the game
        is open (panel channel) also the clans and the connected players' contact lists. -> number of events applied."""
        import name_log as NL
        new_ = NL.events_since(getattr(self, 'name_log_n', 0))
        if not new_:
            return 0
        from . import society
        lists = ('friend', 'incoming', 'outgoing', 'declined', 'blocked')
        with self.lock:
            if not loading:
                for e in new_:
                    if e['type'] != 'name':
                        continue
                    b = self.name_index.pop(NL._k(e['eski']), None)
                    if b is not None:
                        b.k['name'] = e['new']
                        self.name_index[b.name.lower()] = b
                        for x in self.package.get('roster', []):
                            if x['no'] == b.k['no']:
                                x['name'] = e['new']
                        if b.profile is not None:
                            society.update(b)          # its name in the game (its ship gets the new name at the next appearance)
            for b in self.bots:
                h = b.memory.d
                for e in new_:
                    if e['type'] == 'name' and NL._k(e['eski']) in h:
                        x = h.pop(NL._k(e['eski']))
                        x['name'] = e['new']
                        h[NL._k(e['new'])] = x
                    elif e['type'] == 'delete':
                        h.pop(NL._k(e['name']), None)
                r = b.k.get('contacts') or {}
                for name in lists:
                    if isinstance(r.get(name), list):
                        x = NL.apply_list(r[name], new_)
                        if x is not None:
                            r[name] = x
            self.name_log_n = new_[-1]['n']
        society._PEOPLE['t'] = 0
        if not loading:
            import clan as KL
            import community as TP
            NL.apply_clans(KL)
            for k in list(TP.all_().values()):
                if k.name.lower() not in self.name_index:
                    NL.apply_profile(k.profile)           # the connected players' contact lists and the clan copy
            self.log('   bots: name record applied (%d events)' % len(new_))
        return len(new_)

    def save(self, now=None):
        if not self.state_path:
            return
        now = now or time.time()
        with self.lock:                                  # the text inside the lock: so the world loop does not see it half done while adding to the dicts
            d = dict(version=VERSION, t=now, name_log=self.name_log_n, bots={str(b.k['no']): b.save() for b in self.bots})
            if self.llm is not None:
                d['llm'] = self.llm.summary()                    # the panel's usage line (last hour: requests, tokens)
            text = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        tmp = self.state_path + '.tmp'
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(tmp, 'w', encoding='utf8') as f:
            f.write(text)
        os.replace(tmp, self.state_path)
        self.last_save = now

    # ------------------------------------------------------------ running
    def launch(self):
        if self._thread:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, name='bots', daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        try:
            self.save()
        except Exception as e:                           # on shutdown the other saves (guests, clan) must not be skipped
            self.log('   botlar: kaydedilemedi (%r)' % e)

    def _loop(self):
        while self.running:
            t0 = time.time()
            try:
                self.tick(t0)
            except Exception:
                self.log('   bots: tick error\n' + traceback.format_exc())
            time.sleep(max(0.05, 1.0 - (time.time() - t0)))

    def tick(self, now=None):
        now = self.now = now or time.time()
        with self.lock:
            online = sum(1 for b in self.bots if b.online)
            limit = self.setting('max_online', 0) or len(self.bots)
            online += self.signup_tick(now, online, limit)
            for b in self.bots:
                if not b.saved:
                    continue
                try:                                     # one bot's error (a broken or old record) must not stop the others and the save
                    if not b.online:
                        if now >= b.next_login:
                            b.next_login = now + LOGIN_RETRY_SEC * b.r.uniform(0.7, 1.3)
                            if online < limit and self._should_login(b, now):
                                self.entry(b, now)
                                online += 1
                        continue
                    self.bot_tick(b, now)
                    if not b.online:
                        online -= 1
                except Exception:
                    self.bot_error(b)
            if now - self.last_pvp >= PVP_SEC:
                self.last_pvp = now
                try:
                    self.pvp_tick(now)
                except Exception:
                    self.log_error('pvp')
            for name, fn in (('society', lambda: self._society_tick(now)),
                           ('sohbet', lambda: self.chat_tick(now)), ('llm', lambda: self.llm.tick(now) if self.llm else None)):
                try:
                    fn()
                except Exception:
                    self.log_error(name)
        if now - self.last_save >= SIGNUP_SEC:
            self.save(now)

    def _society_tick(self, now):
        if self.society and now - self.last_social >= ABSTRACT_SEC:
            self.last_social = now
            from . import society
            society.tick(self, now)

    def bot_error(self, b):
        """Once per bot to the log (so the same trace is not dumped every second); after 10 errors the bot rests in this session."""
        n = b.__dict__['_error'] = b.__dict__.get('_error', 0) + 1
        if n == 1:
            self.log('   bots: %s raised an error (skipped)\n%s' % (b.name, traceback.format_exc()))
        if n >= 10:
            b.online = False
            b.next_login = self.now + 3600
            self.on_map.get(b.game_map, set()).discard(b)

    def log_error(self, name):
        c = self.__dict__.setdefault('_errors', {})
        c[name] = c.get(name, 0) + 1
        if c[name] in (1, 100, 10000):
            self.log('   bots: %s error (time %d)\n%s' % (name, c[name], traceback.format_exc()))

    def bot_tick(self, b, now):
        self.now = now
        on_run = b.target is not None and b.target.name in ('gate', 'mod') and not b.plan.get('finished')
        if now >= b.session_end and not b.en_route and b.dead_until <= now and not on_run:   # does not leave before a gate/mode run is finished
            if b.body is not None and b.body.alive and not b.__dict__.get('logout_ready'):
                # a bot visible on your map does not vanish where it is: it flies to its station or a portal and leaves there (exit_request)
                if not b.__dict__.get('exit_request'):
                    b.exit_request = now
                if now - b.exit_request < 90:
                    return
            b.exit_request = b.logout_ready = None
            self.exit(b, now)
            return
        if b.dead_until > now:
            return
        if now >= b.next_decision:
            B.decision(b, self, now)
            b.next_decision = now + B.next_decision_interval(b)
        dt = now - b.last_abstract
        if dt >= ABSTRACT_SEC:
            b.last_abstract = now
            # gets tired as the session drags on (devoted ones late)
            b.mood.it(fatigue=dt / (3600.0 * (1.5 + 3 * (b.k['personality']['habit'] == 'devoted'))))
            b.ist('sure_sn', int(dt))
            from . import events as EV
            EV.battle_pass(b, min(dt, 60.0))             # pass quests and Season Pass progress as they play (limited after sleep)
            EV.season_pass(b, min(dt, 60.0))
            if b.body is None and b.target is not None:
                b.target.abstract(b, min(dt, 60.0), self)

    def signup_tick(self, now, online, limit):
        """The next pilots sign up: for each company separately, one on average every signup_sec (±33%); a new signup enters the game at once
        (at its own base, level 1) -> number who entered."""
        n = 0
        avg = float(self.setting('signup_sec', 15) or 0)
        for f, order in self.signup_queue.items():
            if not order or now < self.next_signup.get(f, 0):
                continue
            b = order.pop(0)
            b.k['registered'] = True
            b.k['registered_at'] = now                         # rank points: days since signup (society.points)
            self.next_signup[f] = now + avg * b.r.uniform(0.67, 1.33)
            if online + n < limit:
                self.entry(b, now)
                n += 1
            else:
                b.next_login = now + LOGIN_RETRY_SEC
        return n

    def prime(self, now=None):
        """Whether it is the evening's prime hours (prime_start-prime_end, local time; may cross midnight; if equal, none)."""
        h = time.localtime(now or self.now).tm_hour
        a, b = int(self.setting('prime_start', 19)), int(self.setting('prime_end', 23))
        return a < b and a <= h < b or a > b and (h >= a or h < b)

    def front(self, now=None):
        """The prime hour's big battle map: changes hour by hour, the PvP bots of the three companies meet in the same place (4-4, 4-5, 4-1/2/3)."""
        return FRONTS[int((now or self.now) // 3600) % len(FRONTS)]

    def _should_login(self, b, now):
        hour = time.localtime(now).tm_hour
        p = PS.online_tendency(b.k['personality'], hour) * self.setting('online_ratio', 0.6) * (PRIME_POPULATION if self.prime(now) else 1)
        # per-minute trial: divide the hourly tendency into minutes (average session ~1-3 hours; the equilibrium brings the online share close to the tendency)
        return b.r.random() < p / 45.0

    def initial_population(self, now):
        """When the server opens, that hour's equilibrium online population is set up at once (a player joining a real server does not see an empty universe):
        a bot is online with the share that follows from the per-minute login probability and the session length; at a random point of its session, silently."""
        hour = time.localtime(now).tm_hour
        limit = self.setting('max_online', 0) or len(self.bots)
        n = 0
        for b in sorted(self.bots, key=lambda b: b.r.random()):
            if n >= limit:
                break
            if not b.saved:
                continue
            p = PS.online_tendency(b.k['personality'], hour) * self.setting('online_ratio', 0.6) * (PRIME_POPULATION if self.prime(now) else 1)
            avg = sum(PS.HABITS[b.k['personality']['habit']][2]) / 2.0
            pay = (p / 45.0 * avg) / (1 + p / 45.0 * avg)
            if b.r.random() < pay:
                self.entry(b, now, silent=True)
                b.last_abstract = now - random.uniform(0, ABSTRACT_SEC)    # so the abstract steps do not bunch in the same tick (100+ ms under the lock every 5 s); the bot's own sequence (b.r) must not drift
                b.session_end = now + (b.session_end - now) * b.r.uniform(0.1, 1.0)
                b.next_decision = now + b.r.uniform(1, 15)
                n += 1
        self.log('   bots: %d bots started online' % n)

    def entry(self, b, now, silent=False):
        if b.game_map not in K.MAPS:                  # it had exited at a gate (or on a closed map): returns to base
            b.k['map'] = K.ev(b.firma)
            b.plan = {}
        b.online = True
        b.session_end = now + PS.session_min(b.k['personality'], b.r) * 60
        b.mood.update(now)
        b.mood.d['fatigue'] = 0.0
        b.last_abstract = now
        b.next_decision = now + b.r.uniform(2, 10)
        b.target = None
        b.__dict__.pop('_error', None)                    # the error counter is per session (when it counted for life, every single error took the bot down for 1 hour)
        self.on_map.setdefault(b.game_map, set()).add(b)
        b._event_time = now
        if not silent and self.mode != 'simple' and b.r.random() < 0.25 * b.o('talkativeness'):
            self.speak(b, b.r.choice(('global', 'company')), SPC.template(b, 'greeting'), now=now + b.r.uniform(5, 40))
        for d in list(self.worlds):
            d.bot_online(b, True)

    def exit(self, b, now):
        if b.r.random() < 0.15 * b.o('talkativeness'):
            self.speak(b, 'global', SPC.template(b, 'exit'), now=now, immediate=True)
            self.chat_tick(now)
        b.online = False
        b.next_login = now + b.r.uniform(15, 120) * 60          # after leaving it does not come in for a while
        b.target = None
        b.k['target'] = None
        b.body = None
        self.on_map.get(b.game_map, set()).discard(b)
        for d in list(self.worlds):
            d.bot_online(b, False)

    # ------------------------------------------------------------ hooks (abstract_sim.py, ship.py)
    def map_changed(self, b, old):
        if b.online:
            self.on_map.get(old, set()).discard(b)
            self.on_map.setdefault(b.game_map, set()).add(b)
        QU.advance(b, QU.VISIT_MAP, game_map=b.game_map, y=self)
        if b.game_map == K.ev(b.firma):
            QU.advance(b, QU.HOME, game_map=b.game_map, y=self)
        for d in list(self.worlds):
            d.map_changed(b, old)

    def npc_killed(self, b, tip, n=1):
        uid = K.NPC['types'].get(tip, {}).get('npc_id')
        if uid is not None and b.k.get('quest'):
            QU.advance(b, QU.KILL_NPC, n=n, npc_id=uid, game_map=b.game_map, y=self)

    def bot_died(self, b, killer):
        pass

    # ------------------------------------------------------------ queries
    def online_name(self, names):
        """The first online person (bot) among the names, or None."""
        for a in names:
            b = self.name_index.get(str(a).lower())
            if b is not None and b.online:
                return b
        return None

    def enemy_population(self, bot):
        """map -> [online enemy-company bots]."""
        return {m: [x for x in s if x.firma != bot.firma and x.dead_until <= self.now] for m, s in self.on_map.items()}

    def state(self):
        with self.lock:
            return [b.summary() for b in self.bots]

    # ------------------------------------------------------------ bot-bot PvP (abstract_sim)
    def pvp_tick(self, now):
        """Encounters between enemy bots on every map: a hunting bot (pvp target) or an aggressive one finds one of the enemies
        on the map (probability grows with the population). Concrete bots (the player's map) are not here, they really fight (ship.py)."""
        if not self.permission('pvp'):
            return
        for m, s in list(self.on_map.items()):
            if m not in K.MAPS:
                continue                                 # gate maps: each bot has its own copy
            live = [b for b in s if b.dead_until <= now and b.body is None and not b.en_route]
            if len(live) < 2 or not K.pvp_map(m, live[0].firma) and len({b.firma for b in live}) < 2:
                continue
            companies = {}
            for b in live:
                companies.setdefault(b.firma, []).append(b)
            for a in live:
                if a.dead_until > now:
                    continue
                hunt = a.target is not None and a.target.name == 'pvp'
                enemy_count = len(live) - len(companies[a.firma])     # a count instead of building an enemy list for each bot (O(n^2) in big packs)
                if not enemy_count:
                    continue
                # on X-1/X-2, attacking another company on its own company's map is allowed; encounter probability
                p = (0.12 if hunt else 0.006 * a.o('aggression')) * min(1.0, enemy_count / 3.0)
                if a.r.random() >= p:
                    continue
                f = a.r.choice([f for f in companies if f != a.firma])
                target = a.r.choice(companies[f])
                if a.k.get('clan'):
                    from . import society as TP
                    combat = [h for h in companies[f] if TP.clan_relation(a, h) == 3]
                    if combat:
                        target = a.r.choice(combat)        # clan war: a member of the enemy clan on the map first
                if target.dead_until > now or a.k.get('clan') and TP.clan_relation(a, target) in (1, 2):
                    continue
                ratio = target.value()['power'] / max(0.5, a.value()['power'])
                if not hunt and ratio > 0.9 + 0.6 * a.o('risk'):
                    continue                     # does not attack a stronger one when not hunting
                if ratio > 1.6 + a.o('risk') + a.mood['anger']:
                    continue                     # does not attack a much stronger one even when hunting
                result = S.encounter(a, target, self, now)
                if result and result[0] == 'won' and result[1].k.get('quest'):
                    QU.advance(result[1], QU.KILL_PLAYERS, game_map=result[1].game_map, y=self)

    # ------------------------------------------------------------ fast-forward
    def fast(self, b, seconds, now, step=900.0, pvp=False):
        """Advances the bot as if it had played for the given seconds (jumpstart, catch-up): big steps, decisions per step."""
        t = now - seconds
        b.online = True
        b.target = None
        while t < now:
            dt = min(step, now - t)
            t += dt
            self.now = t
            b.dead_until = 0
            b.en_route = None
            B.decision(b, self, t)
            if b.target is not None:
                if b.en_route:
                    while b.en_route:
                        S.jump_to(b, b.en_route.pop(0), None)
                b.target.abstract(b, dt, self)
            if self.permission('shop'):
                for _ in range(8):           # spends the money accumulated in a big step (separate decisions in real time)
                    c = SHOP.candidate(b)[0]
                    if c is None or not b.pay(c[1], c[2]):
                        break
                    b.add(c[3])
            b.mood.d['fatigue'] = 0.0
        b.online = False
        b.target = None
        b.dead_until = 0
        self.now = now

    def jumpstart(self, bots, now):
        """The new cast starts with a realistic distribution: each bot gets a lognormal "hours played" (many beginners, many average, few strong),
        multiplied by company strength; the bot is fast-forwarded as if it had played that long (its equipment, level and money are consistent with each other)."""
        import math
        avg = max(1.0, float(self.setting('jumpstart_hours', 60)))
        fg = self.setting('company_power', [1, 1, 1])
        t0 = time.time()
        for b in bots:
            hour = b.r.lognormvariate(math.log(avg) - 0.5, 1.0) * float(fg[b.firma - 1]) * (0.6 + 0.8 * b.o('ambition'))
            hour = min(hour, avg * 8)
            self.fast(b, hour * 3600, now, step=max(1800.0, hour * 3600 / 60))
        self.log('   botlar: jumpstart %d bot, %.1f sn' % (len(bots), time.time() - t0))

    def catch_up(self, seconds, now):
        """Part of the time elapsed while the player was away: bots progress in proportion to their tendency to be online."""
        t0 = time.time()
        for b in self.bots:
            if not b.saved:
                continue
            pay = sum(PS.HABITS[b.k['personality']['habit']][1]) / 24.0 * self.setting('online_ratio', 0.6)
            s = seconds * pay * b.r.uniform(0.5, 1.5)
            if s > 300:
                self.fast(b, s, now, step=900.0)
        self.log('   bots: offline catch-up %.0f min, %.1f s' % (seconds / 60, time.time() - t0))


def server(route, log=print):
    """When the game server opens (game.main, OO_BOT): reads the pack, sets up the manager in the background (jumpstart and offline catch-up
    can take seconds; the game does not wait) and runs it. The pack's state is in <id>/state.json next to the pack file."""
    global ACTIVE
    try:
        with open(route, encoding='utf8') as f:
            package = json.load(f)
    except (OSError, ValueError) as e:
        log('   bots: could not read pack (%s): %s' % (route, e))
        return

    def rate():
        global ACTIVE
        uid = os.path.splitext(os.path.basename(route))[0]
        state = os.path.join(os.path.dirname(route), uid, 'state.json')
        t0 = time.time()
        y = Manager(package, state, log)
        import clan as KL
        import community as TP
        from . import society
        if not KL.FILE:                                  # bot clans are permanent (a shared clan file already exists on the friend server)
            KL.configure(os.path.join(os.path.dirname(state), 'clans.json'))
        society.register(y, getattr(TP.GAME, 'CHAT', None))
        y.society = True
        if y.mode == 'advanced':
            from . import llm, llm_provider, llm_server
            if llm_provider.multilingual() or llm_server.setup() is not None:   # the user's provider or the installed built-in model
                y.llm = llm.Brain(y, log)                  # the model starts in the background; patterns until it is ready
                y.llm.launch()
            else:
                log('   bots: Advanced mode but no language model installed (Bots > Advanced mode): continuing like Normal mode')
        ACTIVE = y
        y.launch()
        log('botlar: "%s" (%s, %d bot) %.1f sn' % (package.get('name', uid), package.get('mode', 'normal'), len(y.bots), time.time() - t0))

    threading.Thread(target=rate, name='bots-setup', daemon=True).start()


def close():
    """The server is shutting down (game.stop_gracefully): the state is saved."""
    if ACTIVE is not None:
        ACTIVE.stop()
        if ACTIVE.llm is not None:
            ACTIVE.llm.stop()
