"""Astral Ascension (roadmap Stage 8; the client's RogueLite* commands; data data/pve_modes.json "astral").

Flow: the Astral CPU (from the shortcut bar) opens the gate in X-1 (portal 86, stays until the run ends). Jumping into the gate brings up the rented ship choice
(RogueLiteSelectShipCommand: Sentinel, Diminisher, Pusat, Zephyr with the same starting loadout) -> RogueLiteSelectShipRequest
{loadoutId}: the run starts. 15 rifts (466-468 in turn): each rift has three waves (5 and 10 mid-bosses, 15 final boss, a single wave); aliens
grow stronger as the rifts advance, and give no rewards (EP, honor, credits, uridium, cargo). When a rift ends, two reward gates (type random: weapon,
generator, ammo, booster, module, resource, HP; the frenzied version has stronger aliens and better rewards, 350 points) and the exit portal.
The chosen gate determines the next rift's type; when that rift ends the reward: for weapon/generator/module/booster one of three
(RogueLiteSelectRewardCommand -> RogueLiteSelectRewardRequest {lootId}; fitted if there is an empty slot, otherwise to the run's inventory),
ammo random, resource Atlas Shard (to the account at the end), HP 50%. After a mid-boss HP refills 50%.
Rented equipment: for the run a temporary ship (added to ships), drones (5 Iris, two LF-3 each) and ammo replace the player's;
on returning to X-1 through the exit portal the player's own come back, and re-entering through the gate brings back the rented ones (the run
continues where it was). The run ends on death or with the final boss: everything rented is deleted, the reward of the rift reached (Astralite; by chance Salvage Core
and Astral Booty Key) and the collected Atlas Shards are given. Points: rift 300 (frenzied 350), mid-boss 400, final boss 450, HP left in the
boss fight (3 per 1%, at most 300) and time (450 - 0.25 x sec); the ranking is the total of the best 3 runs (single player: only the
player).
In the profile: pve.astral {gate, run {ship, shipId, sid, rift, type, frenzied, points, atlas, inventory, items, inside, rented, backup}, runs [points]}.
"""
import json, math, os, random, time

import settings as SET
import galaxy_gates as GALAXY
import rankings as RK
import monthly_rankings as MR
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8'))['astral']
PORTAL = 154900000                 # the gate in X-1; + 10 + i reward gates; + 50 exit
PICK = ('weapon', 'generator', 'module', 'booster')
SALVAGE_CHANCE, KEY_CHANCE = 1.0, 0.5          # at the end of a rift: Salvage Core every time (official forum); the key is an adaptation


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Astral:
    key, name = 'astral', 'Astral Ascension'

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.send = None               # message to the session

    @property
    def pending(self):
        """Rewards awaiting a choice [lootId, level/count]; kept in the run so a relogin does not forfeit them."""
        r = self.run
        return r.get('pending') if r else None

    @pending.setter
    def pending(self, picks):
        r = self.run
        if r is None:
            return
        with self.p.lock:
            if picks is None:
                r.pop('pending', None)
            else:
                r['pending'] = picks
            self.p.dirty = True

    @property
    def st(self):
        return self.p.d.setdefault('pve', {}).setdefault('astral', {})

    @property
    def run(self):
        return self.st.get('run')

    # ------------------------------------------------------------ CPU and gate
    def use_cpu(self, map_id):
        """Astral CPU: opens the gate in X-1 -> messages or None (cannot be used)."""
        import map_links as H
        if H.map_class(map_id) != D['entry'] or self.st.get('gate') or self.run:
            return None
        if self.p.use_ammo(D['cpu']) is None:
            return None
        with self.p.lock:
            self.st['gate'] = True
            self.p.dirty = True
        self.log('   Astral CPU used: gate in X-1')
        return [GALAXY.screen('The Astral Ascension gate has opened in the center of the map.', big=True), self.cpu_cmd()]

    def portals(self, map_id):
        import map_links as H
        if H.map_class(map_id) != D['entry'] or not (self.st.get('gate') or self.run):
            return []
        w, h = H.map_size(map_id)
        return [dict(gateId=PORTAL, x=w // 2, y=h // 2 + 1200, target=0, designId=D['portal'], gate='astral', windowed='astral')]

    def cpu_cmd(self):
        return ('RogueLiteCpuInfoCommand', dict(keys=int(self.p.resource('resource_booty-key-astral')), showCpu=True))

    # ------------------------------------------------------------ ship choice
    def item_mod(self, loot, lvl=0, n=1, iid=0):
        return mod('InventoryItemModule', upgradeLevel=lvl, lootId=loot, amount=n, itemId=iid, star=0, isNew=False, hangarId=0,
                   extAttributes=[], inventoryItemAttributes=[])

    def ship_list(self):
        from shop import ITEMS
        y, out = D['loadout'], []
        dr = y['drones']
        drones = [mod('RogueLiteDroneModule', lootId=dr['type'], level=6, equipments=[self.item_mod(dr['laser'], 0)] * dr['per_drone'])
                  for _ in range(dr['count'])]
        eq = [self.item_mod(l, lvl - 1, n) for slot in ('laser', 'generators', 'extra') for l, n, lvl in y[slot]]
        for s in D['ships']:
            row = ITEMS['ships'].get(s['lootId'], {})
            out.append(mod('RogueLiteShipModule', petEquipments=[], speed=row.get('base_speed', 300), drones=drones, lootId=s['lootId'],
                           loadOutId=s['loadout'], hp=row.get('hp', 0), shipId=s['shipId'], shield=0, equipments=eq, spread=0))
        return ('RogueLiteSelectShipCommand', dict(modifierList=[], shipList=out))

    def gate_jump(self):
        """Jumped to the gate in X-1: if there is no run the ship choice, otherwise back to its rift -> (target map or None, messages)."""
        if not self.run:
            return None, [self.ship_list()]
        self.swap_in()
        return self.rift_map(), []

    def select_ship(self, f):
        """RogueLiteSelectShipRequest {loadoutId} -> target map or None."""
        ship = next((s for s in D['ships'] if s['loadout'] == f.get('loadoutId')), None)
        if not ship or self.run or not self.st.get('gate'):
            return None
        self.loan(ship)
        return self.rift_map()

    # ------------------------------------------------------------ rented equipment
    def loan(self, ship):
        """Rented ship, items, drones and ammo; the run record."""
        p, y = self.p, D['loadout']
        sid = str(p.add_ship(ship['lootId']))
        cfg = p.d['ships'][sid]['configs']['1']
        lv = p.d.setdefault('upgrade_level', {})
        items = []
        for slot in ('laser', 'generators', 'extra'):
            for loot, n, level in y[slot]:
                for _ in range(n):
                    iid = p.new_item(loot)
                    lv[str(iid)] = level - 1
                    cfg.setdefault(slot, []).append(iid)
                    items.append(iid)
        dr = y['drones']
        drones, dcfg = [], p.d['ships'][sid].setdefault('drone_config', {}).setdefault('1', {})
        for k in range(dr['count']):
            did = 990000 + k
            drones.append({'uid': did, 'lootId': dr['type'], 'level': 6, 'points': 0, 'upgrade': 1})
            ids = [p.new_item(dr['laser']) for _ in range(dr['per_drone'])]
            dcfg[str(did)] = ids
            items += ids
        with p.lock:
            p.d['ships'][sid]['on_loan'] = True
            self.st['run'] = dict(ship=ship['lootId'], shipId=ship['shipId'], sid=sid, rift=1, type=None, frenzied=False, points=0, atlas=0,
                                   inventory=[], items=items, inside=False, start=time.time(),
                                   rented=dict(drones=drones, ammunition=dict(y['ammunition']), selected=None))
            self.st['gate'] = False
            p.dirty = True
        self.log('   Astral: run started (%s)' % ship['name'])
        self.swap_in()

    def swap_in(self):
        """Rented equipment active (the player's is stored during the run)."""
        r, p = self.run, self.p
        if not r or r['inside']:
            return
        k = r['rented']
        with p.lock:
            r['backup'] = dict(active=p.d['active_ship'], drones=p.d['drones'], ammunition=p.d['ammunition'], selected=dict(p.d.get('selected', {})))
            p.d['drones'], p.d['ammunition'] = k['drones'], k['ammunition']
            if k.get('selected'):
                p.d['selected'] = k['selected']
            else:
                p.d['selected'] = {'laser': 'ammunition_laser_lcb-10', 'rocket': 'ammunition_rocket_r-310'}
            r['inside'] = True
            p.dirty = True
        self.m.activate({'shipId': r['sid']})
        self.log('   Astral: rented equipment active')

    def swap_out(self):
        """The player's equipment back (the rented ones are stored in the run)."""
        r, p = self.run, self.p
        if not r or not r['inside']:
            return
        y = r['backup']
        with p.lock:
            r['rented'].update(drones=p.d['drones'], ammunition=p.d['ammunition'], selected=dict(p.d.get('selected', {})))
            p.d['drones'], p.d['ammunition'], p.d['selected'] = y['drones'], y['ammunition'], y['selected']
            r['inside'] = False
            p.dirty = True
        self.m.activate({'shipId': y['active']})
        self.log('   Astral: player equipment restored')

    def end_run(self, reached, final=False):
        """The run ended: everything rented is deleted, rewards are given -> messages."""
        r, p = self.run, self.p
        self.swap_out()
        with p.lock:
            sh = p.d['ships'].pop(r['sid'], None)
            for iid in r['items'] + r['inventory']:
                p.d['items'].pop(str(iid), None)
                p.d.get('upgrade_level', {}).pop(str(iid), None)
            self.st['run'] = None
            runs = self.st.setdefault('runs', [])
            runs.append(int(r['points']))
            self.st['runs'] = sorted(runs, reverse=True)[:20]
        MR.record(p, 'astral', int(r['points']))                     # the month's ranking (monthly_rankings.py)
        with p.lock:
            p.dirty = True
        row = next((x for x in D['reward'] if x['min_value'] <= reached <= x['max_count']), D['reward'][0])
        msgs, got = [], []
        give = [('resource_collectable_astralite', row['astralite'])]
        if random.random() < SET.chance('drop', SALVAGE_CHANCE, 'mod'):     # panel: drop chance
            give.append(('resource_collectable_salvage-core', row['salvage']))
        keys = sum(1 for _ in range(row['key']) if random.random() < SET.chance('drop', KEY_CHANCE, 'mod'))
        if keys:
            give.append(('resource_booty-key-astral', keys))
        if r['atlas']:
            give.append(('resource_collectable_atlas-shard', r['atlas']))
        for loot, n in give:
            msgs += self.m.prize(loot, n)
            got.append('%s x%d' % (loot, n))
            if loot == 'resource_collectable_astralite':
                p.ach('loot', loot=loot, amount=n)                  # Astral Ascension Pass: "collect Astralite" (battle_pass.py)
        self.log('   Astral ended: rift %d, points %d; %s' % (reached, r['points'], ', '.join(got)))
        msgs.append(GALAXY.screen('Astral Ascension ended at rift %d. Score: %d' % (min(reached, 15), r['points']), big=True))
        return msgs + [self.info_cmd(), self.rank_cmd()]

    # ------------------------------------------------------------ rift
    def rift_map(self):
        return D['maps'][(self.run['rift'] - 1) % len(D['maps'])]

    def rift(self):
        return D['rifts'][self.run['rift'] - 1]

    def waves(self):
        sets = self.rift()['sets']
        return sets[1 if self.run['frenzied'] and len(sets) > 1 else 0]      # the source's two example runs: normal and frenzied

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        r, o, rf = self.run, D['scale'], self.rift()
        k = r['rift'] - 1
        hp = (1 + o['rift_hp'] * k) * (o['frenzied_hp'] if r['frenzied'] else 1)
        dmg = (1 + o['rift_damage'] * k) * (o['frenzied_damage'] if r['frenzied'] else 1)
        if rf['boss']:
            hp *= o['boss_hp'][rf['name']]
            dmg *= o['boss_damage'][rf['name']]
        return PS.scale_npc(n, hp, dmg, 0)          # in Astral aliens give no EP/honor/credits/uridium/cargo

    def attach(self, world):
        self.world = world
        r = self.run
        if not r:
            world.add_gate(self.exit_portal(world))
            return None
        self.swap_in()
        r['wave_start'] = None
        if r.get('cleared'):                         # rift cleared, waiting for a gate choice (left and came back)
            world.gate = PS.Run(world, self)
            world.gate.phase = 'hold'                  # no waves; death still ends the run
            world.send([self.info_cmd(), self.inventory_cmd()])
            if self.pending:
                world.send([('RogueLiteSelectRewardCommand', dict(content=[self.item_mod(l, n - 1) for l, n in self.pending], module=[]))])
            else:
                self.open_gates()
            return world.gate
        world.gate = PS.Run(world, self, break_sec=3)
        world.send([self.info_cmd(), self.inventory_cmd()])
        return world.gate

    def wave_started(self, i):
        r = self.run                                     # the client's text: "%NAME% - Rift %RIFT% Wave %WAVE%"
        self.world.send([GALAXY.screen('key:log_astralascension_wave_name', big=True, RIFT=r['rift'], WAVE=i + 1,
                                 NAME='Astral Ascension' + (' (Frenzied)' if r['frenzied'] else ''))])
        if self.rift()['boss']:
            self.run['wave_start'] = time.time()

    def wave_done(self, i, now):
        if i + 1 < self.wave_count():
            return 'ongoing'
        self.rift_done(now)
        return 'halt'

    def rift_done(self, now):
        r, w, rf = self.run, self.world, self.rift()
        S = D['points']
        pts = S['per_frenzied_rift_cleared'] if r['frenzied'] else S['per_rift_cleared']
        if rf['boss']:
            g = self.p.d['ship']
            pct = 100.0 * g.get('hitPoints', 0) / max(1, g.get('hitMax', 1))
            t = now - (r.get('wave_start') or now)
            pts += (S['final_boss_defeated'] if r['rift'] == 15 else S['mini_boss_defeated'])
            pts += min(300, int(3 * pct)) + int(max(0, min(450, 450 - 0.25 * t)))
        with self.p.lock:
            r['points'] += pts
            r['cleared'] = True
            self.p.dirty = True
        msgs = [GALAXY.screen('Rift %d cleared! +%d points' % (r['rift'], pts), big=True)]
        self.log('   Astral rift %d ended: +%d points (%d)' % (r['rift'], pts, r['points']))
        if r['rift'] >= len(D['rifts']):
            w.send(msgs + self.end_run(16, final=True))
            w.add_gate(self.exit_portal(w))
            return
        if rf['boss']:
            msgs += self.heal(0.5)
        msgs += self.bounty()
        w.send(msgs + [self.score_cmd()])
        if not self.pending:
            self.open_gates()

    def heal(self, f):
        g = self.p.d['ship']
        hp = min(g.get('hitMax', 0), int(g.get('hitPoints', 0) + g.get('hitMax', 0) * f))
        self.p.set_hull(hp=hp)
        return [('HitpointInfoCommand', dict(hitpoints=int(hp), hitpointsMax=g['hitMax'], nanoHull=int(g.get('nanoHull', 0)),
                                              nanoHullMax=g.get('maxNanoHull', 0)))]

    def bounty(self):
        """This rift's (the chosen gate's) reward."""
        r = self.run
        t = r.get('type')
        if not t:
            return []
        lvl_bonus = 3 if r['frenzied'] else 0
        pool = D['pool'].get(t, [])
        if t == 'hp':
            return self.heal(0.5) + [GALAXY.screen('50% of your hit points restored.')]
        if t == 'ammunition':
            msgs = []
            for loot, lo, hi in random.sample(pool, 2):
                n = int(random.randint(lo, hi) * (1.5 if r['frenzied'] else 1))
                with self.p.lock:
                    self.p.d['ammunition'][loot] = self.p.d['ammunition'].get(loot, 0) + n
                    self.p.dirty = True
                msgs.append(GALAXY.screen('+%d %s' % (n, loot.rsplit('_', 1)[-1].upper())))
            return msgs
        if t == 'source':
            loot, lo, hi = pool[0]
            n = int(random.randint(lo, hi) * (1.5 if r['frenzied'] else 1))
            r['atlas'] += n
            return [GALAXY.screen('+%d Atlas Shard (booked at the end of the run)' % n)]
        picks = []
        for loot, lo, hi in random.sample(pool, min(3, len(pool))):
            if t == 'booster':
                picks.append([loot, 1])
            else:
                top = min(hi + lvl_bonus, 20)
                lvl = max(lo, min(top, lo + r['rift'] // 2 + random.randint(0, 3) + lvl_bonus))
                picks.append([loot, lvl])
        self.pending = picks
        return [('RogueLiteSelectRewardCommand', dict(
            content=[self.item_mod(l, (n - 1) if t not in ('booster',) else 0, 1 if t != 'booster' else n) for l, n in picks],
            module=[]))]

    def select_reward(self, f):
        """RogueLiteSelectRewardRequest {lootId}: the chosen reward is fitted or goes to the inventory -> messages."""
        pick = next((x for x in (self.pending or []) if x[0] == f.get('lootId')), None)
        if not pick or not self.run:
            return []
        self.pending = None
        loot, lvl = pick
        msgs = []
        if loot.startswith('booster_'):
            msgs += self.m.reward(loot, 1)
        else:
            iid = self.p.new_item(loot)
            self.p.d.setdefault('upgrade_level', {})[str(iid)] = lvl - 1
            self.run['items'].append(iid)
            if not self.equip(iid, loot):
                self.run['inventory'].append(iid)
            msgs += self.m.apply_stats()
        self.log('   Astral reward: %s (level %d)' % (loot, lvl))
        self.open_gates()
        return msgs + [self.inventory_cmd()]

    def equip(self, iid, loot):
        """Fit into an empty slot on the rented ship -> True."""
        from shop import ITEMS, slot_of
        slot = slot_of(loot)
        if not slot:
            return False
        sid = self.run['sid']
        cfg = self.p.config(None, sid)
        cap = {'laser': 'laser', 'generators': 'generators', 'extra': 'extra', 'upgrades': None}
        row = ITEMS['ships'].get(self.run['ship'], {})
        limit = row.get(slot, 0) if slot != 'upgrades' else 3
        if len(cfg.get(slot, [])) >= limit:
            return False
        with self.p.lock:
            cfg.setdefault(slot, []).append(iid)
            self.p.sync_equipment()
            self.p.dirty = True
        return True

    def open_gates(self):
        """Two reward gates (types random; the HP gate has no frenzied version) and the exit."""
        w = self.world
        x, y = w.map_w // 2, w.map_h // 2
        kinds = random.sample(D['gate_kinds'], 2)
        for i, k in enumerate(kinds):
            crazy = bool(k['frenzied']) and random.random() < 0.35
            w.add_gate(dict(gateId=PORTAL + 10 + i, x=x - 1500 + 3000 * i, y=y - 1200, target=0, designId=k['frenzied'] if crazy else k['design'],
                            gate='astral', windowed='astral_reward', type=k['name'], frenzied=crazy))
        w.add_gate(self.exit_portal(w))
        w.send([self.info_cmd(at_gate=True)])

    def exit_portal(self, world):
        home = GALAXY.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)
        return dict(gateId=PORTAL + 50, x=world.map_w // 2, y=world.map_h // 2 + 1500, target=home, designId=1, gate='astral', exit=True,
                    astral_exit=True, arrival='station')

    def choose_gate(self, g):
        """Jumped to a reward gate: the next rift with that type -> target map."""
        r = self.run
        with self.p.lock:
            r.update(rift=r['rift'] + 1, type=g['type'], frenzied=g['frenzied'], cleared=False)
            self.p.dirty = True
        self.log('   Astral: rift %d (%s%s)' % (r['rift'], g['type'], ', frenzied' if g['frenzied'] else ''))
        return self.rift_map()

    def leaving(self):
        """Through the exit portal to X-1: the player's equipment is back, the run continues."""
        self.swap_out()

    def on_death(self):
        """Single life: the run ends."""
        if self.run:
            self.world.send(self.end_run(self.run['rift']))
        return 0

    def revive(self):
        pass

    # ------------------------------------------------------------ display
    def best3(self):
        return sum(self.st.get('runs', [])[:3])

    def cashout_cmd(self):
        r = self.run
        if not r:
            return mod('RogueLiteCashOutCommand', confirmedList=[], chanceUpList=[])
        row = next((x for x in D['reward'] if x['min_value'] <= r['rift'] <= x['max_count']), D['reward'][0])
        duration = [self.item_mod('resource_collectable_astralite', 0, row['astralite'])]
        if r['atlas']:
            duration.append(self.item_mod('resource_collectable_atlas-shard', 0, r['atlas']))
        chance = [self.item_mod('resource_collectable_salvage-core', 0, row['salvage'])]
        if row['key']:
            chance.append(self.item_mod('resource_booty-key-astral', 0, row['key']))
        return mod('RogueLiteCashOutCommand', confirmedList=duration, chanceUpList=chance)

    def info_cmd(self, at_gate=False):
        r = self.run or {}
        return ('RogueLiteInfoCommand', dict(isAtGate=at_gate, cpuInfo=mod('RogueLiteCpuInfoCommand', **self.cpu_cmd()[1]),
                                             shipId=int(r.get('shipId', 0)), score=int(r.get('points', 0)), progress=int(r.get('rift', 0)),
                                             cashoutInfo=self.cashout_cmd(), highscore=int(self.best3())))

    def score_cmd(self):
        r = self.run or {}
        return ('RogueLiteScoreInfoCommand', dict(score=int(r.get('points', 0)), progress=int(r.get('rift', 0))))

    def inventory_cmd(self):
        r = self.run
        if not r:
            return ('RogueLiteInventoryCommand', dict(equipments=[], inventory=[], unstableModules=[]))
        lv = self.p.d.get('upgrade_level', {})
        eq = [i for slot in ('laser', 'generators', 'extra', 'upgrades') for i in self.p.config(None, r['sid']).get(slot, [])]
        it = lambda i: self.item_mod(self.p.d['items'].get(str(i), ''), int(lv.get(str(i), 0)), 1, i)
        return ('RogueLiteInventoryCommand', dict(equipments=[it(i) for i in eq if str(i) in self.p.d['items']],
                                                  inventory=[it(i) for i in r['inventory'] if str(i) in self.p.d['items']],
                                                  unstableModules=[]))

    def change_equipment(self, f):
        """RogueLiteChangeEquipmentRequest {modifiedItemIds}: if fitted, to the inventory; if in the inventory, fit it (if the slot is empty)."""
        r = self.run
        if not r:
            return []
        cfg = self.p.config(None, r['sid'])
        for iid in [int(x) for x in f.get('modifiedItemIds', [])]:
            loot = self.p.d['items'].get(str(iid))
            if not loot or iid not in r['items']:
                continue
            slot = next((s for s, ids in cfg.items() if iid in ids), None)
            if slot:
                with self.p.lock:
                    cfg[slot].remove(iid)
                    r['inventory'].append(iid)
                    self.p.dirty = True
            elif iid in r['inventory'] and self.equip(iid, loot):
                r['inventory'].remove(iid)
        with self.p.lock:
            self.p.sync_equipment()
        return self.m.apply_stats() + [self.inventory_cmd()]

    def rank_cmd(self):
        """Rank tab: the month's ranking (total of the best three runs)."""
        row = lambda r: mod('RankModule', lastUpdateTime=int(time.time() * 1000), name=r[1], rank=r[0], points=int(r[2]))
        top, me = MR.table(self.p, 'astral')                  # the month's ranking with the bot pilots (monthly_rankings.py)
        info = mod('RogueLiteRankInfoCommand', topRankers=[row(r) for r in top], myRank=row(me))
        return ('RogueLiteRankEventInfoCommand', dict(playerRankRanges=RK.ranges(RK.ASTRAL), rankInfoCommand=info,
                                                         isEventEnabled=True))
