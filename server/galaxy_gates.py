"""Galaxy Gates (all of those in the builder: Alpha, Beta, Gamma, Delta, Epsilon, Zeta, Kappa, Lambda, Kronos, Hades, Kuiper): the gate
builder (energy, parts, multiplier), preparation, the gate portal in X-1, waves on the gate map, lives and completion rewards.

The flow in the record (at session start and in the builder window):
  GalaxyGateBuilderInfoRequest      -> GalaxyGateBuilderInfoCommand (gates, part count, lives, multiplier, energy price 100, uridium
                                       "money", free energy "samples")
  GalaxyGateBuilderGetGatePartsRequest {gateId} -> GalaxyGateBuilderGetGatePartsCommand (collected part ids)
  GalaxyGateBuilderMultiEnergyRequest {spinAmount, useMultiplier, gateId} -> GalaxyGateBuilderMultiEnergyCommand (results:
                                       GalaxyGateBuilderLootItemModule {type, item_id, amount, spins}: in the record ORE 4/13 and HITPOINTS 1/11000)
Not in the record, from the client's code and texts (GalaxyGateComponentSystem, UIGalaxyGatesSystem, galaxygates_* texts):
  GalaxyGateBuilderSetupGateRequest -> GalaxyGateBuilderSetupGateCommand {livesLeft, lifePrice}; the gate appears in X-1 next to the base
  GalaxyGateBuilderBuyLifeRequest   -> GalaxyGateBuilderBuyLifeCommand (the life price doubles with each purchase, wiki)
  on the gate map GalaxyGateBuilderGateWaveUpdateCommand (sub-wave counter), GateLifeLostCommand (death), GateCompleteCommand (end)
  on-screen messages with MessageCommand (client: MessageCommandHandler; BIG = big notification + log, NORMAL = short message at the top).
  Since the gate was not played in the record, the real server's texts are unknown: the client's own texts (atk_wave_started,
  log_galaxygate_wave_name, log_msg_gg_completed_*) and data/gates.json "mesajlar" (countdown, wave over ...). The client's
  countdown commands (EpicFightMessageCommand, CountdownStatusCommand) have empty handlers in this version and cannot be used.
Built gate (2026-10-19, user report: energy on a built gate gave "An unidentified error"): the client keeps the energy button enabled
regardless of the gate's state, and the response has only 0 / not enough uridium / "unclassified_error" (ParseProduceResponse);
a spin on a built gate is also accepted: every part is a duplicate (multiplier), the other rewards as usual. The built gate's state (state FINISHED)
opens Prepare jump and the client shows the "Gate ALPHA construction finished" notification on every info it receives (UIGalaxyGatesSystem.RefProgress);
so that the notification appears once, when the client already has the same info the window's request goes unanswered (info_request). When the gate is prepared
(PREPARE JUMP, its portal in X-1) the state IN_PROGRESS is sent.
Gate map: main waves, each with sub-waves ("groups": the unit of the window's wave counter). When a wave starts all
aliens queue up and spawn one by one spawn_interval_sec apart, dogma_uzaklik away from the player, and come at them; when all are dead the wave
ends (user report 2026-10-28: like the real game; a mass spawn on a ring caused piling up and getting stuck). The escort groups of the shielded boss
(Zeta Devourer) spawn together around the boss (boss_spawn). After a main wave two portals open in the middle
(official gate guide): the left one to the next wave (same map; on entering it starts with a countdown), the right one home. If the player goes home
progress is kept. When hit the player is repaired at base and loses 1 life; with no lives the gate (with its parts) is lost. Values in
data/gates.json (tools/gates.py).
Gate-specific rules:
  Alpha, Beta, Gamma (ABG): shared spin in the builder; a part drops to one of the three regardless of the selected gate (the other rewards as usual).
  Zeta (3 maps) and Kuiper (5 maps): after the map's last wave the left portal leads to the next map; the gate portal in X-1
  leads to the map of the wave you were on.
  Zeta Devourer ("kalici"): comes at the start of the wave; the escort groups are around it, the species of one family (normal, Boss, Uber)
  spawn together; while a group is alive its Insta-Shield is on and it takes no damage, when the group ends the shield drops for shield_gap_sec (10), then the next group
  (fandom Galaxy Gates); in the gap its HP stops at the next group's share (7 groups: 6/7, 5/7 ...) and reaching it brings the next group at
  once, so it dies only after the last group (forum 127323: "you must destroy all 7 groups"; Run.boss_floor).
  Kronos: no spin in the builder; its parts come from completing the other gates (1 per completion, 2 on Saturday; at most the number in the wiki per gate:
  Alpha 4, Beta 3, Gamma 1, Delta 1, Epsilon 4, Zeta 1, Kappa 2, Lambda 5 = 21). Progress per gate in the builder window
  (GalaxyGateBuilderMultiGateProgressModule). "Evil Clone Of Your Ship" comes with the player's own look.
  Hades: half-size map in the client (maps-config.xml scaleFactor 0.5); it was a group gate, here single-player (group when bots come).
"""
import json, math, os, random, time
import game_data as DATA
import ranks as RT
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
K = DATA.load('gates.json')
GATES = K['gates']
BY_ID = {v['uid']: k for k, v in GATES.items()}
BY_MAP = {m: k for k, v in GATES.items() for m in v['maps']}
SIZES = {int(m): tuple(s) for v in GATES.values() for m, s in v['sizes'].items()}     # gate maps that differ from the standard size
KRONOS_PARTS = next((v['part'] for v in GATES.values() if 'sources' in v), 0)
# the client's enums (GalaxyGateBuilder*)
IN_PROGRESS, FINISHED = 0, 1
ERR_NONE, ERR_MONEY, ERR_OTHER = 0, 1, 2
BATTERY, ROCKET, MINE, ORE, VOUCHER, PART, HITPOINTS, LOGFILE = 1, 2, 3, 4, 5, 6, 7, 8
CAT_AMMO, CAT_RES, CAT_VOUCHER, CAT_PART, CAT_SPECIAL, CAT_LOG = 1, 2, 3, 4, 5, 6
XENOMIT, XENOMIT_ITEM = 3, 4              # the server's ore type; the client's builder id (record: ORE 4)
PORTAL_BASE = 150900000                   # gate portal ids: + gate id (X-1), + 50 + id (exit from the gate),
NEXT_PORTAL = 100                         # + 100 + id (the next map in a multi-map gate)
HOME_MAP = {1: 1, 2: 5, 3: 9}
# shield absorption of gate aliens (if the type has none of its own): player report 2026-10-27, in the real game gate aliens have 50% (map
# aliens 70%, npc.json savas.npc_kalkan_emme); with the Moth formation they die before their shield runs out. No number in the source
GATE_ABSORB = 0.5
ABG = ('alpha', 'beta', 'gamma')        # shared spin in the builder: the part drops to one of the three (Kapilar.draw)
MAP_W, MAP_H = 21000, 13100
# Gate rings (ShipInitializationCommand / ShipCreateCommand galaxyGatesDone): the client reads a 7-bit mask
# (UnitDataComponentSystem.UpdateIcons: if bit i is set the ith ring on the name plate; icons alphaToDelta_gg x4, epsilonZeta_gg x2,
# kronos_gg; if all seven are set only the crown). Previously the count rose by 1 on each completion: after Gamma the ring of 1 Alpha, then
# after Alpha the ring of 2 Beta was shown (user report 2026-10-25).
RINGS = {'alpha': 1, 'beta': 2, 'gamma': 4, 'delta': 8, 'epsilon': 16, 'zeta': 32, 'kronos': 64}


def mod(name, **f):
    f['_'] = name
    return f


def rings(profile):
    """The profile's gate rings (galaxyGatesDone): the bits of gates completed at least once (a gate completed via Dispatch counts too)."""
    gates = (profile.d.get('gates') or {}).get('gates', {})
    return sum(bit for key, bit in RINGS.items() if gates.get(key, {}).get('done'))


DISPLAY_BOTH, STYLE_BIG, STYLE_NORMAL = 2, 0, 1       # MessageCommand.DisplayTarget / DisplayStyle (client)
VM_SHIELD = 33                                        # VisualModifier INVINCIBILITY: the shielded boss's Insta-Shield (Kosu.shield)


def screen(text, big=False, **wild):
    """On-screen message: "key:name" is the client's translated text (%AD% placeholders from wild), otherwise plain text."""
    if text.startswith('key:'):
        key, kind = text[4:], 5
        reps = [mod('MessageWildcardReplacementModule', wildcard='%%%s%%' % k, replacement=str(v),
                    replacementType=mod('ReplacementTypeModule', typeValue=0)) for k, v in wild.items()]
    else:
        key, kind, reps = text, 0, []
    return ('MessageCommand', dict(displayTarget=DISPLAY_BOTH, displayStyle=STYLE_BIG if big else STYLE_NORMAL,
                                   messageModule=mod('WildcardMessageModule', message=mod(
                                       'MessageKeyListWildcardModule', wildCardReplacements=reps, baseKey=key,
                                       baseKeyType=mod('ReplacementTypeModule', typeValue=kind), textStyle=0))))


from legacy_protocol import legacy, loot_kind, loot_line, stm  # noqa: E402,F401  (old text protocol: legacy_protocol.py)


def npc_type(key, wave, i):
    """The NPC type of a gate alien (added to world.CFG tipler): by its order in the wave (the same alien can appear several times in a wave)."""
    return 'gg_%s_%d_%d' % (key, wave, i)


def register_npcs(types):
    """Adds the gate aliens as NPC types: name, look (the client's ship type), speed and npcId from gates.json; with gate-specific
    behavior (Kronos's rockets, Kappa Annihilator's closed launcher: alien.of) if there is any."""
    for key, g in GATES.items():
        for n, w in enumerate(g['waves']):
            for i, a in enumerate(w['alien_spawns']):
                types[npc_type(key, n, i)] = dict(
                    name=a['display_name'], model=a['type'], hp=a['hp'], shield=a['shield'], damage=a['damage'], speed=a['speed'],
                    aggressive=True, reward=dict(a['reward']), cargo=dict(a['cargo']), npc_id=a['npc_id'], gate=key,
                    shield_absorb=a.get('shield_absorb', GATE_ABSORB))
                if a.get('behavior'):
                    types[npc_type(key, n, i)]['behavior'] = dict(a['behavior'])


def spread(cx, cy, count, map_w, map_h):
    """A group's spawn points: in an area around the center that grows with the count, at least group_spacing units apart (so a crowded group does not
    spawn stacked on a single point)."""
    rad = K['group_radius'][0] + K['group_radius'][1] * math.sqrt(count)
    spots = []
    for _ in range(count):
        for _try in range(20):
            x = min(max(cx + random.uniform(-rad, rad), 300), map_w - 300)
            y = min(max(cy + random.uniform(-rad, rad), 300), map_h - 300)
            if all(math.hypot(x - px, y - py) >= K['group_spacing'] for px, py in spots):
                break
        spots.append((x, y))
    return spots


def ring(hx, hy, groups, map_w, map_h, radius=None):
    """A gate wave's spawn ring: evenly spaced around the player, the aliens of each type spread along the ring (user
    report 2026-10-24: a sub-wave spawned stacked on a single point). Those that do not fit the ring (spacing at least group_spacing) go on a second
    ring outside; the ring's center is the point closest to the player such that the ring fits the map. groups: [(key, count)] -> [(key, x, y)].
    radius: the first ring's radius range (dogma_uzaklik if absent; the Devourer's escorts are around it: shield_spawn)."""
    order = [key for _, key in sorted(((j + 0.5) / n, key) for key, n in groups for j in range(n))]
    rings, r, left = [], random.uniform(*(radius or K['spawn_distance'])), len(order)
    while left > 0:
        n = min(left, max(1, int(2 * math.pi * r / K['group_spacing'])))
        rings.append((r, n))
        left -= n
        r += 2 * K['group_spacing']
    edge = 300 + rings[-1][0] if rings else 0
    cx = min(max(hx, edge), map_w - edge) if map_w > 2 * edge else map_w / 2
    cy = min(max(hy, edge), map_h - edge) if map_h > 2 * edge else map_h / 2
    out, base = [], random.uniform(0, 2 * math.pi)
    for r, n in rings:
        for j in range(n):
            a = base + 2 * math.pi * (j + random.uniform(-0.2, 0.2)) / n
            x = min(max(cx + math.cos(a) * r, 300), map_w - 300)
            y = min(max(cy + math.sin(a) * r, 300), map_h - 300)
            out.append((order[len(out)], x, y))
    return out


def far_spot(hx, hy, map_w, map_h, distance=None):
    """A single alien's spawn point: dogma_uzaklik away from the player in a random direction; avoids directions that get shorter at the map edge (if none
    suffices, the farthest). An alien that spawns far away only catches up while the player is cutting the previous one down. distance: [min, max]
    instead (a stationary alien never catches up: it spawns in sight)."""
    lo_hi = distance or K['spawn_distance']
    best = None
    for _ in range(12):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(*lo_hi)
        x = min(max(hx + math.cos(a) * r, 300), map_w - 300)
        y = min(max(hy + math.sin(a) * r, 300), map_h - 300)
        d = math.hypot(x - hx, y - hy)
        if d >= lo_hi[0]:
            return x, y
        if best is None or d > best[0]:
            best = (d, x, y)
    return best[1:]


STATIONARY_DISTANCE = (600, 1000)        # spawn distance of an alien that does not move (far_spot)


def center(map_id):
    w, h = SIZES.get(int(map_id), (MAP_W, MAP_H))
    return w // 2, h // 2


def group_weights(w):
    """The wave's groups' share of the counter (group_counter; if absent 1 per group): in Zeta's last wave an escort group counts as as many
    sub-waves as it has species (Streuner group zeta30-34: five species come together)."""
    return w.get('group_counter') or [1] * len(w['groups'])


def sub_waves(g, n):
    """The number of sub-waves of the first n main waves: the unit of the client's wave counter (GetGateTotalWaves: Alpha 40 ... Hades 12; Hades's
    stage is a quarter of this). The persistent alien (Zeta Devourer) is its own sub-wave (client Zeta 46)."""
    return sum(sum(group_weights(w)) + any(a.get('permanent') for a in w['alien_spawns']) for w in g['waves'][:n])


def wave_map(g, n):
    """The nth wave's map (the last wave's for a finished gate)."""
    waves = g['waves']
    return waves[min(n, len(waves) - 1)]['map']


def pace(name):
    """Wave waiting time (entry, between sub-waves, break; seconds): with the panel's 'wave_wait' multiplier (event gates too)."""
    return int(round(K[name] * SET.multiplier('wave_wait')))


def fresh(g, old=None):
    out = {'parts': sorted((old or {}).get('next', [])), 'ready': False, 'wave': 0, 'hp': g['hp'], 'lives_bought': 0,
           'done': (old or {}).get('done', 0)}      # parts collected while a ready gate is in progress (next) go to the new gate
    if 'sources' in g:
        out['source'] = {}                # Kronos: how many parts came from which gate
    return out


# ------------------------------------------------------------ timed gate bonuses
def bonus_period(now=None):
    """Bonus period -> (index, end time): the panel's gate_bonus_hours, aligned to local midnight."""
    now = time.time() if now is None else now
    span = max(1, int(SET.get('gate_bonus_hours'))) * 3600
    off = time.localtime(now).tm_gmtoff or 0
    idx = int((now + off) // span)
    return idx, (idx + 1) * span - off


def bonus_amount(n):
    """The panel's multiplier (rewards with amounts; a single item is one): exact, what is given is the same as what the window shows."""
    m = SET.multiplier('gate_bonus_multiplier')
    return n if n <= 1 or m == 1.0 else max(1, int(round(n * m)))


def bonus_selection(now=None):
    """This period's bonus gates -> {gate: (lootId, count)}; fixed within the period (a choice seeded with the period's index)."""
    B = K.get('bonus') or {}
    n = int(SET.get('gate_bonus_count'))
    gates = [k for k in B.get('gates', []) if k in GATES]
    pool = B.get('rewards', [])
    if n <= 0 or not gates or not pool:
        return {}
    idx, _ = bonus_period(now)
    rng = random.Random('kapi-bonus-%d-%d' % (int(SET.get('gate_bonus_hours')), idx))
    pick = rng.sample(gates, min(n, len(gates)))
    loots = rng.sample(pool, len(pick)) if len(pool) >= len(pick) else [rng.choice(pool) for _ in pick]
    # EP and honor as ranges ([min, max]): chosen with the period's seed, fixed within the period
    return {k: (l, bonus_amount(rng.randint(*a) if isinstance(a, list) else a)) for k, (l, a) in zip(pick, loots)}


def ammo_type(loot):
    """The ammo result's type. Rockets and mines go with LootItemModule (client ParseOutputList: type 2/3, item_id 3 -> PLT-2021,
    11 -> ACM-01; AmmoOutputVo.ToStr: log_entry_rocket, log_entry_mine_s/p); laser ammo as a battery."""
    return ROCKET if loot.startswith('ammunition_rocket_') else MINE if loot.startswith('ammunition_mine_') else BATTERY


def weights():
    """Spin weights (the probabilities in the record); the panel's 'gate_part' multiplier changes the part's."""
    f = SET.multiplier('gate_part')
    return [[c, w * (f if c == CAT_PART else 1)] for c, w in K['probability']]


def percentages():
    """The percentages in the window (total 100, by the largest remainder method)."""
    wts = weights()
    tot = sum(w for c, w in wts) or 1
    raw = [(c, 100.0 * w / tot) for c, w in wts]
    out = {c: int(v) for c, v in raw}
    for c, v in sorted(raw, key=lambda cv: cv[1] - int(cv[1]), reverse=True)[:100 - sum(out.values())]:
        out[c] += 1
    return out


# gate loot -> the client's lootId (daily rewards store it under the same name)
LOOT_IDS = {'abr': 'resource_collectable_axion-beam-regulator', 'schism': 'resource_collectable_schism', 'green_key': 'resource_booty-key'}


def record_duration(save, key, sec):
    """A gate's completion time (statistics; player request 2026-10-30) -> save['gate_times'][key] {best, last, number} (s)."""
    d = save.setdefault('gate_times', {}).setdefault(key, {'best': 0, 'last': 0, 'number': 0})
    sec = int(max(1, sec))
    d.update(last=sec, number=d['number'] + 1, best=min(d['best'], sec) if d['best'] else sec)
    return d


class Gates:
    """The session's gate builder (profile: gates) and the run on the gate map."""

    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                 # shop (item/money messages)
        self.world = lambda: None     # the session's current world
        self.info_tpl = None          # the GalaxyGateBuilderInfoCommand in the record (other gates as they are)
        self.sent = None              # the gate info the client holds in the session (info_request)
        self.titles = None            # gate completion title (the session binds: title_hunt.grant_title)

    # ------------------------------------------------------------ profile
    @property
    def d(self):
        """The gate section in the profile (created if absent). Lockless: the profile lock cannot be re-entered, callers use it inside the lock."""
        d = self.p.d.get('gates')
        if d is None:
            d = self.p.d['gates'] = {'energy': 0, 'multiplier': 0, 'spin': 1, 'log_disk': 0, 'voucher': 0, 'gates': {}}
        if 'booty' in d:                       # old profile: gate loot was kept separately -> other_items (lootId)
            other = self.p.d.setdefault('other_items', {})
            for k, n in d.pop('booty').items():
                other[LOOT_IDS.get(k, k)] = other.get(LOOT_IDS.get(k, k), 0) + n
        for k, g in GATES.items():
            if k not in d['gates']:
                d['gates'][k] = fresh(g)
            elif 'sources' in g:
                d['gates'][k].setdefault('source', {})
        return d

    def gate(self, key):
        return self.d['gates'][key]

    def built(self, key):
        return len(self.gate(key)['parts']) >= GATES[key]['part']

    def mult(self, key):
        """The builder's multiplier: Alpha, Beta and Gamma share one (official record 2026-10-25: a Beta duplicate while spinning Alpha raised
        the Alpha multiplier), every other gate has its own (same record: Zeta 5 while Alpha 0). Old profiles kept one for all: it stays ABG's."""
        return self.d['multiplier'] if key in ABG else self.gate(key).get('multiplier', 0)

    def set_mult(self, key, n):
        if key in ABG:
            self.d['multiplier'] = n
        else:
            self.gate(key)['multiplier'] = n

    def parts(self, key):
        """The list the parts go to on a spin: the next gate's if a gate is prepared and on the map (player report 2026-10-27: in the real game
        parts drop even while a built gate is on the map; ours counted all as duplicates and turned them into the multiplier), otherwise the gate itself."""
        G = self.gate(key)
        return G.setdefault('next', []) if G['ready'] else G['parts']

    def state(self, key):
        """The state in the window: FINISHED if built and not yet prepared (the client opens "Prepare jump" and shows the "construction
        finished" notification); a prepared gate is IN_PROGRESS (its portal in X-1, so the notification does not appear on every open)."""
        return FINISHED if self.built(key) and not self.gate(key)['ready'] else IN_PROGRESS

    def energy_price(self):
        """Energy price: Premium -5% (everyone is premium in single player; galaxy_gates.md), Shop Discount (rebate) -25% if active, weekend
        -15%; discounts add up (wiki: lowest 55 = 100 - 25 - 5 - 15; client galaxygates_costs_discount_p "Premium and
        rebate are used as usual"). Player report 2026-10-27: rebate + Premium showed 80 (with the weekend) instead of 70."""
        import event_calendar as CAL
        sale = CAL.is_active('gate_weekend')    # Saturday-Sunday (event_calendar.py)
        disc = self.m.discount() if self.m else K.get('premium_discount', 0)     # Premium + Shop Discount (shop.discount)
        f = (1 - disc - (K['weekend_discount'] if sale else 0)) * SET.multiplier('gate_price')     # panel
        return int(round(K['energy_price'] * f)), sale

    def life_price(self, key):
        G = self.gate(key)
        if not G['ready']:
            return -1
        pr = K['life_prices']
        # the final price after the limit too: if -1 goes away the client (GalaxyGateComponentSystem.ParseGateLifePurchaseResponse) counts the fully
        # collected gate as "completed" (player report 2026-10-30: after buying 5 lives "Galaxy Gate ... completed"); the excess is rejected in buy_life
        return int(round(pr[min(G['lives_bought'], len(pr) - 1)] * SET.multiplier('gate_price')))     # panel

    def money(self):
        return self.p.d['pilot'].get('uridium', 0)

    # ------------------------------------------------------------ timed bonuses
    def bonus_taken(self, now=None):
        """Gates whose bonus was taken in this period (reset when the period changes). Profile: gates.bonus {period, claimed}."""
        idx, _ = bonus_period(now)
        with self.p.lock:
            b = self.d.setdefault('bonus', {})
            if b.get('period') != idx:
                b.clear()
                b.update(period=idx, claimed=[])
                self.p.dirty = True
            return b['claimed']

    def bonus_modules(self, key, now=None):
        """The gate's bonus (GalaxyGateBuilderBonusGGRewardModule; the server's choice instead of the leftovers in the record) or []."""
        now = time.time() if now is None else now
        sel = bonus_selection(now)
        if key not in sel:
            return []
        loot, n = sel[key]
        return [mod('GalaxyGateBuilderBonusGGRewardModule', claimed=key in self.bonus_taken(now),
                    countdown=max(0, int(bonus_period(now)[1] - now)), lootId=loot, amount=n)]

    def claim_bonus(self, key, now=None, mark=True):
        """Gate completed: if the period's bonus is on this gate and not taken it is given; also the chance of a Cyborg / Hammerclaw / Mimesis ship (10,000 uridium
        instead of an owned ship; client msg_bonus_gg_reward_info, wiki) -> (messages, (lootId, count) | None, (ship, was owned) | None)."""
        sel, taken = bonus_selection(now), self.bonus_taken(now)
        if key not in sel or key in taken:
            return [], None, None
        loot, n = sel[key]
        if mark:
            with self.p.lock:                          # bonus_taken takes the lock itself (the lock cannot be re-entered)
                taken.append(key)
                self.p.dirty = True
        self.log('   %s: gate bonus %s x%d' % (GATES[key]['name'], loot, n))
        msgs, ship, S = (self.m.reward(loot, n) if self.m else []), None, K['bonus'].get('ship_chance')
        if S and random.random() < SET.chance('drop', S['probability'], 'gate'):
            ship_rec = random.choice(S['ships'])
            had = ship_rec in {x['lootId'] for x in self.p.d['ships'].values()}
            ship = (ship_rec, had)
            if self.m:
                msgs += self.m.prize('currency_uridium', S['fallback_uridium'], 'gate') if had else self.m.reward(ship_rec, 1)
            self.log('   %s: bonus ship %s%s' % (GATES[key]['name'], ship_rec, ' (owned: %d U)' % S['fallback_uridium'] if had else ''))
        return msgs, (loot, n), ship

    # ------------------------------------------------------------ builder window
    def gate_module(self, tpl, key):
        G, g = self.gate(key), GATES[key]
        out = dict(tpl)
        if out.get('probabilityModules') and SET.multiplier('gate_part') != 1.0:       # panel: gate part chance (percentages)
            pct = percentages()
            out['probabilityModules'] = [dict(m, percentage=pct.get(m.get('category'), m.get('percentage', 0)))
                                         for m in out['probabilityModules']]
        out.update(currPart=len(self.parts(key)), currWave=sub_waves(g, G['wave']), state=self.state(key),
                   livesLeft=G['hp'] if G['ready'] else -1, lifePrice=self.life_price(key), multiplier=self.mult(key), mode=key,
                   id=g['uid'], bonusGGRewardModules=self.bonus_modules(key))
        if 'sources' in g:
            # Kronos: progress per gate as in the record (the name is what the client shows, "Alpha", "Beta" ...)
            # dictionary: mod()'s first argument is also "name"
            out['multiGateProgressModules'] = [{'_': 'GalaxyGateBuilderMultiGateProgressModule', 'total': n,
                                                'current': G['source'].get(k, 0), 'name': GATES[k]['name'].replace(' Gate', '')}
                                               for k, n in g['sources'].items()]
            out['probabilityModules'] = []
        return out

    def info_cmd(self):
        """GalaxyGateBuilderInfoCommand: the template in the record (gate order and probability modules), values from the profile; galaxyGateDay:
        Sunday GG Double Rewards (event_calendar.py gg_cift_odul; official server record 2026-10-25 Sunday: galaxyGateDay true, bonusRewardsDay
        false)."""
        import event_calendar as CAL
        price, sale = self.energy_price()
        t = json.loads(json.dumps(self.info_tpl or {'gates': [], 'spinAmounts': K['spin_amounts'], 'bonusRewardsDay': False,
                                                    'galaxyGateDay': False}))
        t.pop('_m', None)
        gates = []
        have = set()
        for m in t.get('gates', []):
            key = BY_ID.get(m.get('id'))
            gates.append(self.gate_module(m, key) if key else m)
            have.add(key)
        for key in GATES:
            if key not in have:
                gates.append(self.gate_module(mod('GalaxyGateBuilderGateModule', bonusGGRewardModules=[], currWave=0, mode=key, currPart=0,
                                                  boosts=[], state=0, probabilityModules=[], lifePrice=-1, id=0, multiplier=0,
                                                  multiGateProgressModules=[], livesLeft=-1), key))
        t.update(gates=gates, samples=self.d['energy'], money=self.money(), energy_cost=price, spinOnSale=sale,
                 spinamount_selected=self.d['spin'], spinAmounts=K['spin_amounts'], galaxyGateDay=CAL.is_active('gg_double_reward'))
        return ('GalaxyGateBuilderInfoCommand', t)

    def info_request(self):
        """GalaxyGateBuilderInfoRequest: the client asks every time it opens the window. A built gate's FINISHED opened Prepare jump, and on every
        info it also re-opened the "ALPHA gate completed" notification, even after Cancel (UIGalaxyGatesSystem.RefProgress; Cancel sends
        nothing; user, live round 2). When the client already has the same gate info there is no reply: the window opens with what it has (Prepare
        jump enabled, no notification); if only uridium changed in the meantime the window shows the old value."""
        cmd = self.info_cmd()
        seen = self.seen(cmd[1])
        if seen == self.sent and any(g.get('state') == FINISHED for g in cmd[1]['gates']):
            return []
        self.sent = seen
        return [cmd]

    @staticmethod
    def seen(t):
        """The compared section: gates and energy; left out because the bonus reward's countdown drops every second."""
        gates = [dict(g, bonusGGRewardModules=[{k: v for k, v in m.items() if k != 'countdown'} for m in g.get('bonusGGRewardModules', [])])
                 for g in t['gates']]
        return json.dumps([gates, t['samples']], sort_keys=True)

    def part_ids(self, key):
        return sorted(self.parts(key))

    def parts_cmd(self, f):
        key = BY_ID.get(f.get('gateId'))
        return ('GalaxyGateBuilderGetGatePartsCommand', dict(gateId=f.get('gateId', 0), gatePartIds=self.part_ids(key) if key else [],
                                                              errorCode=ERR_NONE if key else ERR_OTHER))

    def save_spin(self, f):
        n = f.get('spinAmount')
        if n in K['spin_amounts']:
            with self.p.lock:
                self.d['spin'] = n
                self.p.dirty = True
        return []

    # ------------------------------------------------------------ spin
    def spin(self, f):
        """GalaxyGateBuilderMultiEnergyRequest: one spin per energy; free energy first, then uridium."""
        gid, n = f.get('gateId'), int(f.get('spinAmount') or 0)
        key = BY_ID.get(gid)
        reply = lambda err, items=(), extra=None: [('GalaxyGateBuilderMultiEnergyCommand', dict(
            gatePartIds=self.part_ids(key) if key else [], items=list(items), spinamount_selected=n, errorCode=err, money=self.money(),
            multiplier=self.mult(key) if key else 0, gateMode=key or '', samples=self.d['energy']))] + (extra or [])
        if not key or n <= 0 or GATES[key].get('not_producible'):
            self.log('   gate builder: no spin (gate %s, %d)' % (gid, n))     # Kronos: its parts come from the other gates
            return reply(ERR_OTHER)
        group = ABG if key in ABG else (key,)    # Alpha/Beta/Gamma: the part goes to one of the three (draw)
        was_built = {k: self.built(k) for k in group}   # a spin on a built gate too: parts are duplicates (multiplier), the other rewards as usual
        price, sale = self.energy_price()
        free = min(n, self.d['energy'])
        cost = (n - free) * price
        if self.money() < cost:
            self.log('   gate builder: not enough uridium (%d U)' % cost)
            return reply(ERR_MONEY)
        results, grants = [], {}
        used = 0
        for _ in range(n):
            if any(not was_built[k] and self.built(k) for k in group):
                break                          # the gate was built in these spins: the remaining energy is not spent
            used += 1
            results += self.draw(key, f.get('useMultiplier'), grants)
        free = min(used, self.d['energy'])
        cost = (used - free) * price
        with self.p.lock:
            self.d['energy'] -= free
            self.p.d['pilot']['uridium'] = self.money() - cost
            self.p.dirty = True
        RT.money(self.p, 'uridium', -cost, 'buy_SPECIAL', qty=used - free)
        msgs = self.give(grants)
        if self.m:
            msgs = self.m.money_msgs() + msgs
        items = self.merge(results)
        self.log('   gate builder %s: %d spins (%d free, %d U), part %s, multiplier %d: %s' % (
            key, used, free, cost, ', '.join('%s %d/%d' % (k, len(self.gate(k)['parts']), GATES[k]['part']) for k in group), self.mult(key),
            ', '.join('%s %s' % (k, v) for k, v in sorted(grants.items()))))
        for k in group:
            if not was_built[k] and self.built(k):
                self.log('   %s gate built' % GATES[k]['name'])
        self.sent = self.seen(self.info_cmd()[1])      # the response carries the parts, the energy and the construction (with its notification) to the client
        # the client keeps a multiplier per gate tab and the reply updates only the spun gate's: the other two ABG tabs showed an old value
        # (user report 2026-11-07: Alpha x6, Beta x4, Gamma x2). An error-free life purchase reply only refreshes that gate's state
        # (GalaxyGateComponentSystem.ParseGateLifePurchaseResponse): one per other ABG gate with its current values.
        sync = [('GalaxyGateBuilderBuyLifeCommand', dict(samples=self.d['energy'], multiplier=self.mult(k), gateId=GATES[k]['uid'], errorCode=ERR_NONE,
                                                         lifePrice=self.life_price(k), money=self.money(), gateMode=k,
                                                         livesLeft=self.gate(k)['hp'] if self.gate(k)['ready'] else -1))
                for k in group if k != key]
        return reply(ERR_NONE, items, msgs + sync)

    def draw(self, key, use_mult, grants):
        """One spin -> result records. A duplicate part becomes the multiplier (at most 5 = x6; on reaching 5 it is used automatically
        on the next reward). If a part comes up with the multiplier, as many different missing parts as the multiplier; if none are missing, the excess is ammo (client FAQ
        galaxygates_multiplier_multilpier_on_parts_p: "you'll win new parts for the gate")."""
        G, g, mk = self.gate(key), GATES[key], key       # mk: the multiplier's gate (ABG: shared)
        wts = weights()
        gm = self.p.d['ship']
        if int(gm.get('nanoHull', 0)) + grants.get('nano', 0) >= gm.get('maxNanoHull', 0):
            wts = [x for x in wts if x[0] != CAT_SPECIAL]      # Nano Hull is full on the active ship: it does not drop, the other rewards instead (fandom Materializer)
        r, cat = random.uniform(0, sum(w for c, w in wts)), CAT_AMMO
        for c, w in wts:          # probabilities in the record: ammo 67, resource 12, coupon 3, part 13, special 4, log 1
            r -= w
            if r < 0:
                cat = c
                break
        if cat == CAT_PART and key in ABG:
            # Alpha, Beta and Gamma are shared in the builder: the part goes to one of the three regardless of the selected gate, to that gate's progress (official ABG
            # builder; user report 2026-10-24: each gate took parts from its own spin). A part falling on a built gate is a duplicate (multiplier)
            key = random.choice(ABG)
            G, g = self.gate(key), GATES[key]
        held = self.mult(mk)
        if cat == CAT_PART and held and (use_mult or held >= K['max_multiplier']):
            mult = held + 1
            P = self.parts(key)
            missing = [i for i in range(1, g['part'] + 1) if i not in P]
            new = random.sample(missing, min(mult, len(missing)))
            with self.p.lock:
                self.set_mult(mk, 0)
                P += new
                self.p.dirty = True
            have = len(P) - len(new)
            out = [dict(type=PART, part_id=pid, duplicate=False, current=have + i + 1, gate_id=g['uid'], mult=mult)
                   for i, pid in enumerate(new)]
            left = mult - len(new)
            if left:                                       # the excess over what is needed is ammo
                loot, iid, amount = random.choice(K['ammunition'])
                grants[loot] = grants.get(loot, 0) + amount * left
                out.append(dict(type=ammo_type(loot), item_id=iid, amount=amount * left, mult=left))
            return out
        if cat == CAT_PART:
            pid = random.randint(1, g['part'])
            P = self.parts(key)
            missing = [i for i in range(1, g['part'] + 1) if i not in P]
            if pid in P and missing and random.random() < SET.get('duplicate_to_missing') / 100.0:     # panel (50% of the game's)
                pid = random.choice(missing)
            dup = pid in P
            with self.p.lock:
                if dup:
                    self.set_mult(mk, min(K['max_multiplier'], held + 1))
                else:
                    P.append(pid)
                self.p.dirty = True
            return [dict(type=PART, part_id=pid, duplicate=dup, current=len(P), gate_id=g['uid'])]
        mult = 1
        if held and (use_mult or held >= K['max_multiplier']):
            mult = held + 1
            self.set_mult(mk, 0)
        if cat == CAT_AMMO:
            loot, iid, amount = random.choice(K['ammunition'])
            grants[loot] = grants.get(loot, 0) + amount * mult
            return [dict(type=ammo_type(loot), item_id=iid, amount=amount * mult, mult=mult)]
        if cat == CAT_RES:
            amount = random.randint(*K['xenomit']) * mult
            grants['xenomit'] = grants.get('xenomit', 0) + amount
            return [dict(type=ORE, item_id=XENOMIT_ITEM, amount=amount, mult=mult)]
        if cat == CAT_VOUCHER:
            grants['voucher'] = grants.get('voucher', 0) + mult
            return [dict(type=VOUCHER, item_id=1, amount=mult, mult=mult)]
        if cat == CAT_SPECIAL:
            amount = random.randint(*K['nano_hull']) // 1000 * 1000 * mult
            grants['nano'] = grants.get('nano', 0) + amount
            return [dict(type=HITPOINTS, item_id=1, amount=amount, mult=mult)]
        grants['log_disk'] = grants.get('log_disk', 0) + mult
        return [dict(type=LOGFILE, item_id=1, amount=mult, mult=mult)]

    def merge(self, results):
        """Turns the results into the client's log lines: identical rewards are summed (spins), parts one by one."""
        now = int(time.time() * 1000)
        out, loot = [], {}
        for r in results:
            if r['type'] == PART:
                key = BY_ID[r['gate_id']]
                # FINISHED on the last part: the client enables the "Prepare jump" button from the gate's state (live test: when IN_PROGRESS went away the button
                # stayed disabled until the window was reopened)
                done = r['current'] >= GATES[key]['part'] and not self.gate(key)['ready']
                out.append(mod('GalaxyGateBuilderPartItemModule', type=PART, date=now, livesLeft=-1, gate_id=r['gate_id'],
                               state=FINISHED if done else IN_PROGRESS, multiplier_used=r.get('mult', 1) - 1, current=r['current'],
                               part_id=r['part_id'],
                               duplicate=r['duplicate'], lifePrice=-1))
                continue
            k = (r['type'], r['item_id'], r['mult'])
            if k not in loot:
                # the client (GalaxyGateComponentSystem.ParseOutputList) converts ammo to BatteryItemModule: when LootItemModule
                # was sent the conversion stayed empty and gave a NullReferenceException (live test). The others are LootItemModule (record).
                cls = 'GalaxyGateBuilderBatteryItemModule' if r['type'] == BATTERY else 'GalaxyGateBuilderLootItemModule'
                loot[k] = mod(cls, type=r['type'], date=now, multiplier_used=r['mult'] - 1, item_id=r['item_id'],
                              spins=0, multiplier_amount=r['mult'] if r['mult'] > 1 else 0, amount=0)
                if r['type'] == BATTERY:
                    loot[k]['defaultOutput'] = False
                out.append(loot[k])
            loot[k]['spins'] += 1
            loot[k]['amount'] += r['amount']
        return out

    def give(self, grants, note=True):
        """Adds the rewards to the profile -> UI messages (ammo counters, inventory, cargo, nano hull)."""
        msgs, p = [], self.p
        for loot, n in sorted(grants.items()):
            if loot.startswith('ammunition_'):
                total = p.add_ammo(loot, n)
                if self.m:
                    iid = self.m.item_id(loot)
                    st = p.menu_status(loot)
                    msgs += ([('MenuItemStatusCommand', st)] if st else []) + [self.m.inv_item(iid, loot, total),
                                                                              self.m.pack([self.m.hangar_item(iid, loot, total)])]
                if note:
                    msgs.append(loot_line(loot, n))
        n = grants.get('xenomit', 0)                                  # Xenomit takes no cargo space (player_profile.CARGO_ORES)
        if n > 0:
            totals = p.add_ores({XENOMIT: n})
            msgs.append(('AttributeOreCountUpdateCommand', {'oreCountList': totals}))
            if self.m:
                msgs.append(self.m.ore_pack([XENOMIT]))
            w = self.world()
            if w:
                msgs += w.quest('loot', loot='resource_ore_xenomit', amount=n)      # collection quests (Alien Ore)
        with p.lock:
            self.d['voucher'] += grants.get('voucher', 0)
            self.d['log_disk'] += grants.get('log_disk', 0)
            self.d['energy'] += grants.get('energy', 0)           # Kronos: 250 free energy (wiki "Energy")
            p.dirty = True
        for k, n in (grants.get('booty') or {}).items():          # ABR, Schism, green key: to the resource storage (profile)
            p.add_resource(LOOT_IDS.get(k, k), n)
        if grants.get('nano'):
            gm = p.d['ship']
            with p.lock:
                gm['nanoHull'] = min(gm.get('maxNanoHull', 0), int(gm.get('nanoHull', 0)) + grants['nano'])
            msgs.append(('HitpointInfoCommand', dict(hitpoints=int(gm.get('hitPoints', 0)), hitpointsMax=gm.get('hitMax', 0),
                                                     nanoHull=int(gm['nanoHull']), nanoHullMax=gm.get('maxNanoHull', 0))))
        return msgs

    # ------------------------------------------------------------ preparation, life, portal
    def setup(self, f):
        """GalaxyGateBuilderSetupGateRequest: the built gate appears in X-1 next to the base (wiki: "PREPARE JUMP")."""
        gid = f.get('gateId')
        key = BY_ID.get(gid)
        if not key or not self.built(key):
            self.log('   gate could not be prepared: %s' % gid)
            return [('GalaxyGateBuilderSetupGateCommand', dict(livesLeft=-1, lifePrice=-1, id=gid or 0, errorCode=1))]
        G = self.gate(key)
        with self.p.lock:
            if not G['ready']:
                G.update(ready=True, wave=0, hp=SET.count('gate_lives', GATES[key]['hp']), lives_bought=0)     # panel: gate lives
            self.p.dirty = True
        w = self.world()
        if w and w.map_id == str(self.home()) and not any(x['gateId'] == PORTAL_BASE + GATES[key]['uid'] for x in w.gates):
            w.add_gate(self.home_portal(key, w.station))
        self.log('   %s gate ready: %d lives' % (GATES[key]['name'], G['hp']))
        return [('GalaxyGateBuilderSetupGateCommand', dict(livesLeft=G['hp'], lifePrice=self.life_price(key), id=gid, errorCode=0))]

    def buy_life(self, f):
        gid = f.get('gateId')
        key = BY_ID.get(gid)
        price = self.life_price(key) if key else -1
        if price >= 0 and self.gate(key)['lives_bought'] >= len(K['life_prices']):
            G = self.gate(key)                       # wiki: five lives can be bought (5,000 ... 80,000 U)
            return [screen('You cannot buy more lives for this gate.'),
                    ('GalaxyGateBuilderBuyLifeCommand', dict(samples=self.d['energy'], multiplier=self.mult(key) if key else 0, gateId=gid or 0,
                                                             errorCode=ERR_NONE, lifePrice=price, money=self.money(), gateMode=key,
                                                             livesLeft=G['hp']))]
        err = ERR_OTHER if price < 0 else ERR_MONEY if self.money() < price else ERR_NONE
        if not err:
            with self.p.lock:
                self.p.d['pilot']['uridium'] = self.money() - price
                G = self.gate(key)
                G['hp'] += 1
                G['lives_bought'] += 1
                self.p.dirty = True
            RT.money(self.p, 'uridium', -price, 'buy_SPECIAL')
            self.log('   %s gate lives bought (%d U), lives %d' % (GATES[key]['name'], price, G['hp']))
        G = self.gate(key) if key else {'hp': -1}
        msgs = [('GalaxyGateBuilderBuyLifeCommand', dict(samples=self.d['energy'], multiplier=self.mult(key) if key else 0, gateId=gid or 0, errorCode=err,
                                                         lifePrice=self.life_price(key) if key else -1, money=self.money(),
                                                         gateMode=key or '', livesLeft=G['hp']))]
        return (self.m.money_msgs() if self.m and not err else []) + msgs

    def home(self):
        return HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)

    def home_portal(self, key, station):
        """The gate portal in X-1: next to the base, toward the middle of the map (gates side by side; rings of five). Leads to the map of the wave
        you were on (Zeta, Kuiper)."""
        g, G = GATES[key], self.gate(key)
        cx, cy = MAP_W // 2, MAP_H // 2
        sx, sy = (station['posX'], station['posY']) if station else (cx, cy)
        ring, slot = divmod(list(GATES).index(key), 5)
        a = math.atan2(cy - sy, cx - sx) + (-0.45, 0, 0.45, 0.9, -0.9)[slot]
        dist = K['portal_distance'] + ring * 1400
        x, y = int(sx + math.cos(a) * dist), int(sy + math.sin(a) * dist)
        fix = K.get('x1_position', {}).get({1: '1', 5: '2', 9: '3'}.get(self.home(), ''), {}).get(key)
        if fix:                                         # forum 127536: a fixed place in the company's X-1
            x, y = fix
        dest = wave_map(g, G['wave'])
        return dict(gateId=PORTAL_BASE + g['uid'], x=x, y=y, target=dest, designId=g['portal'], gate=key, arrival=center(dest))

    def home_portals(self, map_id, station):
        if int(map_id) != self.home():
            return []
        return [self.home_portal(k, station) for k in GATES if self.gate(k)['ready']]

    def exit_portal(self, key, map_id, side=False):
        """Return home from the gate: in the middle of the map (to the right of the next wave's portal while it is open)."""
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + 50 + GATES[key]['uid'], x=x + 700 if side else x, y=y, target=self.home(), designId=1,
                    gate=key, exit=True, arrival='station')

    def next_portal(self, key, map_id, dest):
        """To the next wave (same map; in Zeta and Kuiper after the map's last wave to the next map): left of the middle,
        with the gate's portal design."""
        g = GATES[key]
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + NEXT_PORTAL + g['uid'], x=x - 700, y=y, target=dest, designId=g['portal'], gate=key,
                    arrival=center(dest))

    def kronos_part(self, key, dispatch=False):
        """Gate completed: Kronos part (1 per completion, 2 on Kronos day, always 1 with Dispatch (forum 160334); at most the number in the wiki per gate)
        -> (arrived, total)."""
        kronos = next((k for k, g in GATES.items() if key in g.get('sources', {})), None)
        if not kronos:
            return None
        g, G = GATES[kronos], self.gate(kronos)
        import event_calendar as CAL
        n = 2 if CAL.is_active('kronos_day') and not dispatch else 1     # cumartesi (event_calendar.py)
        with self.p.lock:
            have = G['source'].get(key, 0)
            got = min(n, g['sources'][key] - have)
            if got > 0:
                G['source'][key] = have + got
                G['parts'] = list(range(1, sum(G['source'].values()) + 1))
                self.p.dirty = True
        if got <= 0:
            return None
        self.log('   Kronos part: %s +%d (%d/%d)' % (GATES[key]['name'], got, len(G['parts']), g['part']))
        return got, len(G['parts'])

    def finish(self, key, reward_msgs=None, dispatch=False, multiplier=1):
        """Gate completed (last wave on the gate map or Dispatch's gate dispatch): rewards (wiki; lucky rewards by their probability),
        Kronos part, the gate is reset (a part in the reward is the new gate's first part). reward_msgs: the world's reward messages (otherwise the money
        update). dispatch: quests do not count, no N.O.V.A. bonus (darkorbitwiki dispatch-gate: "boosters don't apply and missions
        don't count"; the achievement counts). Sunday GG Double Rewards (event_calendar.py gg_cift_odul; in Dispatch too): EP, honor, Xenomit, log
        disk, coupon, green key, Kronos ammo/energy and the count of lucky rewards doubled -> (messages, {new, kronos, sans}). In Dispatch the event's
        gate rewards (Empyrian, Prosperous, Galaxy Trek ...) and the Booty Day Schism are absent (wiki dispatch-gate: "will not include rewards
        from special events"; Special Booty Days: "This will not be dropped from Dispatch"); the bonus reward and Double Rewards Day are exceptions."""
        import event_calendar as CAL
        import loot as LOOT
        g, R = GATES[key], GATES[key]['reward']
        # Double Rewards Day in Dispatch too (by collection time; client dispatch_gate_description, forum 160341). Items: forum and in-game
        # windows: UCB-100, ABR and Schism x1; Kronos's RSB-75/UBR-100/energy x2; for a lucky reward the probability is the same, the count x2
        x2 = 2 if CAL.is_active('gg_double_reward') else 1
        first = self.gate(key).get('done', 0) == 0         # first completion: Epsilon LF-4, Zeta Havoc, Kronos Spartan guaranteed (forum)
        rm =reward_msgs or (lambda tot, **kw: self.m.money_msgs() if self.m else [])
        self.p.ach('gate', type='%s_GATE' % key.upper(), dispatch=dispatch)      # the client's GalaxyGateType (STREUNER_GATE ...)
        if CAL.is_active('battle_for_influence') and not dispatch:          # Battle for Influence: the points of a gate victory (official forum 131012)
            self.p.ach('influence', points=CAL.EVENTS['battle_for_influence']['influence'].get(key, 0))
        ev_msgs = []
        if not dispatch and self.m:                                         # event points (Hatching Out: Alpha/Beta/Gamma 160 VPP)
            import event_points as OP
            ev_msgs = OP.gate(self.p, key, lambda l, n: self.m.prize(l, n, 'gate'))
        cbs = self.p.cbs_mods() if not dispatch and getattr(self.p, 'cbs_mods', None) else {}
        ep = int(R['ep'] * x2 * multiplier * (1 + (0 if dispatch else self.p.mods().get('gate_ep', 0)) + cbs.get('ep', 0)))
        honor = int(R['honor'] * x2 * multiplier * (1 + cbs.get('honor', 0)))
        ep, honor, uri = SET.amount('ep', ep, 'gate'), SET.amount('honor', honor, 'gate'), SET.amount('uridium', int(R['uridium'] * multiplier), 'gate')   # panel
        tot = self.p.gain(ep=ep, honor=honor, uridium=uri, reason='galaxy_gate_done')
        msgs = rm(tot, ep=ep, honor=honor, uridium=uri) + ev_msgs
        pet = getattr(self.m, 'pet', None) if self.m else None
        msgs += (pet.gain_xp(ep) or []) if pet and not dispatch else []      # forum 127074: the P.E.T. also earns 5% of the gate EP
        q = lambda v: SET.amount('mode_reward', int(round(v * multiplier)), 'gate')      # panel: gate/mode reward multiplier; Dispatch Day x1.5
        grants = {k: q(v * (1 if k == 'ammunition_laser_ucb-100' else x2)) for k, v in R['ammunition'].items()}
        grants.update(xenomit=q(R['xenomit'] * x2), voucher=q(R['voucher'] * x2), log_disk=q(R['log_disk'] * x2), energy=q(R['energy'] * x2),
                      booty={k: q(v * (x2 if k == 'green_key' else 1)) for k, v in (R['booty'] or {}).items()})
        if not dispatch and key in K.get('schism', {}) and 'AllGatesSchism' in CAL.ALWAYS:   # Booty Day Schism on top of the fixed amount (forum 160341)
            grants['booty']['schism'] = grants['booty'].get('schism', 0) + q(random.randint(*K['schism'][key]))
        msgs += self.give(grants)
        for loot, n in R.get('items', []) if self.m else []:      # Delta 450 Promerium (forum, in-game window)
            msgs += self.m.prize(loot, q(n * x2), 'gate')
        got = []
        owned = {x['lootId'] for x in self.p.d['ships'].values()}
        rows = [s for s in R['chance'] if not (x2 > 1 and s.get('no_double_reward'))]        # Hermes does not drop on a double day
        single = [s for s in rows if s.get('single_spin')]                                   # Kappa: a single spin (LF-4 / Hercules / MultiBooster)
        r, pick = random.random(), None
        for s in single:
            r -= SET.chance('drop', s['probability'], 'gate')
            if r < 0:
                pick = s
                break
        hit = [s for s in rows if s is pick or not s.get('single_spin') and (
            first and s.get('first_guaranteed') or random.random() < SET.chance('drop', s['probability'], 'gate'))]
        for s in hit:
            factor = 1 if s['item'].startswith('ship_') or s['item'] == 'design_choice' else x2   # ship and ship design 1; the others x2
            if s['item'] == 'ore_pack':                 # forum 129125: Kyhalon 5% / Tetrathrin 25% / Bifenon 70%, count x2 on a double day
                u = random.random() * sum(r[2] for r in s['package'])
                l, n, _ = next((r for r in s['package'] if (u := u - r[2]) < 0), s['package'][-1])
                msgs += self.m.prize(l, factor * random.randint(*n), 'gate') if self.m else []
                got.append(l)
                continue
            loot = random.choice(s['options']) if s['item'] == 'design_choice' else s['item']
            got.append(loot)
            if loot in owned and s.get('fallback_uridium'):                # Kuiper: 10,000 uridium if the design is already owned (wiki)
                u = SET.amount('uridium', s['fallback_uridium'], 'gate')
                tot = self.p.gain(uridium=u, reason='galaxy_gate_done')
                msgs += rm(tot, uridium=u)
            elif self.m:
                for l, n in [(loot, [s['count'], s['max_count']] if s.get('max_count') else s['count'])] + (
                        [random.choice(s['together'])] if s.get('together') else []):
                    msgs += self.m.prize(l, factor * (random.randint(*n) if isinstance(n, list) else n), 'gate')     # ranged amount; together: Diametrion + one of the three
                    if l != loot:
                        got.append(l)
        for loot, n, chance in [] if dispatch else CAL.gate_rewards(key):    # the event's gate reward (Empyrian / Prosperous Fragment, Lucent Key)
            if random.random() < SET.chance('drop', chance, 'gate') and self.m:
                msgs += self.m.prize(loot, n, 'gate')
                got.append(loot)
        for s in [] if dispatch else CAL.gate_choices(key):    # GG Special Rewards Weekend, LF-4 day: one of the packages with a probability
            rows = [r for r in s['choice'] if not (s.get('non_repeating') and LOOT.gone(self.p, r))]       # an owned ship, a design, or a package all of whose parts are owned
            if s.get('fallback_uridium'):                       # Astral Exploration: drawn from all of them, uridium if an owned one comes up (forum 162019)
                rows = s['choice']
            if rows and random.random() < SET.chance('drop', s['probability'], 'gate') and self.m:
                row = random.choices(rows, [r[2] if len(r) > 2 else 1 for r in rows])[0]               # equal if there are no weights (Empyrian Reward Package)
                if s.get('fallback_uridium') and LOOT.gone(self.p, row):
                    msgs += self.m.prize('currency_uridium', s['fallback_uridium'], 'gate')
                    got.append('currency_uridium')
                    continue
                for loot, n in row[1] if row[0] == LOOT.PACKAGE else [row[:2]]:      # ['package', [[lootId, count], …]]: all of the items (Collector's Joy 10+1)
                    msgs += self.m.prize(loot, n, 'gate')
                    got.append(loot)
        for s in [] if dispatch else CAL.gate_bundles(key):    # Prosperous Package: the package with a probability, its items with their own probabilities; achievement
            if random.random() < SET.chance('drop', s['probability'], 'gate'):
                for loot, n, chance in s['items']:
                    if random.random() < chance and self.m:
                        msgs += self.m.prize(loot, n, 'gate')
                        got.append(loot)
                self.p.ach('package', package=s['package'])
        with self.p.lock:
            if dispatch and self.gate(key).pop('dispatched', False):
                new = self.gate(key)                 # used up when it was sent (dispatch.send_gate): the parts gathered since then stay
                bucket = self.parts(key)
            else:
                new = fresh(g, self.gate(key))
                bucket = new['parts']
                self.d['gates'][key] = new
            new['done'] = new.get('done', 0) + 1
            bucket[:] = sorted(set(bucket) | set(random.sample(range(1, g['part'] + 1), min(R['part'], g['part']))))
            self.p.dirty = True
        kronos = self.kronos_part(key, dispatch)
        bm, bonus, ship = self.claim_bonus(key, mark=not dispatch)   # timed gate bonus; one taken via Dispatch does not count as "taken" (forum 160334)
        msgs += bm
        if g.get('title') and self.titles:             # Kappa All-Star, Lambda Boss of Bosses, Hades Emperor of Hades
            msgs += self.titles(g['title'])
        self.log('   %s gate completed: +%d EP, +%d honor, +%d U, %s%s' % (
            g['name'], R['ep'], R['honor'], R['uridium'], grants, ', lucky: %s' % got if got else ''))
        return msgs, dict(new=new, kronos=kronos, chance=got, bonus=bonus, bonus_ship=ship, currency=dict(ep=ep, honor=honor, uridium=uri))

    def dispatch_complete(self, key, multiplier=1):
        """Dispatch's gate dispatch finished: completion rewards and the loot message (DispatchLootMessageCommand); carpan: Dispatch Day."""
        msgs, info = self.finish(key, dispatch=True, multiplier=multiplier)
        P = info['currency']                                   # given (with the panel's multipliers), the same in the message
        loots = [mod('LootModule', lootId=l, amount=n, modifier='') for l, n in
                 (('currency_experience', P['ep']), ('currency_honour', P['honor']), ('currency_uridium', P['uridium'])) if n]
        return msgs + [('DispatchLootMessageCommand', dict(messageType=1, loots=loots))]

    def bonus_energy(self, n):
        with self.p.lock:
            self.d['energy'] += n
            self.p.dirty = True
        return [legacy('0|A|STM|log_msg_gather_extra-energy_s_collected' if n == 1 else
                       '0|A|STM|log_msg_gather_extra-energy_p_collected|%%COUNT%%|%d' % n)]


class Run:
    """Waves on the gate map (from the world loop, under the lock). phase: intro/break (countdown), next (between sub-waves),
    fight, move (wave over: the next wave's and home portals are open), done, void (no gate or on another map), dead."""
    cleared = 0                      # sub-waves cleared in this main wave (the client's counter counts sub-waves)
    # the gate map's alien behaviour (player report 2026-11-04, an experienced player; world.in_view, world.think, alien.flees):
    all_visible = True               # every alien is on the minimap, however far
    ring = 200                       # the chasing aliens keep this one distance: around a pilot standing still they form a circle
    corners = ((0, 0), (1, 1))       # at low HP they flee to the top-left or bottom-right corner, the one nearest the alien (fandom
                                     # Galaxy Gates: "running into one of two corners depending on where you are"); the Devourer does not flee

    def __init__(self, gates, world, key):
        self.k, self.w, self.key = gates, world, key
        self.g = GATES[key]
        self.map = int(world.map_id)
        G = gates.gate(key)
        self.npcs = set()            # this wave's aliens
        self.keep = set()            # persistent aliens (Zeta Devourer): independent of sub-waves
        self.groups = []             # spawned aliens of the wave's groups (the window's counter: cleared_groups)
        self.queue = []              # aliens to spawn: (alien order, its group)
        self.due = 0                 # the next one's spawn time
        self.sub = 0
        self.counted = None          # the last countdown second sent
        self.left = None             # the last reported number of remaining aliens
        self.exposed = False         # it was reported that the persistent alien's protection is gone
        self.boss = ''               # the persistent alien's name (messages)
        self.guarding = False        # shielded boss (Zeta Devourer): while the escort group is alive the boss takes no damage (boss_tick)
        self.next_group = 0          # the time of the next escort group of a boss whose shield dropped
        self.protected = {}            # Delta: protected alien -> the escort in its group (Insta-Shield while alive)
        now = time.time()
        if not G['ready'] or G['hp'] <= 0:
            self.phase, self.t = 'void', now          # no gate: only the exit portal
            world.add_gate(gates.exit_portal(key, self.map))
        elif wave_map(self.g, G['wave']) != self.map:
            # another map's wave (e.g. returned to the old map): that map's portal and the return home
            self.phase, self.t = 'void', now
            world.add_gate(gates.next_portal(key, self.map, wave_map(self.g, G['wave'])))
            world.add_gate(gates.exit_portal(key, self.map, side=True))
        else:
            self.phase, self.t = 'intro', now + pace('intro_wait_sec')
            world.send(self.say('ongoing' if G['wave'] else 'entry'))
            if not G['wave']:                       # time from entering the first wave (in the session; in a multi-map gate across maps too)
                gates.__dict__.setdefault('start', {})[key] = now
        world.log('   %s gate: wave %d/%d, lives %d (%s)' % (self.g['name'], G['wave'] + 1, len(self.g['waves']), G['hp'], self.phase))

    def wave(self):
        G = self.k.gate(self.key)
        return self.g['waves'][min(G['wave'], len(self.g['waves']) - 1)]

    def say(self, event, wild=None, **extra):
        """The event in data/gates.json "mesajlar" -> on-screen messages (big and/or short; wild: the text's other placeholders for "key:")."""
        G = self.k.gate(self.key)
        waves = self.g['waves']
        n = min(G['wave'], len(waves) - 1)
        vals = dict(gate=self.g['name'].replace(' Gate', ''), wave=n + 1, total=len(waves), hp=G['hp'], key=self.key,
                    groups=len(waves[n]['groups']))
        vals.update(extra)
        m = self.messages().get(event, {})
        out = []
        for kind in ('caps', 'short'):
            if kind in m:
                text = m[kind].format(**vals)
                out.append(screen(text, big=kind == 'caps', NAME=self.g['name'], WAVE='%d/%d' % (vals['wave'], vals['total']),
                                  **(wild or {})))
        return out

    def messages(self):
        """On-screen messages (event gates put their own texts on top)."""
        return K['messages']

    def wave_msgs(self):
        return [self.wave_msg()]

    def sub_msgs(self):
        """Sub-wave cleared: the window's wave counter (event gates do not send it)."""
        return [self.wave_msg()]

    def wave_count(self):
        return len(self.g['waves'])

    def countdown(self, now):
        """Countdown before the wave (at gates.json countdown seconds)."""
        left = int(math.ceil(self.t - now))
        if left in K['countdown'] and left != self.counted:
            self.counted = left
            self.w.send(self.say('countdown', sec=left))

    def wave_msg(self):
        """The wave counter in sub-wave units (client "Wave: {0} / {1}", total GetGateTotalWaves; in Hades the stage is a quarter of it)."""
        G = self.k.gate(self.key)
        return ('GalaxyGateBuilderGateWaveUpdateCommand', dict(gateId=self.g['uid'],
                                                               currWave=sub_waves(self.g, G['wave']) + self.cleared))

    def pending(self, group):
        """Does the group have an alien that has not spawned."""
        return any(g is group for _, g in self.queue)

    def cleared_groups(self):
        """The window's wave counter: the share of groups all of whose aliens have spawned and died (group_weights)."""
        w = self.w
        return sum(n for group, n in zip(self.groups, group_weights(self.wave()))
                   if not self.pending(group) and not any(i in w.npcs for i in group))

    def trickle(self, now):
        """The next alien: if its time has come it spawns away from the player (far_spot); the next one spawn_interval_sec later (with the panel's wave_wait
        multiplier)."""
        if not self.queue or now < self.due:
            return
        i, group = self.queue.pop(0)
        self.due = now + random.uniform(*K['spawn_interval_sec']) * SET.multiplier('wave_wait')
        w = self.w
        # Kuiper IV's Streuner Turrets (speed 0) spawned 1,500-2,000 away out of sight and never came: the wave never ended and no portal
        # appeared (player report 2026-11-02); a stationary alien spawns in sight
        still = self.wave()['alien_spawns'][i].get('speed', 1) == 0
        self.spawn_one(i, group, *far_spot(*w.hero_pos(), w.map_w, w.map_h, STATIONARY_DISTANCE if still else None))

    def tick(self, now):
        w, G = self.w, self.k.gate(self.key)
        if w.hero_dead or w.jumping or self.phase in ('void', 'done', 'dead', 'move'):
            return
        if self.phase == 'fight':
            if self.boss_wave():
                self.boss_tick(now)
                return
            for nid, guarded in list(self.protected.items()):  # the protected one's escort is over: the Insta-Shield drops
                if not guarded():
                    del self.protected[nid]
                    if nid in w.npcs:
                        w.send(self.shield(w.npcs[nid], False))
            self.trickle(now)
            alive = sum(1 for i in self.npcs - self.keep if i in w.npcs)
            cleared = self.cleared_groups()
            if cleared != self.cleared:
                self.cleared = cleared
                w.send(self.sub_msgs())
            if self.queue or alive:
                # also when only stationary aliens are left, however many (they don't come to the player: Kuiper IV's 4 turrets)
                if not self.queue and alive != self.left and (alive <= 3 or all(
                        w.npcs[i].d.get('speed', 1) == 0 for i in self.npcs - self.keep if i in w.npcs)):
                    self.left = alive
                    w.send(self.say('wave_remaining', remaining=alive))
                return
            boss = [w.npcs[i] for i in self.keep if i in w.npcs]
            if boss:
                if not self.exposed:              # the others are over: the persistent alien now takes damage
                    self.exposed = True
                    w.send(self.say('protection_ended', name=self.boss))
                return
            self.wave_done(now)
            return
        if now < self.t:
            if self.phase in ('intro', 'break'):
                self.countdown(now)
            return
        if self.phase in ('intro', 'break'):
            self.sub, self.counted, self.exposed, self.cleared, self.groups = 0, None, False, 0, []
            self.guarding, self.next_group, self.protected, self.queue, self.due = False, 0, {}, [], 0
            self.npcs.clear()
            self.keep.clear()
            w.remove_gate(self.k.exit_portal(self.key, self.map)['gateId'])
            # end of the countdown, lives left (the client's lifes_left "%! lives left"), the wave's name (the user's real game footage)
            msgs = (self.wave_msgs() + [legacy('0|A|STM|atk_wave_started|%%COUNT%%|%d' % (G['wave'] + 1))] + self.say('countdown', sec=0)
                    + [stm('lifes_left', '%!', G['hp'])] + self.say('wave_started'))
            if G['wave'] == self.wave_count() - 1:
                msgs += self.say('last_wave')
            w.send(msgs)
            w.log('   %s gate: wave %s started' % (self.g['name'], self.wave()['name']))
        self.spawn()
        self.trickle(now)                                            # the first one at once
        if self.phase == 'fight' and G['wave'] == self.wave_count() - 1 and self.sub == 0 and not getattr(self, 'filmed', False):
            self.filmed = True                                       # last wave: camera on the boss (Ö2 cinematic entrance)
            boss = next((w.npcs[i] for i in list(self.keep) + list(self.npcs) if i in w.npcs), None)
            if boss:
                w.cinematic(*boss.mover.pos(time.time()))
        self.left = None
        self.phase = 'fight'

    def counts(self, wave, grp):
        """The group's [alien, count]s: with the panel's wave_aliens multiplier (the persistent boss is one); in Kronos Evil Iris equals the player's Iris drone
        count (wikiwiki.jp Kronos Gate; the wiki's 8 if there is no drone)."""
        out = []
        for i, count in grp:
            a = wave['alien_spawns'][i]
            if a['name'] == 'Evil Iris':
                iris = sum(1 for d in self.k.p.d.get('drones', []) if d.get('lootId') == 'drone_iris')
                count = min(iris, count) if iris else count
            if not a.get('permanent'):
                count = SET.count('wave_aliens', count)
            out.append((i, count))
        return out

    def spawn(self):
        """Wave started: the aliens of all groups are queued (trickle spawns them one by one); the persistent boss first, the protected one first in a group
        (its escort comes after), species mixed within a group. A wave with a shielded boss (Zeta Devourer) with groups: boss_spawn."""
        if self.boss_wave():
            self.boss_spawn()
            return
        wave = self.wave()
        first, rest = [], []
        for grp in wave['groups']:
            group = set()
            self.groups.append(group)
            order = sorted(((not wave['alien_spawns'][i].get('protected'), (j + 0.5) / n), i)
                           for i, n in self.counts(wave, grp) for j in range(n))
            for _, i in order:
                (first if wave['alien_spawns'][i].get('permanent') else rest).append((i, group))
        self.queue, self.due = first + rest, 0

    def spawn_one(self, i, group, x, y):
        """The next alien spawns at (x, y) and goes after the player. The persistent alien takes no damage until the others have spawned and died; the protected
        (Delta) group's others have an Insta-Shield until they spawn and die (forum 127543); one with a "player" look (Kronos Evil You) comes with the player's
        ship."""
        w, G = self.w, self.k.gate(self.key)
        a = self.wave()['alien_spawns'][i]
        model = self.k.p.ship_look() if a['type'] == 'player' else None
        n = w.spawn_npc_at(npc_type(self.key, G['wave'], i), x, y, model=model, wave=True)
        n.gate, n.hunt = True, True
        self.npcs.add(n.id)
        group.add(n.id)
        if a.get('permanent'):
            self.keep.add(n.id)
            n.invulnerable = lambda: bool(self.queue) or any(j in self.w.npcs for j in self.npcs - self.keep)
            self.boss = a['name']
            w.send(self.say('protection', name=a['name']))
        elif a.get('protected'):
            guarded = lambda nid=n.id: self.pending(group) or any(j in self.w.npcs for j in group if j != nid)
            if guarded():
                n.invulnerable = guarded
                self.protected[n.id] = guarded
                w.send(self.shield(n, True) + self.say('protection', name=a['name']))
        return n

    def boss_spawn(self):
        """The group of a wave with a shielded boss (Zeta Devourer): the boss is around the player at the start of the wave; the escort group spawns around
        the boss (de.fandom Zeta Gate: Devourer "sends"), while the group is alive the boss's Insta-Shield is on (user report
        2026-10-25: groups spawned around the player, the shield was not visible); they stop for ring_wait_sec and then go after the player."""
        w, G = self.w, self.k.gate(self.key)
        wave = self.wave()
        counts = self.counts(wave, wave['groups'][self.sub])
        hold = time.time() + pace('ring_wait_sec')
        group = set()
        self.groups.append(group)
        bosses = [(i, c) for i, c in counts if wave['alien_spawns'][i].get('permanent')]
        escort = [(i, c) for i, c in counts if not wave['alien_spawns'][i].get('permanent')]
        for i, x, y in ring(*w.hero_pos(), bosses, w.map_w, w.map_h) if bosses else []:
            n = w.spawn_npc_at(npc_type(self.key, G['wave'], i), x, y, wave=True)
            n.gate, n.hunt = True, True
            n.next_think = hold
            self.npcs.add(n.id)
            group.add(n.id)
            self.keep.add(n.id)
            n.invulnerable = lambda: self.guarding
            n.hp_floor, n.at_floor = self.boss_floor(n), self.boss_at_floor
            self.boss = wave['alien_spawns'][i]['name']
        boss = self.boss_npc()
        cx, cy = boss.mover.pos(time.time()) if boss else w.hero_pos()
        for i, x, y in ring(cx, cy, escort, w.map_w, w.map_h, radius=K['shield_spawn']):
            n = w.spawn_npc_at(npc_type(self.key, G['wave'], i), x, y, wave=True)
            n.gate, n.hunt = True, True
            n.next_think = hold
            self.npcs.add(n.id)
            group.add(n.id)
        if boss and escort:
            self.guarding = True
            w.send(self.shield(boss, True) + self.say('protection', name=self.boss))

    # ------------------------------------------------------------ shielded boss (Zeta Devourer)
    def boss_wave(self):
        """Is the wave one with a shielded boss: the gate has shield_gap_sec (Zeta) and the wave has a persistent alien (Devourer)."""
        return 'shield_gap_sec' in self.g and any(a.get('permanent') for a in self.wave()['alien_spawns'])

    def boss_npc(self):
        return next((self.w.npcs[i] for i in self.keep if i in self.w.npcs and self.w.npcs[i].alive), None)

    def boss_floor(self, b):
        """The boss's HP floor until the next group: its share of the groups still to come (0 after the last one). Without it the Devourer was
        killed in the first 10 s gap with 1 of 7 groups out and the gate ended (player report 2026-11-02)."""
        total = len(self.wave()['groups'])
        left = total - 1 - self.sub
        return int(b.d['hp'] * left / total) if self.boss_wave() and left > 0 else 0

    def boss_at_floor(self, b):
        """In the gap the boss reached the next group's threshold (world.hit_npc): the shield returns and the next group comes at once."""
        if self.next_group:
            self.next_group = min(self.next_group, time.time())

    def shield(self, n, on):
        """The boss's Insta-Shield visual (VisualModifierCommand INVINCIBILITY: the client's NPC shield, game.xml invincibilityShield;
        DarkBot EntityEffect NPC_ISH 16). If not in sight it arrives with ShipCreateCommand (world.npc_visual)."""
        msg = self.w.npc_visual(n, VM_SHIELD, on)
        return [msg] if n.id in self.w.visible else []

    def boss_tick(self, now):
        """A wave with a shielded boss (fandom Galaxy Gates, Zeta): while the escort group is alive the boss takes no damage; when the group ends the shield
        drops for shield_gap_sec, then the shield turns on again and the next group spawns around the boss; after the last group the shield is always off.
        When the boss dies the wave (the gate on the last wave) ends immediately, groups that have not come do not come (user report 2026-10-25: when the Devourer
        died early the waves went on without it; the shield was off for the 3 s between groups)."""
        w = self.w
        boss = self.boss_npc()
        if not boss:
            self.guarding = False
            w.log('   %s gate: %s destroyed (group %d/%d)' % (self.g['name'], self.boss, self.sub + 1, len(self.wave()['groups'])))
            self.wave_done(now)
            return
        alive = sum(1 for i in self.npcs - self.keep if i in w.npcs)
        if self.guarding:
            if alive:
                if alive <= 3 and alive != self.left:
                    self.left = alive
                    w.send(self.say('remaining', remaining=alive))
                return
            self.guarding = False
            self.cleared = sum(group_weights(self.wave())[:self.sub + 1])
            more = self.sub + 1 < len(self.wave()['groups'])
            sec = int(round(self.g['shield_gap_sec'] * SET.multiplier('wave_wait')))
            self.next_group = now + sec if more else 0
            w.send(self.sub_msgs() + self.shield(boss, False) + (self.say('shield_gap', name=self.boss, sec=sec) if more
                                                                  else self.say('protection_ended', name=self.boss)))
            return
        if self.next_group and now >= self.next_group:
            self.sub += 1
            self.next_group, self.left = 0, None
            boss.hp_floor = self.boss_floor(boss)
            self.spawn()

    def wave_done(self, now):
        G = self.k.gate(self.key)
        label = self.wave()['name']
        with self.k.p.lock:
            G['wave'] += 1
            self.k.p.dirty = True
        self.cleared = 0
        self.npcs.clear()
        self.keep.clear()
        if G['wave'] >= len(self.g['waves']):
            self.complete()
            return
        # two portals in the middle: the left one to the next wave (in a multi-map gate to the next map), the right one home; the next wave starts when the player
        # enters the portal (official gate guide; user report 2026-10-24: only the return-home portal opened, the wave started by itself
        # when the break ended)
        nxt = wave_map(self.g, G['wave'])
        self.w.add_gate(self.k.next_portal(self.key, self.map, nxt))
        self.w.add_gate(self.k.exit_portal(self.key, self.map, side=True))
        self.w.send([self.wave_msg()] + self.say('next_map' if nxt != self.map else 'next_wave', wave=G['wave']))
        self.phase = 'move'                 # after the messages (so it also sees the messages waiting for the stage)
        self.w.log('   %s gate: wave %s over; portals open (next %s)' % (self.g['name'], label, nxt))

    def complete(self):
        """Last wave: rewards (Kapilar.finish), exit portal, on-screen messages."""
        k, w = self.k, self.w
        t0 = k.__dict__.get('start', {}).pop(self.key, None)
        if t0:
            with k.p.lock:
                record_duration(k.p.d, self.key, time.time() - t0)
                k.p.dirty = True
        msgs, info = k.finish(self.key, w.reward_msgs)
        out = k.exit_portal(self.key, self.map)
        w.add_gate(out)
        w.auto_jump(out, K.get('exit_wait_sec', 5))      # forum 127543: to X-1 by itself after the rewards
        msgs += [('GalaxyGateBuilderGateCompleteCommand', dict(gateId=self.g['uid'], currPart=len(info['new']['parts'])))]
        msgs += self.say('wave_finished', wave=len(self.g['waves']), sec=0)[:1] + self.say('done')
        if info['kronos']:
            got, total = info['kronos']
            msgs += self.say('kronos_part', sk='s' if got == 1 else 'p', wild=dict(COUNT=got))
            if total >= KRONOS_PARTS:                    # last part: the client's "Kronos Gate erected."
                msgs.append(screen('key:log_msg_gg_build_complete_kronos'))
        w.send(msgs)
        self.phase = 'done'

    def on_death(self):
        """The player was hit at the gate: loses 1 life; with none left the gate is lost with its parts. -> lives left."""
        if self.phase in ('void', 'done'):
            return None
        k, G = self.k, self.k.gate(self.key)
        with k.p.lock:
            if not SET.get('infinite_lives'):                    # panel: no lives are spent at the gate
                G['hp'] = max(0, G['hp'] - 1)
            left = G['hp']
            if left <= 0:
                k.d['gates'][self.key] = fresh(self.g, G)
            k.p.dirty = True
        self.w.send([('GalaxyGateBuilderGateLifeLostCommand', dict(gateId=self.g['uid'], livesLeft=left))])
        self.w.log('   %s gate life lost: %d left%s' % (self.g['name'], left, ' (gate lost)' if left <= 0 else ''))
        self.before_death = self.phase
        self.phase = 'void' if left <= 0 else 'dead'      # the map changes with a repair at base; on re-entering the gate the wave starts over
        return left

    def revive(self):
        """Hades: respawned on the gate map; the wave continues where it left off."""
        if self.phase == 'dead':
            self.phase = getattr(self, 'before_death', 'fight')
            self.w.log('   %s gate respawned: %s' % (self.g['name'], self.phase))
