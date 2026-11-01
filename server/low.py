"""LoW (Lord of War), tek kişilik sürüm (yol haritası Aşama 4). Değerler ve kaynaklar data/low.json'da.

Harita (wiki görseli, emu-dark): giriş sol alt köşede (harita.LOW_START); ortada korsan HQ'su (süs istasyon map_links.py LOW_STATION; boss burada
doğar; ilk röle etkinleşince çevresinde iyileştirme bölgesi açılır); dört röle istasyonu sabit yerlerde (role.yerler), ilki girişten beri
görünür, sonraki bir öncekinin etkinleşmesiyle belirir; kırmızı uçuş yasağı bölgeleri map_layout.json'un 200 kaydında.
Akış (dünya döngüsünden, kilit altında): rota (low.json): eski korsanlar türlerine göre dalga dalga, sabit doğuş noktalarında (dogma_noktalari);
dalgaların arasında röle istasyonları sırayla (istemcinin RELAY_STATION varlığı; wiki: "shoot the station until its green indicator
loads": vurulunca dolar, dünyanın asset_targets'ı; yedek olarak yanında durunca da; haritada korsan varken ya da sırası gelmeden etkinleşmez,
istemcinin metni) -> Century Falcon ve eskortu HQ'da -> bitti: ortada firmanın X-3'üne dönüş portalı. Anlatı: HQ'dan telsiz metinleri
(istemcinin transmission_groupgate_* anahtarları, low.json anlati).
İlerleme profilde (low: asama, dalga = doğan dalga sayısı, role = etkin röle sayısı; rotadaki sıradaki adım bunlardan türer): ölünce donus_sn
içinde X-3'teki portaldan dönülürse kaldığı aşamadan sürer (dalganın uzaylıları yeniden gelir), yoksa baştan. LoW'da tamir yalnız istasyonda
(X-1); atlama CPU'su çalışmaz.
"""
import json, math, os, random, time

import map_links as H
import alien as ALN
from legacy_protocol import legacy
from galaxy_gates import mod, screen

HERE = os.path.dirname(os.path.abspath(__file__))
L = json.load(open(os.path.join(HERE, 'data', 'low.json'), encoding='utf8'))
MAP = L['map']
RELAY_STATION = 31                  # AssetTypeModule.AssetType (istemci)
RELAY_BASE = 152100000
EXIT_ID = H.GATE_ID_BASE + 990010
POI_HQ = 'lowHqHealing'             # HQ iyileştirme bölgesi (POIType HEALING = 4, design SIMPLE = 6; dunya_patronu'nun şifa feneriyle aynı)


def fresh():
    return {'stage': 'wave', 'wave': 0, 'role': 0, 'death': None}


class Low:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.npcs = set()           # bu aşamanın uzaylıları
        self.relay = None           # {kimlik, x, y, ilerleme, son, yuzde, savunan}
        self.boss = None
        self.heal_next = 0.0
        self.told = set()           # anlatılan olaylar (low.json anlati): her biri girişten sonra bir kez
        now = time.time()
        st = self.p.d.get('low')
        returning = bool(st and st.get('stage') != 'finished' and st.get('death') and now - st['death'] <= L['return_sec'])
        with self.p.lock:
            self.p.d['low'] = dict(st, death=None) if returning else fresh()
            self.p.dirty = True
        self.t = now + L['entry_sec']
        world.asset_targets = self             # röle seçilir ve vurulur (dunya.asset_laser)
        self.show_relay()                      # sıradaki röle girişten görünür
        self.w.send(self.asset_msgs())         # Low hazır demetinden sonra kurulur (resend yalnız haritayı yeniden yükleyince taşır): canlıda ilk röle istemciye gitmiyordu
        self.say('ongoing' if returning else 'entry')
        if not returning:
            self.tell('entry')
        self.w.log('   LoW: %s (%s)' % ('kaldığı yerden' if returning else 'baştan', self.st['stage']))

    @property
    def st(self):
        return self.p.d['low']

    def save(self, **kw):
        with self.p.lock:
            self.st.update(kw)
            self.p.dirty = True

    def say(self, key, **kw):
        """Akış metni: "key:" önekliyse istemcinin metni (Century Falcon, bitiş), değilse low.json'un cümlesi."""
        vals = dict(relays=L['role']['count'], total=len(L['waves']))
        vals.update(kw)
        self.w.send([screen(L['messages'][key].format(**vals))])

    def tell(self, event):
        """HQ'nun telsiz anlatısı (istemcinin transmission_groupgate_* metinleri, low.json anlati): olay başına bir kez."""
        keys = L['narration'].get(event)
        if keys and event not in self.told:
            self.told.add(event)
            self.w.send([legacy('0|A|STM|' + k) for k in keys])

    def hq(self):
        """HQ: haritanın ortası (süs istasyonun yeri)."""
        return self.w.map_w // 2, self.w.map_h // 2

    # ------------------------------------------------------------ doğurma
    def spawn(self, tip, count, near=None, at=None):
        """at verilirse tam o noktanın çevresinde (rota doğuş noktası, HQ); yoksa near'ın (yoksa oyuncunun) çevresinde halkada."""
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

    # ------------------------------------------------------------ adımlar
    def step(self):
        """Rotadaki sıradaki adım (low.json rota): ('dalga', i), ('role', i), ('boss',); bitince None. Profildeki sayaçlardan türer."""
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
            w.log('   LoW dalga %d: %s x%d' % (i + 1, tip, n))
        elif s[0] == 'role':
            if not (self.relay and self.relay['defender']):
                if self.alive():                             # önceki dalga bitmeden rölenin savunanı gelmez
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
        """Sıradaki röle istasyonunu sabit yerinde (role.yerler) belirtir (savunanı sırası gelince doğar) -> yaratma iletisi ya da None."""
        no = self.st['role'] + 1
        if no > L['role']['count']:
            return None
        x, y = L['role']['places'][no - 1]
        self.relay = dict(uid=RELAY_BASE + no, x=x, y=y, progress=0.0, last=time.time(), percent=-1, defender=False)
        return self.relay_msg()

    def place_relay(self, now):
        """Rölenin sırası geldi: yanında Vagrant savunması doğar (röle girişten ya da öncekinin ardından beri haritada görünür)."""
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
        w.log('   LoW röle istasyonu %d: (%d,%d)' % (no, r['x'], r['y']))

    def relay_tick(self, now):
        """Röle (yedek yol): yanında yaricap içinde, haritada korsan yokken ilerler; sn saniyede etkinleşir."""
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
        """Rölenin ilerlemesi (saniye; vuruş hasar/hasar x sn kadar): yüzde iletisi, dolunca etkinleşir; sıradaki röle belirir."""
        w, r, cfg = self.w, self.relay, L['role']
        pct = min(100, int(100 * r['progress'] / cfg['sn']))
        no = self.st['role'] + 1
        if pct // 25 > r['percent'] // 25 and pct < 100:
            r['percent'] = pct
            self.say('relay_progress', no=no, percent=pct)
        if r['progress'] < cfg['sn']:
            return
        msgs = [ALN.asset_remove(r['uid'], RELAY_STATION), legacy('0|A|STM|msg_relaisstation_activated')]
        if no >= 2 and cfg.get('pirates'):                        # forum 126411: 2-4. röle etkinleşince çevresinde korsanlar
            self.spawn(cfg['pirates'][0], cfg['pirates'][1], at=(r['x'], r['y']))
        self.relay = None
        self.save(role=no)
        msgs += self.zone_msgs() if no == 1 else []                 # ilk röle HQ iyileştirme bölgesini açar
        nxt = self.show_relay()
        w.send(msgs + ([nxt] if nxt else []))
        self.say('relay_done', no=no)
        self.tell('relay_%d_done' % no)
        self.t = now + L['wave_interval_sec']
        s = self.step()
        self.save(stage=s[0])
        w.log('   LoW röle istasyonu %d etkin' % no)

    def docking_station(self, x, y):
        """Son röle etkinleşince HQ istasyonu hangar ve ticaret verir (forum 126411); öncesinde yanaşılmaz."""
        cx, cy = self.hq()
        cfg = L['role']
        if self.st['role'] >= cfg['count'] and math.hypot(x - cx, y - cy) <= cfg['center']['radius']:
            return dict(posX=cx, posY=cy, peaceRadius=cfg['center']['radius'], pvpPeace=False)
        return None

    # ------------------------------------------------------------ HQ iyileştirme bölgesi
    def zone_msgs(self):
        """İlk röle etkinleşince haritanın ortasında açılan iyileştirme bölgesi (istemcide HEALING POI'si, mini haritada da görünür)."""
        if self.st.get('role', 0) < 1:
            return []
        cx, cy = self.hq()
        return [('MapAddPOICommand', dict(inverted=False, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=4), shape=0,
                                          active=True, design=mod('POIDesignModule', designValue=6), poiId=POI_HQ,
                                          shapeCoordinates=[int(cx), int(cy), int(L['role']['center']['radius'])]))]

    def heal_tick(self, now):
        """HQ bölgesinde saniyede sabit can (iyilestirme_sn_can; etkin her ek röleyle role_artis kadar artar); onarım robotundan ve
        savaştan bağımsız (resmî forum SSS: savaşırken de iyileşir). Bölgeye ilk girişte HQ'nun anlatısı."""
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

    # ------------------------------------------------------------ röleyi vurma (dunya.asset_targets)
    def charge(self):
        """Rölenin dolumu hasar biriminde: (şimdiki, gereken)."""
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
        """Korsanlar (rölenin savunanı da) haritadayken ya da rölenin sırası gelmeden (dalgalar sürerken) röle etkinleşmez (istemcinin metni)."""
        if self.alive() or self.step() != ('role', self.st['role']):
            return [legacy('0|A|STM|msg_groupgate_cant_activate_relay_because_npcs_are_alive')]
        return []

    def asset_hit(self, uid, dmg):
        """Vuruş röleyi doldurur (gösterge: AttackHitAssetCommand'ın canı dolum)."""
        cfg = L['role']
        self.relay['progress'] = min(cfg['sn'], self.relay['progress'] + dmg / float(cfg['damage']) * cfg['sn'])
        now, need = self.charge()
        msgs = [('AttackHitAssetCommand', dict(assetId=int(uid), hitpointsNow=now, hitpointsMax=need))]
        self.relay_step(time.time())
        return msgs

    def spawn_boss(self):
        """Century Falcon HQ'da (haritanın ortası) doğar, eskortu çevresinde."""
        hq = self.hq()
        self.boss = self.spawn(L['boss'], 1, at=hq)[0].id
        tip, n = L['escort']
        self.spawn(tip, n, at=hq)
        self.say('boss')
        self.tell('boss')
        self.w.send([legacy('0|A|STM|msg_boss_adds_spawn')])                 # eskortu (istemcinin metni)
        self.w.log('   LoW: Century Falcon geldi')

    def finish(self):
        w = self.w
        self.save(stage='finished')
        dest = L['exit'].get(str(self.p.d['pilot'].get('factionId')), 5)       # firmanın X-1'i (forum 126411: herkes X-1'e atılır)
        g = dict(gateId=EXIT_ID, x=w.map_w // 2, y=w.map_h // 2, target=dest, designId=1, arrival='station')
        w.add_gate(g)
        w.auto_jump(g, L.get('exit_wait_sec', 5))
        self.say('finished')
        self.tell('finished')
        w.log('   LoW tamamlandı: X-1 istasyonuna dönüş')
        self.boss = -1

    # ------------------------------------------------------------ dünya olayları
    def on_death(self):
        """Ölünce: dönüş süresi başlar; aşamanın uzaylıları gider (dönünce yeniden gelir)."""
        self.save(death=time.time())
        if self.st['stage'] == 'wave' and self.alive():
            self.save(wave=max(0, self.st['wave'] - 1))      # yarım kalan dalga dönünce baştan
        elif self.st['stage'] == 'boss':
            self.boss = None

    def asset_msgs(self):
        """Giriş demeti: görünür röle ve (ilk röle etkinleştiyse) HQ iyileştirme bölgesi."""
        return ([self.relay_msg()] if self.relay else []) + self.zone_msgs()

    def cleanup_msgs(self):
        return ([ALN.asset_remove(self.relay['uid'], RELAY_STATION)] if self.relay else []) + \
               ([('MapRemovePOICommand', {'poiId': POI_HQ})] if self.zone_msgs() else [])
