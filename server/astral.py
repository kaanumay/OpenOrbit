"""Astral Ascension (yol haritası Aşama 8; istemcinin RogueLite* komutları; veri data/pve_modes.json "astral").

Akış: Astral CPU (kısayol çubuğundan) X-1'de kapıyı açar (portal 86, koşu bitene dek durur). Kapıya atlayınca kiralık gemi seçimi
(RogueLiteSelectShipCommand: Sentinel, Diminisher, Pusat, Zephyr ve aynı başlangıç yüklemesi) -> RogueLiteSelectShipRequest
{loadoutId}: koşu başlar. 15 rift (466-468 sırayla): her rift üç dalga (5 ve 10 ara patron, 15 son patron, tek dalga); uzaylılar
rift ilerledikçe güçlenir, ödül (EP, onur, kredi, uridyum, kargo) vermez. Rift bitince iki ödül kapısı (türü rastgele: silah,
jeneratör, cephane, booster, modül, kaynak, can; çılgın sürümü daha güçlü uzaylı ve daha iyi ödül, 350 puan) ve çıkış portalı.
Seçilen kapı sonraki riftin türünü belirler; o rift bitince ödül: silah/jeneratör/modül/booster için üçünden biri
(RogueLiteSelectRewardCommand -> RogueLiteSelectRewardRequest {lootId}; boş yuva varsa takılır, yoksa koşunun envanterine),
cephane rastgele, kaynak Atlas Shard (bitişte hesaba), can %50. Ara patrondan sonra can %50 dolar.
Kiralık donanım: koşu süresince geçici bir gemi (gemiler'e eklenir), dronlar (5 Iris, ikişer LF-3) ve cephane oyuncununkilerin
yerine geçer; çıkış portalından X-1'e dönünce oyuncununkiler geri gelir, kapıdan yeniden girince kiralıklar (koşu kaldığı yerden
sürer). Koşu ölünce ya da son patronla biter: kiralık her şey silinir, ulaşılan riftin ödülü (Astralite; olasılıkla Salvage Core
ve Astral Booty Key) ve toplanan Atlas Shard'lar verilir. Puan: rift 300 (çılgın 350), ara patron 400, son patron 450, patron
savaşında kalan can (%1'e 3, en çok 300) ve süre (450 - 0,25 x sn); sıralama en iyi 3 koşunun toplamı (tek oyunculu: yalnız
oyuncu).
Profilde: pve.astral {kapi, kosu {gemi, sid, rift, tur, cilgin, puan, atlas, envanter, yedek, icerde, sonraki}, kosular [puan]}.
"""
import json, math, os, random, time

import settings as SET
import galaxy_gates as KAPI
import rankings as RK
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8'))['astral']
PORTAL = 154900000                 # X-1'deki kapı; + 10 + i ödül kapıları; + 50 çıkış
PICK = ('silah', 'jenerator', 'modul', 'booster')
SALVAGE_CHANCE, KEY_CHANCE = 1.0, 0.5          # rift sonu: Kurtarma Çekirdeği her seferde (resmî forum); anahtar uyarlama


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Astral:
    key, name = 'astral', 'Astral Ascension'

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.send = None               # oturuma mesaj
        self.pending = None            # seçim bekleyen ödüller [lootId, seviye/adet]

    @property
    def st(self):
        return self.p.d.setdefault('pve', {}).setdefault('astral', {})

    @property
    def run(self):
        return self.st.get('kosu')

    # ------------------------------------------------------------ CPU ve kapı
    def use_cpu(self, map_id):
        """Astral CPU: X-1'de kapıyı açar -> mesajlar ya da None (kullanılamaz)."""
        import map_links as H
        if H.map_class(map_id) != D['giris'] or self.st.get('kapi') or self.run:
            return None
        if self.p.use_ammo(D['cpu']) is None:
            return None
        with self.p.lock:
            self.st['kapi'] = True
            self.p.dirty = True
        self.log('   Astral CPU kullanıldı: X-1\'de kapı')
        return [KAPI.screen('The Astral Ascension gate has opened in the center of the map.', big=True), self.cpu_cmd()]

    def portals(self, map_id):
        import map_links as H
        if H.map_class(map_id) != D['giris'] or not (self.st.get('kapi') or self.run):
            return []
        w, h = H.map_size(map_id)
        return [dict(gateId=PORTAL, x=w // 2, y=h // 2 + 1200, hedef=0, designId=D['portal'], kapi='astral', pencere='astral')]

    def cpu_cmd(self):
        return ('RogueLiteCpuInfoCommand', dict(keys=int(self.p.resource('resource_booty-key-astral')), showCpu=True))

    # ------------------------------------------------------------ gemi seçimi
    def item_mod(self, loot, lvl=0, n=1, iid=0):
        return mod('InventoryItemModule', upgradeLevel=lvl, lootId=loot, amount=n, itemId=iid, star=0, isNew=False, hangarId=0,
                   extAttributes=[], inventoryItemAttributes=[])

    def ship_list(self):
        from shop import ITEMS
        y, out = D['yukleme'], []
        dr = y['dronlar']
        drones = [mod('RogueLiteDroneModule', lootId=dr['tur'], level=6, equipments=[self.item_mod(dr['lazer'], 0)] * dr['dron_basina'])
                  for _ in range(dr['adet'])]
        eq = [self.item_mod(l, lvl - 1, n) for slot in ('laser', 'generators', 'extra') for l, n, lvl in y[slot]]
        for s in D['gemiler']:
            row = ITEMS['gemiler'].get(s['lootId'], {})
            out.append(mod('RogueLiteShipModule', petEquipments=[], speed=row.get('temel_hiz', 300), drones=drones, lootId=s['lootId'],
                           loadOutId=s['yukleme'], hp=row.get('hp', 0), shipId=s['shipId'], shield=0, equipments=eq, spread=0))
        return ('RogueLiteSelectShipCommand', dict(modifierList=[], shipList=out))

    def gate_jump(self):
        """X-1'deki kapıya atlandı: koşu yoksa gemi seçimi, varsa riftine dön -> (hedef harita ya da None, mesajlar)."""
        if not self.run:
            return None, [self.ship_list()]
        self.swap_in()
        return self.rift_map(), []

    def select_ship(self, f):
        """RogueLiteSelectShipRequest {loadoutId} -> hedef harita ya da None."""
        ship = next((s for s in D['gemiler'] if s['yukleme'] == f.get('loadoutId')), None)
        if not ship or self.run or not self.st.get('kapi'):
            return None
        self.loan(ship)
        return self.rift_map()

    # ------------------------------------------------------------ kiralık donanım
    def loan(self, ship):
        """Kiralık gemi, eşyalar, dronlar ve cephane; koşu kaydı."""
        p, y = self.p, D['yukleme']
        sid = str(p.add_ship(ship['lootId']))
        cfg = p.d['gemiler'][sid]['konfigler']['1']
        lv = p.d.setdefault('yukseltme_seviye', {})
        items = []
        for slot in ('laser', 'generators', 'extra'):
            for loot, n, level in y[slot]:
                for _ in range(n):
                    iid = p.new_item(loot)
                    lv[str(iid)] = level - 1
                    cfg.setdefault(slot, []).append(iid)
                    items.append(iid)
        dr = y['dronlar']
        drones, dcfg = [], p.d['gemiler'][sid].setdefault('dron_konfig', {}).setdefault('1', {})
        for k in range(dr['adet']):
            did = 990000 + k
            drones.append({'kimlik': did, 'lootId': dr['tur'], 'seviye': 6, 'puan': 0, 'yukseltme': 1})
            ids = [p.new_item(dr['lazer']) for _ in range(dr['dron_basina'])]
            dcfg[str(did)] = ids
            items += ids
        with p.lock:
            p.d['gemiler'][sid]['odunc'] = True
            self.st['kosu'] = dict(gemi=ship['lootId'], shipId=ship['shipId'], sid=sid, rift=1, tur=None, cilgin=False, puan=0, atlas=0,
                                   envanter=[], esyalar=items, icerde=False, bas=time.time(),
                                   kiralik=dict(dronlar=drones, cephane=dict(y['cephane']), secili=None))
            self.st['kapi'] = False
            p.dirty = True
        self.log('   Astral: koşu başladı (%s)' % ship['ad'])
        self.swap_in()

    def swap_in(self):
        """Kiralık donanım etkin (oyuncununki koşuda saklanır)."""
        r, p = self.run, self.p
        if not r or r['icerde']:
            return
        k = r['kiralik']
        with p.lock:
            r['yedek'] = dict(aktif=p.d['aktif_gemi'], dronlar=p.d['dronlar'], cephane=p.d['cephane'], secili=dict(p.d.get('secili', {})))
            p.d['dronlar'], p.d['cephane'] = k['dronlar'], k['cephane']
            if k.get('secili'):
                p.d['secili'] = k['secili']
            else:
                p.d['secili'] = {'lazer': 'ammunition_laser_lcb-10', 'roket': 'ammunition_rocket_r-310'}
            r['icerde'] = True
            p.dirty = True
        self.m.activate({'shipId': r['sid']})
        self.log('   Astral: kiralık donanım etkin')

    def swap_out(self):
        """Oyuncunun donanımı geri (kiralıklar koşuda saklanır)."""
        r, p = self.run, self.p
        if not r or not r['icerde']:
            return
        y = r['yedek']
        with p.lock:
            r['kiralik'].update(dronlar=p.d['dronlar'], cephane=p.d['cephane'], secili=dict(p.d.get('secili', {})))
            p.d['dronlar'], p.d['cephane'], p.d['secili'] = y['dronlar'], y['cephane'], y['secili']
            r['icerde'] = False
            p.dirty = True
        self.m.activate({'shipId': y['aktif']})
        self.log('   Astral: oyuncunun donanımı geri')

    def end_run(self, reached, final=False):
        """Koşu bitti: kiralık her şey silinir, ödüller verilir -> mesajlar."""
        r, p = self.run, self.p
        self.swap_out()
        with p.lock:
            sh = p.d['gemiler'].pop(r['sid'], None)
            for iid in r['esyalar'] + r['envanter']:
                p.d['esyalar'].pop(str(iid), None)
                p.d.get('yukseltme_seviye', {}).pop(str(iid), None)
            self.st['kosu'] = None
            runs = self.st.setdefault('kosular', [])
            runs.append(int(r['puan']))
            self.st['kosular'] = sorted(runs, reverse=True)[:20]
            p.dirty = True
        row = next((x for x in D['odul'] if x['en_az'] <= reached <= x['en_cok']), D['odul'][0])
        msgs, got = [], []
        give = [('resource_collectable_astralite', row['astralite'])]
        if random.random() < SET.chance('dusme', SALVAGE_CHANCE, 'mod'):     # panel: düşme şansı
            give.append(('resource_collectable_salvage-core', row['kurtarma']))
        keys = sum(1 for _ in range(row['anahtar']) if random.random() < SET.chance('dusme', KEY_CHANCE, 'mod'))
        if keys:
            give.append(('resource_booty-key-astral', keys))
        if r['atlas']:
            give.append(('resource_collectable_atlas-shard', r['atlas']))
        for loot, n in give:
            msgs += self.m.prize(loot, n)
            got.append('%s x%d' % (loot, n))
            if loot == 'resource_collectable_astralite':
                p.ach('loot', loot=loot, amount=n)                  # Astral Ascension Pass: "Astralite topla" (savas_bileti.py)
        self.log('   Astral bitti: rift %d, puan %d; %s' % (reached, r['puan'], ', '.join(got)))
        msgs.append(KAPI.screen('Astral Ascension ended at rift %d. Score: %d' % (min(reached, 15), r['puan']), big=True))
        return msgs + [self.info_cmd(), self.rank_cmd()]

    # ------------------------------------------------------------ rift
    def rift_map(self):
        return D['haritalar'][(self.run['rift'] - 1) % len(D['haritalar'])]

    def rift(self):
        return D['riftler'][self.run['rift'] - 1]

    def waves(self):
        sets = self.rift()['setler']
        return sets[1 if self.run['cilgin'] and len(sets) > 1 else 0]      # kaynağın iki örnek koşusu: normal ve çılgın

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        r, o, rf = self.run, D['olcek'], self.rift()
        k = r['rift'] - 1
        hp = (1 + o['rift_can'] * k) * (o['cilgin_can'] if r['cilgin'] else 1)
        dmg = (1 + o['rift_hasar'] * k) * (o['cilgin_hasar'] if r['cilgin'] else 1)
        if rf['patron']:
            hp *= o['patron_can'][rf['ad']]
            dmg *= o['patron_hasar'][rf['ad']]
        return PS.scale_npc(n, hp, dmg, 0)          # Astral'da uzaylılar EP/onur/kredi/uridyum/kargo vermez

    def attach(self, world):
        self.world = world
        r = self.run
        if not r:
            world.add_gate(self.exit_portal(world))
            return None
        self.swap_in()
        r['dalga_bas'] = None
        if r.get('temiz'):                         # rift temizlenmiş, kapı seçimi bekliyor (çıkıp dönüldü)
            world.gate = PS.Run(world, self)
            world.gate.phase = 'hold'                  # dalga yok; ölüm yine koşuyu bitirir
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
        r = self.run                                     # istemcinin metni: "%NAME% - Rift %RIFT% Wave %WAVE%"
        self.world.send([KAPI.screen('key:log_astralascension_wave_name', big=True, RIFT=r['rift'], WAVE=i + 1,
                                 NAME='Astral Ascension' + (' (Frenzied)' if r['cilgin'] else ''))])
        if self.rift()['patron']:
            self.run['dalga_bas'] = time.time()

    def wave_done(self, i, now):
        if i + 1 < self.wave_count():
            return 'devam'
        self.rift_done(now)
        return 'dur'

    def rift_done(self, now):
        r, w, rf = self.run, self.world, self.rift()
        S = D['puan']
        pts = S['per_frenzied_rift_cleared'] if r['cilgin'] else S['per_rift_cleared']
        if rf['patron']:
            g = self.p.d['gemi']
            pct = 100.0 * g.get('hitPoints', 0) / max(1, g.get('hitMax', 1))
            t = now - (r.get('dalga_bas') or now)
            pts += (S['final_boss_defeated'] if r['rift'] == 15 else S['mini_boss_defeated'])
            pts += min(300, int(3 * pct)) + int(max(0, min(450, 450 - 0.25 * t)))
        with self.p.lock:
            r['puan'] += pts
            r['temiz'] = True
            self.p.dirty = True
        msgs = [KAPI.screen('Rift %d cleared! +%d points' % (r['rift'], pts), big=True)]
        self.log('   Astral rift %d bitti: +%d puan (%d)' % (r['rift'], pts, r['puan']))
        if r['rift'] >= len(D['riftler']):
            w.send(msgs + self.end_run(16, final=True))
            w.add_gate(self.exit_portal(w))
            return
        if rf['patron']:
            msgs += self.heal(0.5)
        msgs += self.bounty()
        w.send(msgs + [self.score_cmd()])
        if not self.pending:
            self.open_gates()

    def heal(self, f):
        g = self.p.d['gemi']
        hp = min(g.get('hitMax', 0), int(g.get('hitPoints', 0) + g.get('hitMax', 0) * f))
        self.p.set_hull(hp=hp)
        return [('HitpointInfoCommand', dict(hitpoints=int(hp), hitpointsMax=g['hitMax'], nanoHull=int(g.get('nanoHull', 0)),
                                              nanoHullMax=g.get('maxNanoHull', 0)))]

    def bounty(self):
        """Bu riftin (seçilen kapının) ödülü."""
        r = self.run
        t = r.get('tur')
        if not t:
            return []
        lvl_bonus = 3 if r['cilgin'] else 0
        pool = D['havuz'].get(t, [])
        if t == 'can':
            return self.heal(0.5) + [KAPI.screen('50% of your hit points restored.')]
        if t == 'cephane':
            msgs = []
            for loot, lo, hi in random.sample(pool, 2):
                n = int(random.randint(lo, hi) * (1.5 if r['cilgin'] else 1))
                with self.p.lock:
                    self.p.d['cephane'][loot] = self.p.d['cephane'].get(loot, 0) + n
                    self.p.dirty = True
                msgs.append(KAPI.screen('+%d %s' % (n, loot.rsplit('_', 1)[-1].upper())))
            return msgs
        if t == 'kaynak':
            loot, lo, hi = pool[0]
            n = int(random.randint(lo, hi) * (1.5 if r['cilgin'] else 1))
            r['atlas'] += n
            return [KAPI.screen('+%d Atlas Shard (booked at the end of the run)' % n)]
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
        """RogueLiteSelectRewardRequest {lootId}: seçilen ödül takılır ya da envantere -> mesajlar."""
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
            self.p.d.setdefault('yukseltme_seviye', {})[str(iid)] = lvl - 1
            self.run['esyalar'].append(iid)
            if not self.equip(iid, loot):
                self.run['envanter'].append(iid)
            msgs += self.m.apply_stats()
        self.log('   Astral ödülü: %s (seviye %d)' % (loot, lvl))
        self.open_gates()
        return msgs + [self.inventory_cmd()]

    def equip(self, iid, loot):
        """Kiralık gemide boş yuvaya tak -> True."""
        from shop import ITEMS, slot_of
        slot = slot_of(loot)
        if not slot:
            return False
        sid = self.run['sid']
        cfg = self.p.config(None, sid)
        cap = {'laser': 'laser', 'generators': 'generators', 'extra': 'extra', 'upgrades': None}
        row = ITEMS['gemiler'].get(self.run['gemi'], {})
        limit = row.get(slot, 0) if slot != 'upgrades' else 3
        if len(cfg.get(slot, [])) >= limit:
            return False
        with self.p.lock:
            cfg.setdefault(slot, []).append(iid)
            self.p.sync_equipment()
            self.p.dirty = True
        return True

    def open_gates(self):
        """İki ödül kapısı (türleri rastgele; can kapısının çılgını yok) ve çıkış."""
        w = self.world
        x, y = w.map_w // 2, w.map_h // 2
        kinds = random.sample(D['kapi_turleri'], 2)
        for i, k in enumerate(kinds):
            crazy = bool(k['cilgin']) and random.random() < 0.35
            w.add_gate(dict(gateId=PORTAL + 10 + i, x=x - 1500 + 3000 * i, y=y - 1200, hedef=0, designId=k['cilgin'] if crazy else k['tasarim'],
                            kapi='astral', pencere='astral_odul', tur=k['ad'], cilgin=crazy))
        w.add_gate(self.exit_portal(w))
        w.send([self.info_cmd(at_gate=True)])

    def exit_portal(self, world):
        home = KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)
        return dict(gateId=PORTAL + 50, x=world.map_w // 2, y=world.map_h // 2 + 1500, hedef=home, designId=1, kapi='astral', cikis=True,
                    astral_cikis=True, varis='istasyon')

    def choose_gate(self, g):
        """Ödül kapısına atlandı: sonraki rift o türle -> hedef harita."""
        r = self.run
        with self.p.lock:
            r.update(rift=r['rift'] + 1, tur=g['tur'], cilgin=g['cilgin'], temiz=False)
            self.p.dirty = True
        self.log('   Astral: rift %d (%s%s)' % (r['rift'], g['tur'], ', çılgın' if g['cilgin'] else ''))
        return self.rift_map()

    def leaving(self):
        """Çıkış portalıyla X-1'e: oyuncunun donanımı geri, koşu sürer."""
        self.swap_out()

    def on_death(self):
        """Tek can: koşu biter."""
        if self.run:
            self.world.send(self.end_run(self.run['rift']))
        return 0

    def revive(self):
        pass

    # ------------------------------------------------------------ gösterge
    def best3(self):
        return sum(self.st.get('kosular', [])[:3])

    def cashout_cmd(self):
        r = self.run
        if not r:
            return mod('RogueLiteCashOutCommand', confirmedList=[], chanceUpList=[])
        row = next((x for x in D['odul'] if x['en_az'] <= r['rift'] <= x['en_cok']), D['odul'][0])
        duration = [self.item_mod('resource_collectable_astralite', 0, row['astralite'])]
        if r['atlas']:
            duration.append(self.item_mod('resource_collectable_atlas-shard', 0, r['atlas']))
        chance = [self.item_mod('resource_collectable_salvage-core', 0, row['kurtarma'])]
        if row['anahtar']:
            chance.append(self.item_mod('resource_booty-key-astral', 0, row['anahtar']))
        return mod('RogueLiteCashOutCommand', confirmedList=duration, chanceUpList=chance)

    def info_cmd(self, at_gate=False):
        r = self.run or {}
        return ('RogueLiteInfoCommand', dict(isAtGate=at_gate, cpuInfo=mod('RogueLiteCpuInfoCommand', **self.cpu_cmd()[1]),
                                             shipId=int(r.get('shipId', 0)), score=int(r.get('puan', 0)), progress=int(r.get('rift', 0)),
                                             cashoutInfo=self.cashout_cmd(), highscore=int(self.best3())))

    def score_cmd(self):
        r = self.run or {}
        return ('RogueLiteScoreInfoCommand', dict(score=int(r.get('puan', 0)), progress=int(r.get('rift', 0))))

    def inventory_cmd(self):
        r = self.run
        if not r:
            return ('RogueLiteInventoryCommand', dict(equipments=[], inventory=[], unstableModules=[]))
        lv = self.p.d.get('yukseltme_seviye', {})
        eq = [i for slot in ('laser', 'generators', 'extra', 'upgrades') for i in self.p.config(None, r['sid']).get(slot, [])]
        it = lambda i: self.item_mod(self.p.d['esyalar'].get(str(i), ''), int(lv.get(str(i), 0)), 1, i)
        return ('RogueLiteInventoryCommand', dict(equipments=[it(i) for i in eq if str(i) in self.p.d['esyalar']],
                                                  inventory=[it(i) for i in r['envanter'] if str(i) in self.p.d['esyalar']],
                                                  unstableModules=[]))

    def change_equipment(self, f):
        """RogueLiteChangeEquipmentRequest {modifiedItemIds}: takılıysa envantere, envanterdeyse (yuva boşsa) tak."""
        r = self.run
        if not r:
            return []
        cfg = self.p.config(None, r['sid'])
        for iid in [int(x) for x in f.get('modifiedItemIds', [])]:
            loot = self.p.d['esyalar'].get(str(iid))
            if not loot or iid not in r['esyalar']:
                continue
            slot = next((s for s, ids in cfg.items() if iid in ids), None)
            if slot:
                with self.p.lock:
                    cfg[slot].remove(iid)
                    r['envanter'].append(iid)
                    self.p.dirty = True
            elif iid in r['envanter'] and self.equip(iid, loot):
                r['envanter'].remove(iid)
        with self.p.lock:
            self.p.sync_equipment()
        return self.m.apply_stats() + [self.inventory_cmd()]

    def rank_cmd(self):
        """Rank sekmesi: sunucudaki oyuncular (en iyi üç koşunun toplamı)."""
        import community as TP
        row = lambda r: mod('RankModule', lastUpdateTime=int(time.time() * 1000), name=r[1].d['pilot'].get('userName', ''), rank=r[0],
                            points=int(r[2]))
        top, me = TP.ranking(self.p, lambda x: sum(((x.d.get('pve') or {}).get('astral') or {}).get('kosular', [])[:3]))
        info = mod('RogueLiteRankInfoCommand', topRankers=[row(r) for r in top], myRank=row(me))
        return ('RogueLiteRankEventInfoCommand', dict(playerRankRanges=RK.ranges(RK.ASTRAL), rankInfoCommand=info,
                                                         isEventEnabled=True))
