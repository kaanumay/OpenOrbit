"""Game settings (admin panel, panel/): multipliers, event selection, auction rivals, server options.

The single definition of the settings is SCHEMA: the panel UI is built from it, the server reads values with get(). Values are in save/settings.json
({key: value, 'events': {event: 'on' | 'off'}}); a key missing from the file is the default, unknown ones are ignored,
numbers are clamped to the limits, a corrupt file falls back to the defaults.
Limits (2026-10-19, user request: "I can't set the uridium multiplier above 50"): 'min'..'max' is the recommended range of the panel's slider;
any value up to `limit` can be typed by hand into the number box (UPPER_LIMIT if missing). `limit` is for safety only: overflow of values that
go to the client in a 32-bit field (HP, shield, damage), the server's load (number of aliens and boxes) or a logical upper bound (number of gates).
When the file changes (saved from the panel) it is re-read within REFRESH_SEC at the latest, and takes effect while the game is open too. Each setting's
'apply_mode' says when it takes effect:
  instant   at the next event (damage, reward, box contents ...)
  map       when the map is rebuilt (map change, respawn after death): number of NPCs and boxes
  login     when re-entering the game (events are announced to the client at login; popup windows)
  restart   when the server restarts
Sub-settings (2026-10-24, user request: adjust uridium separately for boxes, aliens, gates): the multipliers in SUBS have sub-multipliers by
source (key <parent>_<source>: uridium_npc, shop_price_credits ...; in the schema they follow their parent right after it with the 'parent' and 'source'
fields). The effective multiplier is parent x sub: multiplier('uridium', 'npc'); if the source has no sub-setting, only the parent. Range,
limit and apply mode come from the parent, default x1; presets change only the parents. The panel shows the sub-settings in the
"By source" section that opens under the parent.
The game server binds the file with configure() (game.main, the --settings=<path> option or save/settings.json). While unbound
(tests, tools) all settings are defaults: the user's settings do not affect the tests.
"""
import json, os, random, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, 'save', 'settings.json')
REFRESH_SEC = 1.0

GROUPS = (('ship', 'Your ship'), ('combat', 'Combat and aliens'), ('reward', 'Rewards'), ('progress', 'Progression'), ('world', 'World'),
           ('gate', 'Gates and modes'), ('economy', 'Economy'), ('duration', 'Timers'), ('auction', 'Auction'), ('ui', 'Interface'),
           ('manager', 'Admin'), ('developer', 'Developer'))
RIVAL_LEVELS = ('Off', 'Timid', 'Moderate', 'Competitive', 'Aggressive')
UPPER_LIMIT = 10000.0             # the largest value multipliers can be typed by hand ('limit' if not given)
I32 = 2 ** 31 - 1               # the upper bound of values that go to the client in a 32-bit field (the protocol would overflow: HP, shield, price)


def _c(key, name, group, description, apply_mode='instant', lo=0.0, hi=10.0, step=0.1, default=1.0, limit=UPPER_LIMIT, condition=None):
    """Multiplier: a slider (lo..hi, recommended) and a number box (lo..limit) in the panel. condition: visible only while that on/off setting is on."""
    return dict(key=key, name=name, group=group, type='multiplier', default=default, min=lo, max=hi, cap=max(hi, limit), step=step,
                description=description, apply_mode=apply_mode, **({'condition': condition} if condition else {}))


def _b(key, name, group, description, apply_mode='instant', default=False):
    return dict(key=key, name=name, group=group, type='bool', default=default, description=description, apply_mode=apply_mode)


def _n(key, name, group, description, apply_mode='instant', lo=0, hi=10, default=1, unit='', limit=None):
    """Integer (count, hours): a number box in the panel; hi is the recommended upper bound, limit the largest that can be typed by hand (hi if missing)."""
    return dict(key=key, name=name, group=group, type='number', default=default, min=lo, max=hi, cap=max(hi, limit or hi),
                unit=unit, description=description, apply_mode=apply_mode)


SCHEMA = [
    # ---------------------------------------------------------------- ship
    _c('ship_hp', 'Ship HP', 'ship', "Your ship's maximum HP (hull), together with formation, booster and lab bonuses. Also changes while "
                                     'the game is running.', lo=0.1, limit=1000.0),
    _c('ship_shield', 'Ship shield', 'ship', "Your ship's maximum shield (shield generators on the ship and drones, with bonuses). Also changes "
                                             'while the game is running.', limit=500.0),
    _c('ship_speed', 'Ship speed', 'ship', "Your ship's flight speed (with speed generators and bonuses). Effects like slowdowns and Fortify "
                                           'still apply.', lo=0.25, hi=3.0, limit=10.0),
    _c('shield_regen', 'Shield regeneration', 'ship', 'How fast the shield refills by itself out of combat (game value 4% per second). 0: the shield never '
                                                      'refills by itself.', limit=100.0),
    _c('repair_speed', 'Repair bot speed', 'ship', 'How fast the repair bot (REP) repairs the hull.', lo=0.1, limit=1000.0),
    _c('player_hit_chance', 'Your hit chance', 'ship', "Hit chance of your lasers, rockets and P.E.T. (game value 80%, at most 100%). x1.25: every shot "
                                                       "hits.", lo=0.1, hi=2.0, limit=100.0),
    _c('rocket_cooldown', 'Rocket cooldown', 'ship', 'Cooldown and reload time of rockets and the rocket launcher. Lower value: more frequent shots.', lo=0.05, hi=5.0, limit=100.0),
    _b('immune_until', 'Invulnerable ship', 'ship', 'Alien shots are shown, but your ship loses no hit points or shield.'),
    _b('infinite_ammo', 'Infinite ammo', 'ship', 'Laser ammo, rockets, launcher ammo and mines are not used up (you need at least one).'),
    _b('infinite_technology', 'Infinite tech', 'ship', 'Tech items (Energy Leech, Battle Repair Bot, Speed Burst …) are not used up when activated (you '
                                                       'need at least one). Cooldowns still apply.'),
    _b('own_mine', 'Your own mines hurt you', 'ship', 'The blast of a mine you placed also damages your ship (as in the game). When off, only aliens are '
                                                      'hit.', default=True),
    _n('on_spot_hp', 'HP on on-the-spot repair', 'ship', 'HP you get when you repair on the spot after your ship is destroyed (game value 10%; the shield '
                                                         'starts empty).', lo=1, hi=100, default=10, unit='%'),
    _n('on_spot_protection', 'Protection after on-the-spot repair', 'ship', 'How long you take no damage after repairing on the spot (game value 10 s). Ends when you fire.', lo=0, hi=60, default=10, unit='s', limit=3600),
    # ---------------------------------------------------------------- combat and aliens
    _c('npc_damage', 'Damage from aliens', 'combat', 'Damage aliens (NPCs) deal to your ship, your P.E.T. and friendly ships. 0: you take no damage at '
                                                    'all.', limit=1000.0),
    _c('player_damage', 'Damage you deal', 'combat', 'Damage you deal to aliens, players and bots with lasers, rockets, launchers, mines, Smart Bomb, '
                                                    'cannons, the P.E.T. and abilities.', lo=0.1, limit=1000.0),
    _c('npc_hp', 'Alien hit points and shields', 'combat', 'Alien hit points and shields. A lower value kills aliens faster.', apply_mode='map', lo=0.1, limit=100.0),
    _c('npc_hit_chance', 'Alien hit chance', 'combat', 'Chance that aliens hit your ship and P.E.T. (game value 60%, at most 100%). 0: they never hit.', hi=2.0, limit=100.0),
    _c('npc_speed', 'Alien speed', 'combat', 'Flight speed of aliens (stationary ones stay put).', lo=0.1, hi=3.0, limit=10.0),
    dict(key='npc_aggression', name='Alien aggression', group='combat', type='level', default=0,
         options=['By type', 'All aggressive', 'None aggressive'], colors=['', 'err', 'ok'], apply_mode='instant',
         option_description=['As in the game: aggressive types attack when they see you, the others fight back when shot.',
                           'Every alien chases and attacks you once it notices you.',
                           'No alien attacks on its own; an alien you shoot still fights back.'],
         description='Whether aliens chase you on their own (including those in gate and mode waves).'),
    _c('npc_notice', 'Alien detection range', 'combat', 'Distance at which aggressive aliens notice you and start chasing (game value 1,000 units).', lo=0.1, hi=3.0, limit=20.0),
    _c('npc_range', 'Alien firing range', 'combat', 'Distance from which aliens can fire lasers, rockets and bombs at you (game value 450 for most, 550 '
                                                   'for Kristallons, 1,000 for stationary ones; world boss attacks included).', lo=0.1, hi=3.0, limit=20.0),
    _b('slowing_shots', 'Slowing alien shots', 'combat', 'Shots from aliens such as Barb, The Stinger, Saboteur and Mindfire Behemoth slow your ship down. '
                                                        'When off, they only deal damage.', default=True),
    _b('company_pvp', 'Attacking your own company', 'combat', "You can attack players and bots from your own company (as in the game): forbidden on your company's "
                                                             'X-1 and X-2 maps, destroying them brings a penalty. When off, you cannot attack your own company '
                                                             '(except clans at war).', default=True),
    _c('radiation', 'Radiation damage', 'combat', 'Hull damage from radiation outside the map border. 0: radiation does no harm.', lo=0.0, hi=5.0, limit=100.0),
    _c('cbs_hp', 'Clan Battle Station HP', 'combat', "Health and shield of every Clan Battle Station module (yours, bot clans' and rival clans'). When "
                                                     "changed, the modules' current health scales proportionally; in-game bars refresh when you re-enter "
                                                     'the map or a module is hit.', apply_mode='map', lo=0.1, hi=10.0, limit=1000.0),
    _c('cbs_damage', 'Clan Battle Station damage', 'combat', 'Damage dealt by the weapon modules of every Clan Battle Station (to aliens, and by a rival station '
                                                            'to you).', lo=0.0, hi=10.0, limit=1000.0),
    # ---------------------------------------------------------------- rewards
    _c('credits', 'Credit gain', 'reward', 'Credits earned from aliens, boxes, missions, gates and events (sales and refunds excluded).', hi=50.0, limit=100000.0),
    _c('uridium', 'Uridium gain', 'reward', 'Uridium earned from aliens, boxes, missions, gates and events.', hi=50.0,
       limit=100000.0),
    _c('ep', 'Experience (EP) gain', 'reward', 'Experience points earned: how fast you level up.', hi=50.0, limit=100000.0),
    _c('honor', 'Honor gain', 'reward', 'Honor points earned.', hi=50.0, limit=100000.0),
    _c('collecting', 'Collected item amount', 'reward', 'Ammo and items in boxes, ore in alien cargo boxes and from mining, extra alien rewards (Palladium, '
                                                        'event currency …). Credits and uridium from boxes use their own multipliers.', hi=50.0),
    _c('mode_reward', 'Quest, gate and event item rewards', 'reward', 'Amount of ammo, resources, keys and tech items given by quests, Galaxy Gates, event gates, modes '
                                                                      '(Astral, EBL, Mimesis, Galaxy Trek …), Urgent Missions and Dispatch. Single items such as ships, '
                                                                      'lasers and designs stay at one; money and EP use their own multipliers.', hi=50.0),
    _c('drop', 'Item drop chance', 'reward', 'Chance that aliens drop boosters, equipment, resources and event boxes; Galaxy Gate lucky rewards '
                                             '(at most 100%).', hi=20.0, limit=1000.0),
    _b('x1_cargo', "Reduced X-1 cargo and rewards at high level", 'reward', "On X-1 maps the aliens' cargo boxes shrink as your level rises (level 7: 50%, 10 and up: none), and "
                                                                            "on your own X-1 map kill rewards drop too (level 15 and up: none; as in the game). When off, full "
                                                                            "cargo and rewards at every level.", default=True),
    _b('tag', 'Alien tagging', 'reward', 'The first to fire at an alien tags it: its reward, quest count and cargo box belong to them (or '
                                            'their group), even if someone else finishes it. The tag drops if its owner does not hit for 15 '
                                            'seconds. If off, the reward goes to whoever lands the last hit.',
       default=True),
    _b('player_tag', "Player takes the bot's tag", 'reward', "If you shoot an alien that a bot has tagged, the tag passes to you: reward, quest count and cargo "
                                                             "box become yours (bots in your group still share). Not for aliens fought together such as Cubikon, "
                                                             "Mindfire Behemoth and world bosses: there the reward is split between players and bots by damage "
                                                             "dealt, and the cargo box goes to the top damage dealer. Has no effect while alien tagging is off.", default=False),
    _b('cargo_ownership', 'Cargo box ownership', 'reward', "An alien's cargo box belongs to its owner only; others see it in blue (if the game's Settings > "
                                                           "Display option for other players' cargo boxes is on). Collecting the box of someone from your own "
                                                           "company costs honor: 10 for the first that day, twice as much each time. If off, anyone can collect "
                                                           "it with no penalty.", default=True),
    # ---------------------------------------------------------------- progress
    _c('drone_xp', 'Drone experience', 'progress', 'Points your drones earn when you kill aliens: how fast drones level up.',
       hi=50.0),
    _c('pet_ep', "P.E.T. experience", 'progress', "Experience your P.E.T. earns (game value 5% of the EP you earn): how fast the P.E.T. levels up.", hi=50.0),
    _c('season_points', 'Season Pass points', 'progress', 'Points earned from Season Pass missions: how fast you level up the season.',
       hi=50.0),
    _n('season_duration', 'Season Pass duration', 'progress', "Length of a season. The season starts from day 1 on the save's first login; when it ends, unclaimed "
                                                              'rewards are booked and the next season starts (about 3 months in the real game). A change also '
                                                              'applies to the running season.',
       lo=1, hi=180, default=90, unit='days', limit=3650),
    _n('battle_pass_duration', 'Battle Pass duration', 'progress', "Length of the Battle Pass. When an event with a pass opens, the save's pass starts from day 1 and "
                                                                   "runs together with the event for this long (even if its calendar period ends sooner); one pass at a "
                                                                   "time (about 2 weeks in the real game).", lo=1, hi=60, default=14, unit='days', limit=365),
    _c('booster_power', 'Booster strength', 'progress', 'The bonus of boosters (damage, HP, shield, EP, honor …) and the cap of each type. x2: a 10% damage '
                                                        'booster gives 20%.', hi=10.0, limit=100.0),
    # ---------------------------------------------------------------- world
    _c('box_abundance', 'Bonus box abundance', 'world', 'Number of bonus boxes on the maps (event boxes included).',
       apply_mode='map', hi=10.0, limit=100.0),
    _c('box_respawn', 'Box respawn time', 'world', 'Time until a collected box is replaced. Lower value: sooner.', lo=0.01, hi=5.0, limit=100.0),
    _c('npc_count', 'Alien count', 'world', 'Number of aliens on the maps (bosses included; gate and mode waves excluded).',
       apply_mode='map', hi=5.0, limit=50.0),
    _c('npc_respawn', 'Alien respawn time', 'world', 'Time until a dead alien is replaced. Lower value: sooner.', lo=0.01, hi=5.0, limit=100.0),
    _c('ore_abundance', 'Ore abundance', 'world', 'Number of collectable ores (Prometium, Endurium, Terbium …) on the maps.',
       apply_mode='map', hi=10.0, limit=50.0),
    _c('ore_respawn', 'Ore respawn time', 'world', 'Time until a collected ore is replaced. Lower value: faster.', lo=0.01, hi=5.0, limit=100.0),
    _n('max_quests', 'Quests at the same time', 'world', 'How many quests you can run at the same time in the quest window (game value 5). When all slots are '
                                                         'taken, no new quest can be accepted until one is completed or cancelled. Lowering it does not '
                                                         'cancel running quests.', lo=1, hi=10, default=5, unit='quests', limit=100),
    _b('campaign', 'Starter campaign', 'world', 'The "Level N" starter quests are always shown in the quest window. When off, they show only for the '
                                                'first month and only if chosen when the save was created; a running quest can always be finished.'),
    _b('jump_deviation', "Jump CPU occasionally misjumps", 'world', "With a small chance (2%) the jump CPU takes you to the Cubikon Graveyard (as in the game). When "
                                                                    "off, it always goes to the map you picked.", default=True),
    _b('pack_limit', 'Unique packages once', 'world', "Shop packages containing a ship, ship design, formation, P.E.T. or unique drone (Defcom-Raven, "
                                                      "Stellar, Dusklight …) can be bought once, as in the game, and then leave the list. When off they "
                                                      "can be bought again (content you already own is skipped).", default=True),
    _b('portal_hangar', 'Hangar at portals', 'world', "You can also open the hangar and change equipment in the safe zone of portals (convenience; in the "
                                                      "real game only at the station). When off, only at the station.", default=True),
    _b('clan_cooldown', 'Clan 48-hour rules', 'world', 'After leaving a clan you cannot found or join another clan for 48 hours; the clan name/tag can only '
                                                       'be changed every 48 hours. When off there is no waiting time.', default=True),
    # ---------------------------------------------------------------- gates and modes
    _c('gate_part', 'Gate part chance', 'gate', "Chance of getting a gate part per energy in the Galaxy Gate generator (the game's value is 13%; the "
                                                "window's odds list changes too).", lo=0.1, hi=7.0, limit=1000.0),
    _n('duplicate_to_missing', 'Duplicate part becomes a missing one', 'gate', 'When you draw a gate part you already have, the chance that you get a missing part instead (game '
                                                                               'value 50%). 100%: no duplicate parts at all (until the gate is built).', lo=0, hi=100,
       default=50, unit='%'),
    _c('gate_energy', 'Gate energy amount', 'gate', 'Amount of free Galaxy Gate energy from bonus boxes (the Palladium trade at the 5-2 merchant and '
                                                    "packages don't change).", hi=20.0),
    _c('gate_price', 'Gate prices', 'gate', 'Uridium price of energy in the Galaxy Gate generator and of extra lives at a gate. 0: free.', hi=5.0, limit=300.0),
    _c('gate_lives', 'Lives in gates', 'gate', 'Lives given when a Galaxy Gate or an event gate (Plutus, Quarantine …) is prepared (game value 5 '
                                               'for most gates).', lo=0.2, hi=10.0, limit=1000.0),
    _b('infinite_lives', 'No lives lost in gates', 'gate', 'Being destroyed in a Galaxy Gate or an event gate costs no life: the gate is never lost.'),
    _c('wave_aliens', 'Aliens per wave', 'gate', 'Number of aliens in the waves of Galaxy Gates, event gates and modes (Astral, EBL, Voyagers, '
                                                 'Trinity, Echoes). Guarding bosses stay single.', lo=0.1, hi=5.0, limit=20.0),
    _c('wave_wait', 'Pause between waves', 'gate', 'Start, sub-wave and break times of gate and mode waves (Galaxy Gate: start 6 s, break 30 s). 0: no '
                                                   'waiting.', hi=5.0, limit=100.0),
    _b('no_entry_limit', 'No gate and mode entry limits', 'gate', 'Event gates have no daily, yearly or one-time entry limits and no cooldowns; the free entries of '
                                                                  'Voyagers and Trinity never run out.'),
    _n('gate_bonus_count', 'Galaxy Gates with a bonus', 'gate', 'Number of gates in the gate window that have a timed bonus reward at the same time. Gates and '
                                                                'rewards are picked at random at the start of each period; finish a gate before the period ends '
                                                                '(Dispatch gate missions included) to get the bonus once. 0: no bonus.', lo=0, hi=11, default=3, unit='gates'),
    _c('gate_bonus_multiplier', 'Gate bonus amount', 'gate', 'Size of the gate bonus (honor, uridium, ammo, log disks, keys); single items such as lasers and '
                                                             'designs stay at one.', lo=0.1, hi=20.0),
    _n('gate_bonus_hours', 'Gate bonus period', 'gate', 'How often the bonus gates change (aligned to midnight; 24: every day). Changing it renews the '
                                                        'selection right away.', lo=1, hi=168, default=24, unit='hours', limit=8760),
    # ---------------------------------------------------------------- economy
    _c('shop_price', 'Shop prices', 'economy', 'Price of everything sold in the shop for credits and uridium.', lo=0.0,
       hi=5.0, limit=1000.0),
    _b('event_looks_in_shop', 'Event designs in the shop', 'economy', "Ship, drone and P.E.T. designs from events (Galactic Strife's Arios and Neikos, Trial of Terrors' "
                                                                      "Dusklight, past seasons' designs …) are sold in the shop. If turned off they are hidden in the shop "
                                                                      "and can't be bought; they are earned only in their own events: Battle Pass key exchange, event and "
                                                                      "booty boxes, GG weekend gates, Season Pass. The shop's own designs are always sold.",
       default=True),
    _c('service_price', 'Service fees', 'economy', "P.E.T. slots, repair and fuel; Skylab upgrades, instant finish, fast transport and robots; ship "
                                                   "warp. 0: free.", hi=5.0, limit=1000.0),
    _c('repair_cost', 'Repair cost after death', 'economy', 'Uridium cost of repairing at the portal and on the spot.',
       lo=0.0, hi=5.0, limit=1000.0),
    _c('ore_price', 'Ore sell price', 'economy', 'Credits and uridium you get for ores sold at the refinery (also shown in the window).', hi=10.0, limit=10000.0),
    _c('cargo', 'Cargo capacity', 'economy', "The ship's cargo space (together with Logistics, the cargo CPU and the P.E.T. protocol).",
       lo=0.5, hi=10.0, limit=1000.0),
    _b('infinite_cargo', 'Infinite cargo', 'economy', 'Cargo never fills up: every box and ore can always be collected without a "cargo full" warning.'),
    _b('infinite_pet_range', 'Infinite P.E.T. locator range', 'economy', "The P.E.T.'s enemy and resource locator gears point to the nearest target on the map with no range "
                                                                         "limit."),
    _b('assembly_free', 'Free Assembly', 'economy', 'No materials are spent in the Assembly and Upgrade/Disassembly tabs; the client shows every '
                                                    'material as sufficient. Production and wait times and daily use limits stay the same.'),
    _b('legacy_upgrade', 'Old upgrade system', 'economy', "Item upgrades as in 2018, with uridium only: the Assembly's Upgrade tab no longer asks for ABR, "
                                                          "Indoctrine Oil, Diametrion or other materials. The price is the old Item Upgrading's 100% success "
                                                          "price (3,905 U. for level 2, +435 per level; 104,250 U. in total up to 16). Also changes while the "
                                                          "game is running."),
    _c('legacy_upgrade_price', 'Old upgrade prices', 'economy', 'Uridium price of upgrades in the old system (the Upgrade Hour discount still applies). 0: free.',
       lo=0.0, hi=5.0, limit=1000.0, condition='legacy_upgrade'),
    _c('pet_fuel', 'P.E.T. fuel use', 'economy', "The P.E.T.'s fuel use per minute. 0: it uses no fuel.", lo=0.0, hi=5.0,
       limit=100.0),
    _c('skylab_production', 'Skylab production', 'economy', 'Hourly output of Skylab collectors and refineries.', hi=20.0),
    _c('skylab_storage', 'Skylab storage capacity', 'economy', 'Capacity of the Skylab storage for each resource.', hi=20.0,
       limit=1000.0),
    # ---------------------------------------------------------------- timers
    _c('cooldown', 'Crafting and waiting times', 'duration', 'Assembly crafting, Skylab upgrades and transport, Dispatch missions, item upgrades. Lower value: '
                                                         'faster (applies to newly started ones).', lo=0.0, hi=5.0, limit=100.0),
    _c('skill_cooldown', 'Ability and item cooldowns', 'duration', "Cooldown of ship abilities, CPUs, mines, Smart Bomb, Insta-Shield, tech items and special rockets.", lo=0.05, hi=5.0, limit=100.0),
    _c('booster_duration', 'Booster duration', 'duration', 'How long boosters stay active (applies to newly activated ones).', lo=0.1,
       hi=10.0, limit=1000.0),
    _b('no_level_limit', 'No level restrictions', 'duration', "Portals and the jump CPU have no level requirement: you can enter every map."),
    _b('session_always_open', 'Session events always open', 'duration', 'Events that open at set hours (Vortex of Greed, Treacherous Domain, Mimesis Mutiny) stay open for '
                                                                    'the whole event: the portal is always open, and a session, battle or run starts when you enter. '
                                                                    "Event aliens (Curcubitor, Agatus, Lanatum, Chaos Protegit) also spawn outside the game's hourly "
                                                                    'windows.'),
    # ---------------------------------------------------------------- auction
    dict(key='auction_rivals', name='Virtual rivals', group='auction', type='level', default=0,
         options=list(RIVAL_LEVELS), colors=['', 'ok', 'ok', 'info', 'err'], apply_mode='instant',
         option_description=['No rivals: only you place bids.',
                           'They place small bids now and then; they never outbid you, so any lot you bid on is yours.',
                           'More frequent and slightly higher bids; they still never outbid you.',
                           'When you outbid them they answer after a while. Go past their budget and the lot is yours; if you lose, your credits come back.',
                           'They answer very often, quickly and with big budgets. Bid well to keep the lot.'],
         description='Virtual bidders who compete with you at the auction. Timid and Moderate: they bid a little but '
                  'never outbid you, so any lot you bid on is yours. Competitive and Aggressive: they answer when you '
                  'outbid them; unless you go past their budget you may lose the lot (your credits come back). Off '
                  'while a bot pack is running in the world: the bots bid instead.'),
    # ---------------------------------------------------------------- interface
    _b('dark', 'Dark maps (flashlight)', 'ui', 'On the Trial of Terrors gate maps the screen goes dark and only the direction your ship faces is '
                                               "lit (the client's flashlight effect). Turn it off for bright maps.", apply_mode='map',
       default=True),
    _b('cinematic', 'Cinematic boss entrances', 'ui', "When an event boss spawns and in a Galaxy Gate's last wave, the camera turns to the boss for a few "
                                                      'seconds (controls are locked meanwhile), then returns to your ship.', default=True),
    _b('hints', 'Beginner tips', 'ui', "Tip windows when something happens for the first time (cargo full, out of ammo, another company's "
                                       'map) and as you level up, plus a description of the running event. Each shows once; tips you closed '
                                       'stay closed and can be reread in the tip archive.', default=True),
    _b('kill_streak', 'Kill streak announcements', 'ui', 'Destroy aliens in quick succession to get the "Triple Kill", "Unstoppable", "Godlike", "Like a '
                                                         'Boss" announcement and sound (3, 6, 10, 15 kills; at most 10 s apart).'),
    _b('no_ads', 'Hide login pop-ups', 'ui', 'The daily bonus, tip and Season Pass windows that open at login are not sent (you can still open '
                                             'them from the menus).', apply_mode='login'),
    # ---------------------------------------------------------------- admin (admin_mode.py)
    _b('admin_mode', 'Admin mode', 'manager', 'You become an administrator in the game: an admin badge (yellow A) before your name, and you are '
                                              'left out of the rank system, the Hall of Fame rankings and the company ranking. Bots know you as an '
                                              'admin: they never attack you, follow your warnings in chat and react when they see you. On a friend '
                                              'server only for the host player.', apply_mode='login'),
    dict(key='admin_ship', name='Admin ship', group='manager', type='level', default=0,
         options=['Your own ship', 'UFO', 'Police', 'G-Admincloak', 'Goliath Admin'], colors=['', 'info', 'info', 'info', 'info'],
         apply_mode='login',
         option_description=['In admin mode you still show your own ship.',
                           "Admin ship (ship_admin): the same model as the game's UFO alien.",
                           'Police ship (ship_police).',
                           "The admin's cloaking ship (ship_g-admincloak).",
                           "The Goliath's admin design (admincloak)."],
         description="In admin mode your ship looks like this; its stats (hit points, speed, equipment) are your own ship's."),
    _b('admin_spectator', 'Spectator (invulnerable)', 'manager', 'In admin mode aliens and bots do not attack you and you take no damage; you can roam the maps '
                                                                 'freely and watch the bots.', apply_mode='instant'),
    _b('admin_chat', 'Admin in chat', 'manager', "In admin mode your chat messages show as an admin's (in the game's admin colour).", apply_mode='login', default=True),
    _b('gm_console', 'GM console', 'manager', "The game's hidden admin window: in game press Ctrl, then Shift, then Z. Teleport to maps, spawn "
                                              'aliens and boxes, give items and packages, finish quests, set up gates, reset cooldowns, '
                                              'invulnerability. While on, an admin badge shows before your name (the client recognises the admin '
                                              'by rank 6000).', apply_mode='login'),
    # ---------------------------------------------------------------- developer
    _b('nearby_npc', 'Spawn aliens nearby', 'developer', 'Testing aid: one of each of the first four alien types spawns right next to your ship.', apply_mode='map'),
    _b('control', 'Live test control channel', 'developer', 'Developer tool (control.py, 127.0.0.1:8099): message trace and request injection.', apply_mode='restart'),
]

# sub-settings: parent multiplier -> its sources [(source, name, description)]; the counterpart in the game is where multiplier(parent, source) is called
_NPC = ('npc', 'Aliens', 'When you destroy an alien (NPC).')
_BOX = ('box', 'Boxes and chests', 'Bonus boxes, event boxes and booty chests.')
_QUEST = ('quest', 'Quests', 'Quests from the quest window and Urgent Missions.')
_GATE = ('gate', 'Gates', "When you complete Galaxy Gates (Dispatch gate runs included) and event gates (Plutus, Quarantine "
                          "…).")
_MOD = ('mod', 'Modes and events', 'Rewards of Astral, EBL, Galaxy Trek, Mimesis, Apotheosis, Voyagers, Trinity, Deep Space Echoes, the '
                                   'Labyrinth, world bosses, Battle Station, Dispatch and events.')
_EXTRA = ('extra', 'Extra alien rewards', 'Palladium, event currency and resources you get for destroying an alien.')
_PLACE = (('map', 'On maps', 'Aliens and bosses roaming the maps.'),
        ('wave', 'In gate and mode waves', 'Aliens in the waves of Galaxy Gates, event gates and modes (Astral, EBL, Voyagers, Trinity, Mimesis '
                                            '…).'))
_MONEY = (_NPC, _BOX, _QUEST, _GATE, _MOD)
SUBS = {
    'credits': _MONEY, 'uridium': _MONEY, 'ep': _MONEY, 'honor': _MONEY,
    'collecting': (_BOX, ('cargo', 'Alien cargo boxes', 'Ore in the cargo box an alien leaves behind.'),
                ('ore', 'Mining', 'Amount collected from ores on the map.'), _EXTRA),
    'mode_reward': (_QUEST, _GATE, _MOD),
    'drop': (('booster', 'Booster', 'Booster drops from Boss and Uber aliens.'), _EXTRA,
              ('event', 'Event drops', 'Boxes from event and event gate aliens, Chromin boxes, Hitac lottery letters.'),
              ('gate', 'Gates', 'Lucky rewards of Galaxy Gates and event gates (designs, LF-4 …).'),
              ('mod', 'Modes', "Astral's salvage core and keys, EBL's extra reward.")),
    'npc_damage': _PLACE, 'npc_hp': _PLACE,
    'player_damage': (('pve', 'Vs aliens (PvE)', 'Damage you deal to aliens (NPCs).'),
                     ('pvp', 'Vs players (PvP)', 'Damage you deal to other players with lasers and rockets.'),
                     ('bot', 'Vs bots', 'Damage you deal to bots.')),
    'box_abundance': (('bonus', 'Bonus boxes', 'Bonus boxes scattered across the maps.'),
                    ('booty', 'Booty chests', 'Booty chests opened with a key.'),
                    ('event', 'Event boxes', 'Boxes that events bring to the maps.')),
    'npc_count': (('map', 'Map aliens', "The map's own aliens and bosses."),
                 ('event', 'Event aliens', 'Aliens that events bring to the maps.')),
    'shop_price': (('credits', 'Sold for credits', 'Everything priced in credits in the shop.'),
                     ('uridium', 'Sold for uridium', 'Everything priced in uridium in the shop.')),
    'service_price': (('pet', 'P.E.T.', "P.E.T. slots, repair and fuel."),
                     ('skylab', 'Skylab', 'Upgrades, instant finish, fast transport and robots.'),
                     ('warp', 'Ship warp', 'Bringing another of your ships to you without going to the hangar.')),
    'cooldown': (('assembly', 'Assembly crafting', "Crafting items in the Assembly."),
                ('skylab', 'Skylab', 'Module upgrades and transport.'),
                ('dispatch', 'Dispatch', 'Missions and gate runs.'),
                ('upgrade', 'Item upgrades', 'Level upgrades of lasers, generators, drones and modules.')),
    'skill_cooldown': (('skill', 'Ship abilities', "Your ship's own abilities."),
                        ('item', "Combat items and CPUs", "Mines, Smart Bomb, Insta-Shield, EMP, special rockets and CPUs."),
                        ('technology', 'Tech items', 'Energy Leech, Chain Impulse, Battle Repair Bot, Speed Burst …'),
                        ('particle', 'Particle cannons and drive', 'Particle weapons and the Singularity Drive.')),
}
SCHEMA = [x for s in SCHEMA for x in [s] + [dict(s, key='%s_%s' % (s['key'], k), name=name, description=description, default=1.0,
                                                 parent=s['key'], source=k) for k, name, description in SUBS.get(s['key'], ())]]
SUB = {(s['parent'], s['source']): s['key'] for s in SCHEMA if s.get('parent')}
BY_KEY = {s['key']: s for s in SCHEMA}
DEFAULTS = {s['key']: s['default'] for s in SCHEMA}
EVENT_STATES = ('on', 'off')         # otherwise by the calendar

# presets (the panel's "Presets" list): only the changed keys, the others are default
PRESETS = {
    'default': {'name': 'Default', 'description': "The game's own values.", 'values': {}},
    'casual': {'name': 'Relaxed', 'description': 'You take less damage; rewards and boxes are plentiful.',
              'values': {'npc_damage': 0.5, 'credits': 2.0, 'uridium': 2.0, 'ep': 2.0, 'honor': 2.0, 'collecting': 2.0, 'drop': 2.0,
                           'box_abundance': 2.0, 'box_respawn': 0.5, 'mode_reward': 2.0, 'drone_xp': 2.0, 'pet_ep': 2.0,
                           'shield_regen': 2.0}},
    'fast': {'name': 'Fast progress', 'description': 'Five times the rewards; aliens are plentiful and respawn quickly.',
              'values': {'credits': 5.0, 'uridium': 5.0, 'ep': 5.0, 'honor': 5.0, 'collecting': 5.0, 'drop': 3.0, 'box_abundance': 3.0,
                           'box_respawn': 0.3, 'npc_count': 1.5, 'npc_respawn': 0.3, 'shop_price': 0.5, 'mode_reward': 5.0,
                           'drone_xp': 5.0, 'pet_ep': 5.0, 'season_points': 3.0, 'skylab_production': 3.0, 'ore_abundance': 2.0,
                           'wave_wait': 0.5}},
    'hard': {'name': 'Hard', 'description': 'Aliens hit harder and last longer, rewards are low, rivals are aggressive.',
              'values': {'npc_damage': 2.0, 'npc_hp': 1.5, 'credits': 0.75, 'uridium': 0.75, 'box_abundance': 0.5,
                           'repair_cost': 2.0, 'auction_rivals': 4, 'npc_hit_chance': 1.25, 'npc_aggression': 1,
                           'shield_regen': 0.5}},
    'creative': {'name': 'Creative', 'description': "Your ship can't be destroyed, ammo never runs out, the shop and services are free, no waiting.",
                 'values': {'immune_until': True, 'infinite_ammo': True, 'infinite_technology': True, 'shop_price': 0.0, 'service_price': 0.0,
                              'gate_price': 0.0, 'repair_cost': 0.0, 'cooldown': 0.0, 'no_level_limit': True,
                              'infinite_lives': True, 'no_entry_limit': True, 'pet_fuel': 0.0, 'assembly_free': True,
                              'infinite_cargo': True, 'infinite_pet_range': True}},
}

_lock = threading.Lock()
_state = {'route': None, 'mtime': None, 'read_at': 0.0, 'd': {}}


def clean(raw):
    """Dict from the file -> valid values (no unknown keys, numbers at the limits, types correct)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, v in raw.items():
        s = BY_KEY.get(key)
        if s is None:
            continue
        try:
            if s['type'] == 'multiplier':
                v = float(v)
                if v != v:                                # NaN
                    continue
                out[key] = min(s['cap'], max(s['min'], v))
            elif s['type'] == 'bool':
                out[key] = bool(v)
            elif s['type'] == 'level':
                out[key] = min(len(s['options']) - 1, max(0, int(v)))
            elif s['type'] == 'number':
                v = float(v)
                if v != v:                                # NaN
                    continue
                out[key] = int(round(min(s['cap'], max(s['min'], v))))       # infinity also to the limit
        except (TypeError, ValueError):
            continue
    ev = raw.get('events')
    if isinstance(ev, dict):
        out['events'] = {str(k): v for k, v in ev.items() if v in EVENT_STATES}
    return out


def read(path):
    """The settings in the file (cleaned); {} if the file is missing or corrupt."""
    try:
        with open(path, encoding='utf8') as fh:
            return clean(json.load(fh))
    except (OSError, ValueError):
        return {}


def write(path, values):
    """Write the settings atomically (panel). Values equal to the default are written too: the file is the user's choice."""
    d = clean(values)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return d


def configure(argv=None, path=None):
    """Bind the settings file: path, otherwise the --settings=<path> option, otherwise save/settings.json. path=False: unbind (defaults)."""
    if path is None:
        argv = sys.argv if argv is None else argv
        path = next((a.split('=', 1)[1] for a in argv if a.startswith('--settings=')), DEFAULT_PATH)
    with _lock:
        _state.update(route=path or None, mtime=None, read_at=0.0, d={})
    return path


def _current():
    with _lock:
        if not _state['route']:
            return _state['d']
        now = time.monotonic()
        if _state['mtime'] is not None and now - _state['read_at'] < REFRESH_SEC:
            return _state['d']
        _state['read_at'] = now
        try:
            m = os.stat(_state['route']).st_mtime_ns
        except OSError:
            m = 0
        if m != _state['mtime']:
            _state['mtime'] = m
            _state['d'] = read(_state['route']) if m else {}
        return _state['d']


def get(key):
    return _current().get(key, DEFAULTS[key])


def multiplier(key, source=None):
    """Multiplier; if source is given it is multiplied by the sub-setting (multiplier('uridium', 'npc') = uridium x uridium_npc). If the source has no
    sub-setting, only the parent."""
    sub = SUB.get((key, source))
    return float(get(key)) * (float(get(sub)) if sub else 1.0)


def version():
    """Version of the settings file (time of modification; None if unbound): to notice a setting changed while the game is open (world.settings_tick)."""
    _current()
    with _lock:
        return _state['mtime']


def price(key, n, source=None):
    """Scale a price by the multiplier (service fees ...): integer, at least 0, fits a 32-bit field."""
    m = multiplier(key, source)
    return n if m == 1.0 or not n else min(I32, max(0, int(round(n * m))))


def count(key, n, source=None):
    """Scale a number (aliens, box count) by the multiplier: rounded, a positive number stays at least 1 (a boss does not vanish); 0 if the multiplier is 0."""
    m = multiplier(key, source)
    if m == 1.0 or not n or n < 0:
        return n
    return 0 if m <= 0 else max(1, int(round(n * m)))


def amount(key, n, source=None):
    """Scale an amount (reward, collected item) by the multiplier: the fraction is rounded probabilistically (with x1.5, 1 -> half the time 1 or 2),
    the expected value is exactly the multiplier."""
    m = multiplier(key, source)
    if m == 1.0 or not n or n < 0:
        return n
    v = n * m
    whole = int(v)
    return whole + (1 if random.random() < v - whole else 0)


def duration(sec, source=None):
    """Production and cooldown time (the panel's 'cooldown' multiplier; sources: assembly, skylab, dispatch, upgrade) -> seconds (at least 1)."""
    m = multiplier('cooldown', source)
    return sec if m == 1.0 else max(1, int(round(sec * m)))


def chance(key, p, source=None):
    """Scale a probability by the multiplier (0..1)."""
    m = multiplier(key, source)
    return p if m == 1.0 else min(1.0, max(0.0, p * m))


def event_state(key):
    """The player's event choice: 'on', 'off' or None (by the calendar)."""
    return (_current().get('events') or {}).get(key)


def full_name(s, name=lambda x: x):
    """The setting's name in summaries: a sub-setting together with its parent ('Uridium gain › Aliens'); name: translation (panel)."""
    return name(BY_KEY[s['parent']]['name']) + ' › ' + name(s['name']) if s.get('parent') else name(s['name'])


def summary(values=None):
    """Settings that differ from the default [(name, value text)] (the panel's summary chips)."""
    d = _current() if values is None else clean(values)
    out = []
    for s in SCHEMA:
        v = d.get(s['key'], s['default'])
        if v == s['default']:
            continue
        if s['type'] == 'multiplier':
            out.append((full_name(s), 'x%g' % v))
        elif s['type'] == 'bool':
            out.append((s['name'], 'on' if v else 'off'))
        elif s['type'] == 'number':
            out.append((s['name'], ('%d %s' % (v, s.get('unit', ''))).strip()))
        else:
            out.append((s['name'], s['options'][v]))
    return out
