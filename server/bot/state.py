"""Bot: a pilot's persistent record (package state, a dictionary in state.json) and the temporary fields needed while running.

Persistent record (k):
  no, name, company, personality    from the roster (unchanged)
  uid                               its id on the server (BOT_UID_BASE + no)
  level, ep, credits, uridium, honor  progress
  gear                              equipment in catalog format (everything owned; outfit places it)
  map, x, y                         last position
  mood, memory                      mood and relationships toward people (personality.Mood, personality.Memory)
  clan, friends                     clan id or None; friend names (a copy of the contact list)
  stats                             npc, player, death, quest, sure_sn, spend_*
  quest                             current quest {id, conditions: {condition: count}} or None; done: quests it finished
  target, intent                    its last goal (brain) and the LLM's inclination {target, pay, end_time, plan}
"""
import random, time

import player_profile as PF
from . import catalog as K
from . import personality as PS
from . import game_settings as GS
from . import society as T

BOT_UID_BASE = 1800000000


class Bot:
    def __init__(self, k):
        self.k = k
        k.setdefault('uid', BOT_UID_BASE + int(k['no']))
        k.setdefault('level', 1)
        for a in ('ep', 'credits', 'uridium', 'honor'):
            k.setdefault(a, 0)
        k.setdefault('gear', K.new_gear())
        k.setdefault('map', K.ev(k['company']))
        k.setdefault('x', 0)
        k.setdefault('y', 0)
        k.setdefault('mood', {})
        k.setdefault('memory', {})
        k.setdefault('clan', None)
        k.setdefault('friends', [])
        k.setdefault('stats', {})
        if 'npc_points' not in k['stats']:       # old record: kills have no type; per alien the average of ordinary aliens (3.7),
            k['stats']['npc_points'] = round(k['stats'].get('npc', 0) * 3.7)       # per player ship the score of its own ship
            k['stats']['player_points'] = k['stats'].get('player', 0) * T.ship_rank_points(k['gear']['ship'])
        k.setdefault('quest', None)
        k.setdefault('done', [])
        k.setdefault('cargo', {})
        k.setdefault('stock', {'ammunition_laser_lcb-10': 1000, 'ammunition_rocket_r-310': 20})     # a new player's ammo
        k.setdefault('target', None)
        k.setdefault('intent', None)
        if k.get('honor', 0) < 0 and not k.get('_honor_fix'):
            k['honor'] = 0              # old record: honor that went negative from the cargo box penalty is reset to zero once (ship.is_theft)
        k['_honor_fix'] = 1
        k['memory'].pop('', None)      # old record: an attacking bot ship was remembered without a name (ship._name)
        k['personality']['_name'] = k['name']                     # from time zone and taste name (personality comes back from the roster on every start)
        self.mood = PS.Mood(k['mood'], k.get('mood_time'))
        self.memory = PS.Memory(k['memory'])
        self.r = random.Random('%s|%s|%s' % (k['name'], k['no'], k['stats'].get('sure_sn', 0)))     # deterministic (simulation)
        # temporary
        self.online = False
        self.session_end = 0.0
        self.next_login = 0.0         # the next "should I log in" moment while offline
        self.next_decision = 0.0
        self.target = None                # brain.Goal instance
        self.goal_start = 0.0
        self.plan = {}                   # the goal's own state (the map being gone to, the target alien ...)
        self.en_route = None                # [maps ...]: on the portal route (abstract_sim jump)
        self.en_route_time = 0.0               # the moment of the next jump
        self.dead_until = 0.0             # died: has not respawned until this moment (returning to base)
        self.body = None                # concrete ship (ship.BotShip) or None
        self.last_abstract = time.time()
        self._value = None               # value() cache (reset when the equipment changes)
        self._candidates = None             # shopping.candidates() cache
        self.events = []                # incoming events (chat, invite, attack ...): read by the brain and the LLM
        self.pending = []               # invites awaiting a reply [(type, id, name, time)] (society.invites)
        self.session = None               # society.BotSession while online
        self.profile = None               # Profile for the community (society.py)
        self.permission = {}                   # the package's access settings (manager binds)
        self.hour = time.time            # the events' clock (manager binds the simulation's clock)
        self.game_settings = GS.STANDARD             # the package's game-settings profile (manager binds; separate from the player's settings)

    # ------------------------------------------------------------ shortcuts
    @property
    def name(self):
        return self.k['name']

    @property
    def uid(self):
        return self.k['uid']

    @property
    def saved(self):
        """Has it registered on the server (in progressive mode pilots join one by one; old records have no field: registered)."""
        return self.k.get('registered', True)

    @property
    def firma(self):
        return self.k['company']

    @property
    def level(self):
        return self.k['level']

    @property
    def game_map(self):
        return self.k['map']

    @property
    def traits(self):
        return self.k['personality']['traits']

    @property
    def archetype(self):
        return self.k['personality']['archetype']

    def o(self, name):
        return self.k['personality']['traits'][name]

    def ist(self, name, n=1):
        self.k['stats'][name] = self.k['stats'].get(name, 0) + n

    def shield_share(self):
        """The share of the generator slots given to the shield: cautious shield, hunter likes speed; a clan order (clan_orders: full shield, full speed,
        balanced) comes first."""
        if self.k.get('structure'):
            from .clan_orders import LAYOUT_SHARE
            return LAYOUT_SHARE.get(self.k['structure'], 0.6)
        return PS.clamp(0.85 - 0.45 * self.o('risk') * self.o('aggression') - 0.15 * (self.archetype == 'hunter'), 0.3, 0.95)

    def clan_savings(self):
        """A leader-personality bot that will found a clan (clanless, level 4+) sets aside the founding cost: shopping and the auction do not touch this
        credit. Previously not a single bot could found a clan even in 8 hours (the money always went to something else)."""
        if (self.archetype != 'leader' or self.k.get('clan') is not None or self.level < 4 or not self.permission.get('clan', True)
                or not self.permission.get('clan_found', True)):
            return 0
        import clan as KL
        return KL.FOUNDING_COST * 1.3

    def value(self):
        """Combat values; active boosters (damage, HP, shield) are added on top (they drop on their own when they expire)."""
        d = self._base_value()
        from . import loot as LT
        dmg, hp, shd = LT.booster_share(self, 'DAMAGE'), LT.booster_share(self, 'HITPOINTS'), LT.booster_share(self, 'SHIELD')
        if dmg or hp or shd:
            d = dict(d, dps=d['dps'] * (1 + dmg), can=d['can'] * (1 + hp), kalkan=d['kalkan'] * (1 + shd),
                     ehp=d['ehp'] * (1 + 0.5 * hp + 0.5 * shd))
        return d

    def _base_value(self):
        """Combat values; dps and ehp against aliens: with the profile's alien HP and damage multiplier (on a hard profile the same ship
        kills more slowly and takes more damage). power is the equipment itself (comparison, panel)."""
        if self._value is None:
            d = K.values(self.k['gear'], self.shield_share())
            d['dps'] /= max(0.1, self.game_settings.multiplier('npc_can', 'map'))
            d['ehp'] /= max(0.1, self.game_settings.multiplier('npc_damage', 'map'))
            self._value = d
        return self._value

    def loadout_changed(self):
        self._value = self._candidates = None
        if self.body is not None:
            self.body.refresh()

    # ------------------------------------------------------------ progress
    def earn(self, ep=0, credits=0, uridium=0, honor=0):
        """Gain (or loss); level from the EP table (player_profile.level_for). -> did it reach a new level."""
        k = self.k
        # fractions accumulate: the abstract simulation's 5 s steps give uridium in pieces like 0.4, which never accumulated when truncated
        fractions = self.__dict__.setdefault('_fraction', {})
        full = {}
        for a, v in (('ep', ep), ('credits', credits), ('uridium', uridium), ('honor', honor)):
            v = v + fractions.get(a, 0.0)
            full[a] = int(v)
            fractions[a] = v - full[a]
        k['ep'] += full['ep']
        if full['credits'] > 0 and full['ep'] > 0 and k.get('clan'):
            self._clan_income = self.__dict__.get('_clan_income', 0) + full['credits']   # alien/quest gain: clan tax (society)
        k['credits'] = max(0, k['credits'] + full['credits'])
        k['uridium'] = max(0, k['uridium'] + full['uridium'])
        k['honor'] += full['honor']
        lv = PF.level_for(k['ep'])
        if lv != k['level']:
            leveled_up = lv > k['level']
            k['level'] = lv
            if leveled_up:
                self.mood.it(morale=0.2, confidence=0.05)
                self.event('level', level=lv)
            return leveled_up
        return False

    def reward(self, source, speed=1.0, **earnings):
        """The game's reward (source: npc, quest, box or None): multiplied by the package's speed, the game-settings profile and the EP/honor boosters."""
        from . import loot as LT
        bst = {'ep': 1 + LT.booster_share(self, 'EXPERIENCE_POINTS'), 'honor': 1 + LT.booster_share(self, 'HONOUR_POINTS')}
        return self.earn(**{k: v * speed * self.game_settings.multiplier(k, source) * bst.get(k, 1.0) for k, v in earnings.items()})

    def pay(self, currency, amount):
        """Pay with 'C' | 'U' -> was it paid."""
        a = 'credits' if currency == 'C' else 'uridium'
        if self.k[a] < amount:
            return False
        self.k[a] -= int(amount)
        self.ist('spend_' + a, int(amount))
        return True

    def add(self, loot, n=1):
        """A purchased or earned item goes to the equipment (ship: becomes the active ship)."""
        e = self.k['gear']
        if loot.startswith('ship_'):
            if not (K.ITEMS['ships'].get(loot) or {}).get('hp'):
                return False                             # a design that is only a look: not a ship
            e['ship'] = loot
        elif loot in K.ITEMS['lasers']:
            e['laser'][loot] = e['laser'].get(loot, 0) + n
        elif loot in K.ITEMS['shield_generators']:
            e['kalkan'][loot] = e['kalkan'].get(loot, 0) + n
        elif loot in K.ITEMS['speed_generators']:
            e['speed'][loot] = e['speed'].get(loot, 0) + n
        elif loot in K.ITEMS['drones']:
            e['drone'][loot] = e['drone'].get(loot, 0) + n
        elif loot in K.ITEMS['combat_items']['launcher']['kinds']:
            e['launcher'] = loot                       # rocket launcher (technology.py)
        elif loot in K.ITEMS['extras'] or loot in K.ITEMS['repair_robots']:
            from . import extras as EX
            EX.equip(self, loot)                          # CPU and repair robot to the extra slot (extras.py)
            return True
        elif loot in K.ITEMS['laser_ammo'] or loot in K.ITEMS['rockets'] or loot in K.ITEMS['combat_items']['launcher_ammo'] \
                or loot.startswith('tech_') or loot.startswith('ammunition_'):
            from . import weapons as WP
            WP.add(self, loot, n)                      # ammo and rockets to stock (weapons.py)
            return True
        else:
            return False
        self.loadout_changed()
        return True

    # ------------------------------------------------------------ cargo
    def cargo_fill(self):
        """Cargo fullness (0..1): ores that take space / the ship's cargo area."""
        k = self.k.get('cargo') or {}
        return sum(v for t, v in k.items() if int(t) in K.CARGO_ORE) / max(1, K.cargo_capacity(self.k['gear']))

    def add_cargo(self, contents):
        """Takes ores into the cargo as far as they fit -> what was taken {type: count}."""
        cargo = self.k.setdefault('cargo', {})
        empty = K.cargo_capacity(self.k['gear']) - sum(v for t, v in cargo.items() if int(t) in K.CARGO_ORE)
        claimed = {}
        for t, v in sorted(contents.items(), key=lambda x: -K.ore_prices(0).get(int(x[0]), 0)):   # valuables first
            n = int(v) if int(t) not in K.CARGO_ORE else max(0, min(int(v), empty))
            if n > 0:
                cargo[str(t)] = cargo.get(str(t), 0) + n
                claimed[int(t)] = n
                if int(t) in K.CARGO_ORE:
                    empty -= n
        return claimed

    def sell_cargo(self):
        """At the station sells the cargo's sellable ores (honor-dependent price, the profile's ore price multiplier) -> credits earned.
        Laboratory first: a bot that likes upgrades refines and loads them into its laser, shield, rocket (lab.py); the rest is sold."""
        from . import lab as LB, weapons as WP, skylab as SK
        SK.carry(self, self.hour(), K.cargo_capacity(self.k['gear']) * 3)      # ore from Skylab (up to the transport allowance)
        LB.decision(self, WP.hourly_ammo(self))
        price = K.ore_prices(self.k['honor'], self.game_settings.multiplier('ore_price'))
        cargo = self.k.setdefault('cargo', {})
        kredi = 0
        for t in list(cargo):
            if int(t) in price:
                kredi += price[int(t)] * cargo.pop(t)
            elif int(t) in K.CARGO_ORE:              # what the refinery does not sell (Palladium: to the trader in 5-2 for gate energy) to storage
                from . import weapons as WP
                name = K.ITEMS['ores']['kinds'].get(str(t), 'resource_ore_%s' % t)
                WP.stock(self)[name] = WP.stock(self).get(name, 0) + cargo.pop(t)
        if kredi:
            self.earn(credits=kredi)
            self.ist('ore_credits', kredi)
            self.event('sold_ore', credits=kredi)
        return kredi

    def event(self, kind, now=None, **f):
        """Event queue (at most 30): for the brain and the LLM context."""
        self.events.append(dict(type=kind, t=now or self.hour(), **f))
        del self.events[:-30]

    def save(self):
        self.k['mood'] = self.mood.save()
        self.k['mood_time'] = self.mood.t
        return self.k

    def summary(self):
        """A short status for the panel and the LLM."""
        d = self.value()
        return dict(no=self.k['no'], name=self.name, company=self.firma, archetype=self.archetype, level=self.level, ep=self.k['ep'],
                    credits=self.k['credits'], uridium=self.k['uridium'], honor=self.k['honor'], ship=self.k['gear']['ship'],
                    power=round(d['power'], 1), map=K.H.name(self.game_map), online=self.online, clan=self.k['clan'],
                    target=self.k['target'], concrete=self.body is not None, stats=dict(self.k['stats']), registered=self.saved,
                    cargo=round(self.cargo_fill(), 2))
