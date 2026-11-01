"""LoW (Lord of War), single-player version (roadmap stage 4). Values and sources are in data/low.json.

Map (wiki image, emu-dark): the entry is in the bottom-left corner (map.LOW_START); in the middle the pirate HQ (decorative station map_links.py LOW_STATION;
the boss spawns here; when the first relay activates, a healing zone opens around it); four relay stations at fixed places (role.places), the first
visible from entry, each later one appears when the previous one activates; the red no-fly zones are in the 200 records of map_layout.json.
Flow (from the world loop, under the lock): the route (low.json): old pirates by type wave after wave, at fixed spawn points (spawn_points);
between the waves the relay stations in order (the client's RELAY_STATION asset; wiki: "shoot the station until its green indicator
loads": it fills when hit, the world's asset_targets; as a fallback also when standing next to it; it does not activate while pirates are on the map or
before its turn, the client's text) -> Century Falcon and its escort at the HQ -> done: in the middle a return portal to the company's X-3. Narrative: radio texts
from the HQ (the client's transmission_groupgate_* keys, low.json narration).
Progress is in the profile (low: stage, wave = number of waves spawned, role = number of active relays; the next step in the route derives from these): if after dying
the player returns through the portal on X-3 within return_sec, it continues from the stage reached (the wave's aliens come again), otherwise from the start. In LoW repair
only at the station (X-1); the jump CPU does not work.
"""
import json, math, os, random, time

import map_links as H
import alien as ALN
from legacy_protocol import legacy
from galaxy_gates import mod, screen

HERE = os.path.dirname(os.path.abspath(__file__))
L = json.load(open(os.path.join(HERE, 'data', 'low.json'), encoding='utf8'))
MAP = L['map']
RELAY_STATION = 31                  # AssetTypeModule.AssetType (client)
RELAY_BASE = 152100000
EXIT_ID = H.GATE_ID_BASE + 990010
POI_HQ = 'lowHqHealing'             # HQ healing zone (POIType HEALING = 4, design SIMPLE = 6; same as the world boss's healing beacon)


def fresh():
    return {'stage': 'wave', 'wave': 0, 'role': 0, 'death': None}


class Low:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.npcs = set()           # the aliens of this stage
        self.relay = None           # {uid, x, y, progress, last, percent, defender}
        self.boss = None
        self.heal_next = 0.0
        self.told = set()           # narrated events (low.json narration): each once after entry
        now = time.time()
        st = self.p.d.get('low')
        returning = bool(st and st.get('stage') != 'finished' and st.get('death') and now - st['death'] <= L['return_sec'])
        with self.p.lock:
            self.p.d['low'] = dict(st, death=None) if returning else fresh()
            self.p.dirty = True
        self.t = now + L['entry_sec']
        world.asset_targets = self             # a relay is selected and shot (world.asset_laser)
        self.show_relay()                      # the next relay is visible from entry
        self.w.send(self.asset_msgs())         # set up after Low's ready bundle (resend only carries over when the map is reloaded): live, the first relay was not reaching the client
        self.say('ongoing' if returning else 'entry')
        if not returning:
            self.tell('entry')
        self.w.log('   LoW: %s (%s)' % ('resumed' if returning else 'from the start', self.st['stage']))

    @property
    def st(self):
        return self.p.d['low']

    def save(self, **kw):
        with self.p.lock:
            self.st.update(kw)
            self.p.dirty = True

    def say(self, key, **kw):
        """Flow text: if it has a "key:" prefix, the client's text (Century Falcon, finish), otherwise the sentence from low.json."""
        vals = dict(relays=L['role']['count'], total=len(L['waves']))
        vals.update(kw)
        self.w.send([screen(L['messages'][key].format(**vals))])

    def tell(self, event):
        """The HQ's radio narrative (the client's transmission_groupgate_* texts, low.json narration): once per event."""
        keys = L['narration'].get(event)
        if keys and event not in self.told:
            self.told.add(event)
            self.w.send([legacy('0|A|STM|' + k) for k in keys])

    def hq(self):
        """HQ: the middle of the map (the place of the decorative station)."""
        return self.w.map_w // 2, self.w.map_h // 2

    # ------------------------------------------------------------ spawning
    def spawn(self, tip, count, near=None, at=None):
        """If at is given, right around that point (route spawn point, HQ); otherwise in a ring around near (or the player)."""
        w = self.w
        if at:
            cx, cy = at
        else:
            hx, hy = near or w.hero_pos()
            a, r = random.uniform(0, 2 * math.pi), random.uniform(*L['spawn_distance'])
            cx = min(max(hx + math.cos(a) * r, 800), w.map_w - 800)
            cy = min(max(hy + math.sin(a) * r, 800), w.map_h - 800)
        out = []
        for i in range(count):
            b, d = random.uniform(0, 2 * math.pi), random.uniform(0, 250 + 40 * count)
            n = w.spawn_npc_at(tip, cx + math.cos(b) * d, cy + math.sin(b) * d)
            n.gate, n.engaged, n.hunt, n.next_think = True, True, True, time.time()
            self.npcs.add(n.id)
            out.append(n)
        return out

    def alive(self):
        self.npcs = {i for i in self.npcs if i in self.w.npcs and self.w.npcs[i].alive}
        return self.npcs

    # ------------------------------------------------------------ steps
    def step(self):
        """The next step in the route (low.json route): ('wave', i), ('role', i), ('boss',); None when done. Derived from the counters in the profile."""
        st = self.st
        if st['stage'] == 'finished':
            return None
        for s in L['route']:
            if s[0] == 'boss' or (st['wave'] if s[0] == 'wave' else st['role']) <= s[1]:
                return tuple(s)
        return ('boss',)

    def tick(self, now):
        w = self.w
        self.heal_tick(now)
        if w.hero_dead or w.jumping or now < self.t:
            return
        s = self.step()
        if s is None:
            return
        if s[0] == 'wave':
            if self.alive():
                return
            i = s[1]
            tip, n = L['waves'][i]
            self.spawn(tip, n, at=L['spawn_points'][i])
            self.save(stage='wave', wave=i + 1)
            self.t = now + L['wave_interval_sec']
            self.say('wave', name=w.alien.CFG['types'][tip]['name'].strip('-=[] '), count=n, wave=i + 1)
            w.log('   LoW wave %d: %s x%d' % (i + 1, tip, n))
        elif s[0] == 'role':
            if not (self.relay and self.relay['defender']):
                if self.alive():                             # the relay's defenders do not come before the previous wave ends
                    return
                self.save(stage='role')
                self.place_relay(now)
            self.relay_tick(now)
        elif not self.alive() and self.boss is None:
            self.save(stage='boss')
            self.spawn_boss()
        elif not self.alive():
            self.finish()

    def relay_msg(self):
        r = self.relay
        return ALN.asset_create(r['uid'], RELAY_STATION, r['x'], r['y'], name='Relay Station %d' % (self.st['role'] + 1))

    def show_relay(self):
        """Shows the next relay station at its fixed place (role.places) (its defenders spawn when its turn comes) -> spawn message or None."""
        no = self.st['role'] + 1
        if no > L['role']['count']:
            return None
        x, y = L['role']['places'][no - 1]
        self.relay = dict(uid=RELAY_BASE + no, x=x, y=y, progress=0.0, last=time.time(), percent=-1, defender=False)
        return self.relay_msg()

    def place_relay(self, now):
        """The relay's turn has come: a Vagrant defense spawns next to it (the relay has been visible on the map since entry or since the previous one)."""
        w = self.w
        if not self.relay:
            w.send([self.show_relay()])
        r = self.relay
        r['last'], r['defender'] = now, True
        tip, n = L['role']['savunma']
        self.spawn(tip, n, near=(r['x'], r['y']))
        no = self.st['role'] + 1
        self.say('role', no=no)
        self.tell('relay_%d' % no)
        w.log('   LoW relay station %d: (%d,%d)' % (no, r['x'], r['y']))

    def relay_tick(self, now):
        """Relay (fallback path): progresses while the player is within radius of it and there are no pirates on the map; activates in sn seconds."""
        w, r, cfg = self.w, self.relay, L['role']
        dt, r['last'] = now - r['last'], now
        if self.alive():
            return
        self.tell('relay_%d_ready' % (self.st['role'] + 1))
        hx, hy = w.hero_pos(now)
        if math.hypot(r['x'] - hx, r['y'] - hy) > cfg['radius']:
            return
        r['progress'] += min(dt, 1.0)
        self.relay_step(now)

    def relay_step(self, now):
        """The relay's progress (seconds; a hit counts damage/damage x sn): a percent message, activates when full; the next relay appears."""
        w, r, cfg = self.w, self.relay, L['role']
        pct = min(100, int(100 * r['progress'] / cfg['sn']))
        no = self.st['role'] + 1
        if pct // 25 > r['percent'] // 25 and pct < 100:
            r['percent'] = pct
            self.say('relay_progress', no=no, percent=pct)
        if r['progress'] < cfg['sn']:
            return
        msgs = [ALN.asset_remove(r['uid'], RELAY_STATION), legacy('0|A|STM|msg_relaisstation_activated')]
        if no >= 2 and cfg.get('pirates'):                        # forum 126411: when relays 2-4 activate, pirates appear around them
            self.spawn(cfg['pirates'][0], cfg['pirates'][1], at=(r['x'], r['y']))
        self.relay = None
        self.save(role=no)
        msgs += self.zone_msgs() if no == 1 else []                 # the first relay opens the HQ healing zone
        nxt = self.show_relay()
        w.send(msgs + ([nxt] if nxt else []))
        self.say('relay_done', no=no)
        self.tell('relay_%d_done' % no)
        self.t = now + L['wave_interval_sec']
        s = self.step()
        self.save(stage=s[0])
        w.log('   LoW relay station %d active' % no)

    def docking_station(self, x, y):
        """When the last relay activates the HQ station gives hangar and trade (forum 126411); before that it cannot be docked with."""
        cx, cy = self.hq()
        cfg = L['role']
        if self.st['role'] >= cfg['count'] and math.hypot(x - cx, y - cy) <= cfg['center']['radius']:
            return dict(posX=cx, posY=cy, peaceRadius=cfg['center']['radius'], pvpPeace=False)
        return None

    # ------------------------------------------------------------ HQ healing zone
    def zone_msgs(self):
        """The healing zone that opens in the middle of the map when the first relay activates (a HEALING POI in the client, visible on the minimap too)."""
        if self.st.get('role', 0) < 1:
            return []
        cx, cy = self.hq()
        return [('MapAddPOICommand', dict(inverted=False, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=4), shape=0,
                                          active=True, design=mod('POIDesignModule', designValue=6), poiId=POI_HQ,
                                          shapeCoordinates=[int(cx), int(cy), int(L['role']['center']['radius'])]))]

    def heal_tick(self, now):
        """A fixed HP per second in the HQ zone (heal_hp_per_sec; grows by relay_increase with each additional active relay); independent of the repair
        robot and of combat (official forum FAQ: heals during combat too). The HQ's narrative on first entering the zone."""
        w = self.w
        n = self.st.get('role', 0)
        if n < 1 or w.hero_dead or now < self.heal_next:
            return
        self.heal_next = now + 1.0
        c = L['role']['center']
        cx, cy = self.hq()
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - cx, hy - cy) > c['radius']:
            return
        self.tell('hq')
        g = self.p.d['ship']
        hp0 = g.get('hitPoints', 0)
        if hp0 >= g.get('hitMax', 0):
            return
        self.p.set_hull(hp=min(g['hitMax'], hp0 + c['heal_hp_per_sec'] * (1 + c['relay_increase'] * (n - 1))))
        w.send([('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=g.get('nanoHull', 0), nanoHullMax=g.get('maxNanoHull', 0)))] + w.heal_msgs(hp0))

    # ------------------------------------------------------------ shooting the relay (world.asset_targets)
    def charge(self):
        """The relay's charge in damage units: (current, required)."""
        cfg = L['role']
        return int(self.relay['progress'] / cfg['sn'] * cfg['damage']), cfg['damage']

    def asset_pos(self, uid):
        r = self.relay
        return (r['x'], r['y']) if r and uid == r['uid'] else None

    def asset_select(self, uid):
        now, need = self.charge()
        return [('ShipSelectionCommand', dict(userId=int(uid), shipType=0, shield=0, shieldMax=0, hitpoints=now, hitpointsMax=need,
                                              nanoHull=0, maxNanoHull=0, shieldSkill=False)),
                ('AssetInfoCommand', dict(assetId=int(uid), type=ALN.mod('AssetTypeModule', typeValue=RELAY_STATION), designId=0,
                                          expansionStage=0, hitpoints=now, maxHitpoints=need, shielded=False, shieldEnergy=0,
                                          maxShieldEnergy=0))]

    def asset_attackable(self, uid):
        """The relay does not activate while pirates (the relay's defenders too) are on the map or before its turn (while waves continue) (the client's text)."""
        if self.alive() or self.step() != ('role', self.st['role']):
            return [legacy('0|A|STM|msg_groupgate_cant_activate_relay_because_npcs_are_alive')]
        return []

    def asset_hit(self, uid, dmg):
        """A hit charges the relay (indicator: AttackHitAssetCommand's HP is the charge)."""
        cfg = L['role']
        self.relay['progress'] = min(cfg['sn'], self.relay['progress'] + dmg / float(cfg['damage']) * cfg['sn'])
        now, need = self.charge()
        msgs = [('AttackHitAssetCommand', dict(assetId=int(uid), hitpointsNow=now, hitpointsMax=need))]
        self.relay_step(time.time())
        return msgs

    def spawn_boss(self):
        """Century Falcon spawns at the HQ (middle of the map), its escort around it."""
        hq = self.hq()
        self.boss = self.spawn(L['boss'], 1, at=hq)[0].id
        tip, n = L['escort']
        self.spawn(tip, n, at=hq)
        self.say('boss')
        self.tell('boss')
        self.w.send([legacy('0|A|STM|msg_boss_adds_spawn')])                 # the escort (the client's text)
        self.w.log('   LoW: Century Falcon arrived')

    def finish(self):
        w = self.w
        self.save(stage='finished')
        dest = L['exit'].get(str(self.p.d['pilot'].get('factionId')), 5)       # the company's X-1 (forum 126411: everyone is thrown to X-1)
        g = dict(gateId=EXIT_ID, x=w.map_w // 2, y=w.map_h // 2, target=dest, designId=1, arrival='station')
        w.add_gate(g)
        w.auto_jump(g, L.get('exit_wait_sec', 5))
        self.say('finished')
        self.tell('finished')
        w.log('   LoW completed: return to the X-1 station')
        self.boss = -1

    # ------------------------------------------------------------ world events
    def on_death(self):
        """On death: the return timer starts; the stage's aliens go away (they come again on return)."""
        self.save(death=time.time())
        if self.st['stage'] == 'wave' and self.alive():
            self.save(wave=max(0, self.st['wave'] - 1))      # a half-finished wave restarts when returning
        elif self.st['stage'] == 'boss':
            self.boss = None

    def asset_msgs(self):
        """Entry bundle: the visible relay and (if the first relay is activated) the HQ healing zone."""
        return ([self.relay_msg()] if self.relay else []) + self.zone_msgs()

    def cleanup_msgs(self):
        return ([ALN.asset_remove(self.relay['uid'], RELAY_STATION)] if self.relay else []) + \
               ([('MapRemovePOICommand', {'poiId': POI_HQ})] if self.zone_msgs() else [])
