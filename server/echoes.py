"""Deep Space Echoes (yol haritası Aşama 8; istemcinin Expedition* komutları; veri data/pve_modes.json "echoes").

Seviye 15'ten; X-1'deki portal (300) Command Hall'a (473) götürür. Salonda üç portal: sol (301) seviyeyi başlatır, orta (302)
gemi seçimi, sağ (1) çıkış. Gemi seçimi: hangardaki gemilerden en çok 5 (ExpeditionShipListCommand -> ExpeditionSelectShipRequest
{hangarId [...]}); kadro onaylanınca değişmez (sıfırlamaya dek). Sol portal: kadrodan bu seviyenin gemisi (ExpeditionSelectedShip-
ListCommand -> ExpeditionActivateShipRequest {hangarId}): o gemi etkin olur, seviye haritasına (DSE 1-8, 474-481) gidilir,
ExpeditionStartInstanceCommand {seconds} süreyi başlatır. Bir koşunun ilk seviyesi bir Travel Permit ister (mağazadan 8.000 U:
ExpeditionBuyTicketRequest).
50 seviye, beşerli bloklar: ilk dördü (yok et, koru, eşlik et; blok içinde rastgele sırayla) ve sabit patron seviyesi. Koru: haritanın
ortasında duran dost gemi, uzaylılar ona da ateş eder; eşlik et: dost gemi haritanın bir yanından öbürüne gider, varınca kazanılır.
Dost gemi yok olursa, gemin yok olursa ya da süre dolarsa seviye kaybedilir; yok olan gemi bu koşuda kullanılamaz. Seviye bitince
ilk geçiş ödülü (bir kez, sıfırlanmaz) ve her geçişte uridyum + UCB-100; salona dönüş portalı açılır.
Sıfırlama (ExpeditionResetRequest): ilerleme 1. seviyeye, kadro boşalır. Atlama (ExpeditionJumpTargetLevelRequest): ulaşılmış bloğun
başına uridyumla. Aylık dönem: ay değişince ilerleme ve sıralama sıfırlanır (ilk geçiş ödülleri kalır; geçen ay seviye geçen oyuncu
tek oyunculu sıralamanın birincisi: yeni dönemde Cosmic Tyrant unvanı, siralama[].unvan). Sıralama: en yüksek seviye,
eşitlikte toplam süre (tek oyunculu: yalnız oyuncu). Patron seviyesi (her 5.) bitince Echo sandığı düşer (Aşama 9; qfc.py): renk
ulaşılan seviyeye göre, açmak için aynı renk Echo Key (anahtarlı kutu sistemi, loot.py); içinde Quantum Fluid Core.
Profilde: pve.echoes {donem, seviye, en_yuksek, sure, ilk [], kadro [hangarId], yok [hangarId], sira {blok: [seviye …]}, izin}.
"""
import datetime, json, math, os, random, time

import galaxy_gates as KAPI
import pve_common as PS
import qfc as QF

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8'))['echoes']
LEVELS = {l['level']: l for l in D['levels']}
PORTAL = 155900000            # + 0 X-1, + 1 başlat, + 2 gemi seçimi, + 3 çıkış, + 4 salona dönüş
UI_TICKET, UI_RESET, UI_LEAVE = 1, 2, 5
# istemci (ExpeditionShowUiCommandHandler): 3 kadro penceresini, 4 gemi seçim (başlat) penceresini kapatır. Onay ve Save düğmeleri
# yalnız istek gönderiyor, pencereyi sunucunun bu komutu kapatıyor; önce gönderilmiyordu, iki pencere seviyede de açık kalıyordu
# (1280x720'de kadro penceresinin X'i ekran dışında; canlı test H74)
UI_CLOSE_ROSTER, UI_CLOSE_START = 3, 4
# Command Hall düzeni (oyuncu bildirimi 2026-10-28, resmî istemcinin ekran görüntüsü ve mini haritası): portallar salonun ortasında,
# aynı ekranda; sol başlatır, ortadaki bina (sol alt) gemi seçimi, sağdaki halka çıkış/sıfırlama. Varış oyuncunun durduğu yer.
# Gemi seçimi bir portal değil, istasyon hangarı (AssetType 48; sarı oklu kollar ekran görüntüsündekiyle aynı, canlı denendi):
# hangar çizilir, yerindeki tasarımsız giriş J ile pencereyi açar (istemci portal yokken de JumpRequest gönderir).
HALL_START, HALL_SHIPS, HALL_EXIT, HALL_ARRIVAL = (9270, 6480), (9910, 6840), (10650, 6220), (10000, 6300)
HANGAR_ASSET, HANGAR_ID = 48, PORTAL + 9


def mod(_cls, **f):
    f['_'] = _cls
    return f


def period(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).strftime('%Y-%m')


class Echoes:
    key, name = 'echoes', 'Deep Space Echoes'

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.titles = None             # oturum bağlar: unvan_avi.grant_title (dönem sonu sıralama unvanı)
        self.level = None              # oynanan seviyenin kaydı
        self.ally_npc = None

    @property
    def st(self):
        s = self.p.d.setdefault('pve', {}).setdefault('echoes', {})
        if s.get('period') != period():
            first, top = s.get('first', []), s.get('highest', 0)
            s.clear()
            s.update(period=period(), level=1, highest=0, sure=0, first=first, roster=[], none=[], order={}, run=False)
            if top:                    # tek oyunculu sıralamada oynayan birinci: unvan info_cmd'de verilir (st profil kilidi altında da okunur)
                s['title_pending'] = True
            self.p.dirty = True
        return s

    def permits(self):
        return self.p.resource(D['ticket'])

    # ------------------------------------------------------------ portallar
    def portals(self, map_id):
        import map_links as H
        out = []
        if H.map_class(map_id) == D['entry'] and int(map_id) == KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5):
            w, h = H.map_size(map_id)
            # resmî sunucu kaydı: 2-1'de bu tasarımın (300) portalı (11210, 6310), haritanın ortasında
            out.append(dict(gateId=PORTAL, x=w // 2 + 710, y=h // 2 - 240, target=D['hall'], designId=D['portal'], gate='echoes',
                            windowed='echoes_entry', arrival=HALL_ARRIVAL))
        elif int(map_id) == D['hall']:
            home = KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)
            out += [dict(gateId=PORTAL + 1, x=HALL_START[0], y=HALL_START[1], target=0, designId=301, gate='echoes', windowed='echoes_start',
                         tooltip='window_dse_title', in_place=True),
                    dict(gateId=PORTAL + 2, x=HALL_SHIPS[0], y=HALL_SHIPS[1], target=0, gate='echoes', windowed='echoes_ship',
                         tooltip='window_dse_choose_ship_info', in_place=True),
                    dict(gateId=PORTAL + 3, x=HALL_EXIT[0], y=HALL_EXIT[1], target=0, designId=1, gate='echoes', windowed='echoes_exit',
                         tooltip='ttip_jumpgate', hint_target=home, in_place=True)]
        return out

    def hangar_cmd(self):
        """Command Hall'ün gemi seçimi binası: istasyon hangarı (EIC görünümü, ekran görüntüsündeki sarı)."""
        return ('AssetCreateCommand', dict(
            assetId=HANGAR_ID, type=mod('AssetTypeModule', typeValue=HANGAR_ASSET), userName='Hangar', factionId=2, clanTag='',
            posX=HALL_SHIPS[0], posY=HALL_SHIPS[1], designId=0, expansionStage=0, invisible=False, visibleOnWarnRadar=False,
            detectedByWarnRadar=True, showBubble=True, clanId=0, clanRelation=mod('ClanRelationModule', type=0), modifier=[]))

    def enter_hall(self):
        """X-1 portalı: seviye şartı -> (hedef, mesajlar)."""
        if self.p.d['pilot'].get('level', 1) < D['level_requirement']:
            return None, [KAPI.screen('Deep Space Echoes requires level %d.' % D['level_requirement'])]
        return D['hall'], []

    # ------------------------------------------------------------ gemiler
    def ship_cmd(self, sid, hid=None):
        from shop import ITEMS
        s = self.p.d['ships'][str(sid)]
        row = ITEMS['ships'].get(s['lootId'], {})
        active = str(sid) == self.p.d['active_ship']
        g = self.p.d['ship'] if active else (s.get('hull') or {})
        cfg = self.p.config(None, sid)
        hp = row.get('hp', 0)
        return mod('ExpeditionShipCommand', hangarId=int(s['hangarId']), generators=len(cfg.get('generators', [])), maxNano=hp,
                   nano=int(g.get('nanoHull', 0)), maxShield=int(self.p.d['ship'].get('shieldMax', 0)) if active else 0,
                   extras=len(cfg.get('extra', [])), hp=int(g.get('hitPoints', hp)), modules=len(cfg.get('upgrades', [])),
                   destroyed=int(s['hangarId']) in self.st['none'], lootId=self.p.ship_look(sid),
                   shield=int(self.p.d['ship'].get('shield', 0)) if active else 0, maxHp=hp, lasers=len(cfg.get('laser', [])),
                   rockets=len(cfg.get('rocket', [])))

    def sid_of(self, hid):
        return next((k for k, s in self.p.d['ships'].items() if int(s['hangarId']) == int(hid) and not s.get('on_loan')), None)

    def ship_list(self):
        sids = [k for k, s in sorted(self.p.d['ships'].items(), key=lambda x: int(x[0])) if not s.get('on_loan')]
        return ('ExpeditionShipListCommand', dict(shipCommands=[self.ship_cmd(k) for k in sids]))

    def select_ships(self, f):
        """ExpeditionSelectShipRequest {hangarId [...]}: kadro (en çok 5; onaylanınca değişmez)."""
        from shop import stack_msg
        ids = [int(x) for x in f.get('hangarId', [])]
        ok = bool(ids) and len(ids) <= D['roster'] and not self.st['roster'] and all(self.sid_of(h) for h in ids)
        if ok:
            with self.p.lock:
                self.st['roster'] = ids
                self.p.dirty = True
            self.log('   Echoes kadrosu: %s' % ids)
        return [('ExpeditionSelectShipCommand', dict(result=ok, stack=stack_msg('eqt_error_generic') if not ok else
                                                     mod('BaseStackCommand', type=0, enumBaseKey=0, stringBasekey='', argsList=[])))] +             ([('ExpeditionShowUiCommand', dict(type=UI_CLOSE_ROSTER, param0='', param1=''))] if ok else [])

    def roster_cmd(self):
        cur = next((int(s['hangarId']) for k, s in self.p.d['ships'].items() if k == self.p.d['active_ship']), 0)
        return ('ExpeditionSelectedShipListCommand', dict(
            shipCommands=[self.ship_cmd(self.sid_of(h)) for h in self.st['roster'] if self.sid_of(h)], selectedHangarId=cur))

    # ------------------------------------------------------------ seviye
    def level_no(self):
        """Bloğun içinde rastgele sıra: koşunun n. seviyesi hangi seviyenin haritası."""
        n = self.st['level']
        b = (n - 1) // 5
        if n % 5 == 0:
            return n
        order = self.st['order'].get(str(b))
        if not order:
            order = list(range(b * 5 + 1, b * 5 + 5))
            random.shuffle(order)
            with self.p.lock:
                self.st['order'][str(b)] = order
                self.p.dirty = True
        return order[(n - 1) % 5]

    def start_level(self, f):
        """ExpeditionActivateShipRequest {hangarId} -> (hedef harita ya da None, mesajlar)."""
        hid = int(f.get('hangarId') or 0)
        sid = self.sid_of(hid)
        st = self.st
        if hid not in st['roster'] or hid in st['none'] or not sid:
            return None, [KAPI.screen('This ship cannot be used.')]
        if st['level'] > len(LEVELS):
            return None, [KAPI.screen('All levels are cleared. Reset to start again.')]
        if not st['run']:
            if self.permits() < 1:
                return None, [('ExpeditionShowUiCommand', dict(type=UI_TICKET, param0='', param1=''))]
            self.p.add_resource(D['ticket'], -1)
            with self.p.lock:
                st['run'] = True
                self.p.dirty = True
        if sid != self.p.d['active_ship']:
            self.m.activate({'shipId': sid})
        lvl = LEVELS[self.level_no()]
        self.level = dict(no=st['level'], map=lvl['level'], type=lvl['type'], hid=hid, start=None)
        dest = D['maps'][(st['level'] - 1) % len(D['maps'])]
        self.log('   Echoes seviye %d (%s, %d. seviyenin haritası) -> %d' % (st['level'], lvl['type'], lvl['level'], dest))
        return dest, [('ExpeditionShowUiCommand', dict(type=UI_CLOSE_START, param0='', param1=''))]

    def waves(self):
        return LEVELS[self.level['map']]['waves']

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        lvl = LEVELS[self.level['map']]
        f = (1 + D['scale_level'] * (self.level['no'] - 1)) * lvl.get('power', 1.0)
        return PS.scale_npc(n, f * lvl.get('can', 1.0), f, 1.0)        # can: yalnız can/kalkan çarpanı (45. seviyenin patronu)

    def attach(self, world):
        self.world = world
        world.ally = None
        if int(world.map_id) == D['hall']:
            world.send([self.hangar_cmd()])
            return None
        if not self.level:
            world.add_gate(self.hall_portal(world))
            return None
        self.level['start'] = time.time()
        self.level['end_time'] = self.level['start'] + (LEVELS[self.level['map']].get('sure_sn') or D['sure_sn'])
        world.gate = PS.Run(world, self, intro_sec=5, break_sec=4)
        msgs = [('ExpeditionStartInstanceCommand', dict(seconds=int(self.level['end_time'] - self.level['start']))),
                KAPI.screen('Level %d: %s' % (self.level['no'], {'destroy': 'Destroy all enemies.', 'guard': 'Protect the ship!',
                                                                'escort': 'Escort the ship to its destination!',
                                                                'boss': 'Destroy the boss!'}.get(self.level['type'], '')), big=True)]
        if self.level['type'] in ('guard', 'escort'):
            self.spawn_ally(world)
        world.send(msgs)
        return world.gate

    def spawn_ally(self, w):
        kind = self.level['type']
        tip = 'pm_ally_' + kind
        import map_links as H
        cx, cy = H.center(w.map_id)
        x, y = (cx, cy) if kind == 'guard' else (2500, cy)
        n = w.spawn_npc_at(tip, x, y)
        n.gate = True
        self.toughen_ally(n)
        self.ally_npc = n
        w.ally = self
        if kind == 'escort':
            self.level['target'] = (w.map_w - 2500, cy)

    ALLY_SURVIVE_SEC = 180           # uyarlama (kaynakta yok): dost gemi seviyenin en güçlü dalgasının ateşine bu kadar dayanır

    def toughen_ally(self, n):
        """Dost geminin canı seviyenin ateş gücüne göre (en az data 'dost' değerleri). Sabit 400.000 + 200.000'de 2. seviyenin 5 Reflector
        Mimesis'i (50.000 hasar) onu 6 sn'de yok ediyordu: koru seviyeleri kazanılamıyordu (canlı test H75)."""
        import world as world_module
        f = (1 + D['scale_level'] * (self.level['no'] - 1)) * LEVELS[self.level['map']].get('power', 1.0)
        dps = 0.0
        for wave in self.waves():
            w_dps = sum(c * float(world_module.CFG['types'].get(str(t), {}).get('damage', 0)) for grp in wave['groups'] for t, c, *_ in grp)
            dps = max(dps, w_dps)
        # take_shot: atışların yarısı dosta, hasar 0,7-1,0 (ort. 0,85), atış aralığı
        dps = dps * f * 0.5 * 0.85 / world_module.COMBAT['npc_attack_interval_sec']
        need = dps * self.ALLY_SURVIVE_SEC
        hp = max(float(D['friendly']['can']), need * 2 / 3)
        sh = max(float(D['friendly']['kalkan']), need / 3)
        n.d = dict(n.d, hp=int(hp), kalkan=int(sh))         # türün kopyası (tür paylaşılır)
        n.hp, n.shield = int(hp), int(sh)

    def take_shot(self, n, now):
        """Uzaylının atışı dost gemiye mi (menzildeyse yarı yarıya) -> True."""
        a, w = self.ally_npc, self.world
        if not a or not a.alive or random.random() > 0.5:
            return False
        ax, ay = a.mover.pos(now)
        nx, ny = n.mover.pos(now)
        if math.hypot(ax - nx, ay - ny) > w.npc_range(n) + 200:
            return False
        import world as world_module
        n.next_shot = now + n.d.get('shot_interval_sec', world_module.COMBAT['npc_attack_interval_sec'])
        import settings as SET
        dmg = int(n.d['damage'] * random.uniform(0.8, 1.0) * SET.multiplier('npc_damage', 'wave' if n.hunt else 'map'))      # panel
        to_shield = min(int(a.shield), int(dmg * 0.7))
        a.shield -= to_shield
        a.hp = max(0, a.hp - (dmg - to_shield))
        w.send([('AttackLaserRunCommand', dict(attackerId=n.id, targetId=a.id, laserColor=0, isDiminishedBySkillShield=False,
                                               skilledLaser=False, visualType=0)),
                ('AttackHitCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=1), attackerId=n.id, victimId=a.id,
                                          victimHitpoints=int(a.hp), victimShield=int(a.shield), victimNanoHull=0, damage=dmg,
                                          skilled=False, strike=False, cannonType=0))])
        if a.hp <= 0:
            a.alive = False
            w.npcs.pop(a.id, None)
            w.send([('ShipDestroyedCommand', dict(destroyedUserId=a.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': a.id})])
            self.fail('The protected ship was destroyed.')
        return True

    def tick(self, now):
        lv, w = self.level, self.world
        if not lv:
            return
        if now >= lv.get('end_time', now + 1):
            self.fail('Time is up.')
            return
        a = self.ally_npc
        if lv['type'] == 'escort' and a and a.alive:
            tx, ty = lv['target']
            ax, ay = a.mover.pos(now)
            if math.hypot(tx - ax, ty - ay) < 300:
                self.win(now)
                return
            if now >= getattr(a, 'next_move', 0):
                step = 1200
                d = math.hypot(tx - ax, ty - ay)
                nx, ny = ax + (tx - ax) * min(1, step / d), ay + (ty - ay) * min(1, step / d)
                ms = a.mover.go(nx, ny, 90, now)
                a.next_move = now + ms / 1000.0
                w.send([('MoveCommand', dict(userId=a.id, x=int(nx), y=int(ny), timeToTarget=ms))])

    def wave_started(self, i):
        if self.wave_count() > 1:
            self.world.send([KAPI.screen('Wave %d/%d' % (i + 1, self.wave_count()))])

    def wave_done(self, i, now):
        if i + 1 < self.wave_count():
            return 'ongoing'
        if self.level['type'] == 'escort' and self.ally_npc and self.ally_npc.alive:
            return 'halt'                        # eşlik: dalgalar bitti, gemi varınca kazanılır
        self.win(now)
        return 'halt'

    def win(self, now):
        lv, st, w = self.level, self.st, self.world
        if not lv:
            return
        secs = int(now - lv['start'])
        n = lv['no']
        msgs = []
        if n not in st['first']:
            for loot, a in LEVELS[n]['first']:
                msgs += self.grant(loot, a)
            st['first'].append(n)
        t = D['repeat']
        msgs += self.grant('currency_uridium', t['uridium_base'] + t['uridium_level'] * n)
        msgs += self.grant('ammunition_laser_ucb-100', t['ucb_base'] + t['ucb_level'] * n)
        with self.p.lock:
            st['level'] = n + 1
            st['highest'] = max(st['highest'], n)
            st['sure'] = st.get('sure', 0) + secs
            self.p.dirty = True
        self.p.ach('gate', type='EXPEDITION_GATE')
        self.level = None
        self.clear_ally()
        w.gate.phase = 'done'
        w.add_gate(self.hall_portal(w))
        box = QF.echo_box(n) if lv['type'] == 'boss' else None
        if box:                                                     # Echo sandığı (Aşama 9): geminin yanına, anahtarla açılır
            hx, hy = w.hero_pos(now)
            h = w.drop_box(box, hx + random.uniform(-150, 150), hy + random.uniform(-150, 150), None, None)
            w.boxes[h]['keyed'] = True
        w.send(msgs + [KAPI.screen('key:log_msg_gg_completed_expedition', big=True),
                       KAPI.screen('Level %d cleared in %s!' % (n, '%d:%02d' % divmod(secs, 60))), self.info_cmd()])
        self.log('   Echoes seviye %d bitti: %d sn' % (n, secs))

    def fail(self, why):
        lv, w = self.level, self.world
        if not lv:
            return
        self.level = None
        self.clear_ally()
        if w.gate:
            w.gate.phase = 'done'
        for nid in list(w.gate.npcs if w.gate else []):
            n = w.npcs.get(nid)
            if n:
                w.alien.expire(n)
        w.add_gate(self.hall_portal(w))
        w.send([KAPI.screen('Level %d failed: %s' % (lv['no'], why), big=True)])
        self.log('   Echoes seviye %d kaybedildi: %s' % (lv['no'], why))

    def clear_ally(self):
        if self.world:
            self.world.ally = None
        a = self.ally_npc
        if a and a.alive and self.world:
            self.world.alien.expire(a)
        self.ally_npc = None

    def lair(self, j):
        """Pusu (harita_duzeni 'pusu'; oyuncu bildirimi 2026-10-28): yok et seviyesinde dalganın j. grubu haritanın sabit noktasında
        bekler, oyuncu yaklaşınca saldırır -> (x, y, fark yarıçapı) ya da None."""
        import map_layout as ML
        p = ML.of(self.world.map_id).get('ambush') if self.world and self.level and self.level['type'] == 'destroy' else None
        if not p:
            return None
        x, y = p['waypoints'][j % len(p['waypoints'])]
        return x, y, p['radius']

    def hall_portal(self, w):
        import map_links as H
        cx, cy = H.center(w.map_id)
        return dict(gateId=PORTAL + 4, x=cx, y=cy + 1500, target=D['hall'], designId=301, gate='echoes',
                    arrival=HALL_ARRIVAL)

    def on_death(self):
        """Gemi yok oldu: bu koşuda kullanılamaz, seviye kaybedilir."""
        lv = self.level
        if lv:
            with self.p.lock:
                if lv['hid'] not in self.st['none']:
                    self.st['none'].append(lv['hid'])
                self.p.dirty = True
            self.fail('Your ship is destroyed.')
        return 0

    def revive(self):
        pass

    def grant(self, loot, a):
        n = random.randint(a[0], a[1]) if isinstance(a, list) else a
        if loot.startswith('currency_') and self.world:
            return self.world.grant_loot(loot, n, 'mod')
        return self.m.reward(loot, n) if self.m else []

    # ------------------------------------------------------------ pencereler
    def info_cmd(self):
        st = self.st
        if st.get('title_pending') and self.titles:             # geçen ayın birincisi (wiki: Cosmic Tyrant)
            self.titles(next(r['title'] for r in D['ranking'] if r['from_'] == 1))
            st.pop('title_pending')
        me = st['highest']
        ranks = [mod('ExpeditionRankUserInfoCommand', rank=1, curLevel=me, clearanceTime=int(st.get('sure', 0)),
                     userId=self.p.d['pilot'].get('userId', 0), userName=self.p.d['pilot'].get('userName', ''))] if me else []
        rewards = [mod('RankRewardCommand', rankType=13, rewardContentModuleList=[mod('RewardModule', lootId=l, amount=n) for l, n in r['items']],
                       rewardRange=mod('RankRewardRangeModule', **{'from': r['from_'], 'to': r['e']})) for r in D['ranking']]
        n = min(st['level'], len(LEVELS))
        lvl = LEVELS[n]
        t = D['repeat']
        clear = mod('ExpeditionClearanceTimeCommand', seconds=int(st.get('sure', 0)), faction=mod('FactionModule',
                    faction=self.p.d['pilot'].get('factionId', 1)), userName=self.p.d['pilot'].get('userName', ''),
                    shipLootId=self.p.ship_look(), userId=self.p.d['pilot'].get('userId', 0))
        end = datetime.date.today().replace(day=28) + datetime.timedelta(days=4)
        end = end.replace(day=1) - datetime.timedelta(days=1)
        return ('ExpeditionInfoCommand', dict(
            keyCount=int(self.permits()), curLevel=n, rankRewards=rewards, ranks=ranks,
            failureCondition='window_dse_fail_con1', victoryCondition='window_dse_vic_con1', conditionNpcId=0,
            firstRewards=[mod('ExpeditionRewardCommand', lootId=l, amount=a if isinstance(a, int) else a[0])
                          for l, a in (lvl['first'] if n not in st['first'] else [])],
            expeditionClearanceTimeCommand=clear, eventEndTime=end.strftime('%d.%m.%Y') + ' 23:59',
            timeLimit=int(lvl.get('sure_sn') or D['sure_sn']), popup=False, myRank=1 if me else -1,
            normalRewards=[mod('ExpeditionRewardCommand', lootId='currency_uridium', amount=t['uridium_base'] + t['uridium_level'] * n),
                           mod('ExpeditionRewardCommand', lootId='ammunition_laser_ucb-100', amount=t['ucb_base'] + t['ucb_level'] * n)],
            maxLevel=me))

    def jump_info_cmd(self):
        top = self.st['highest']
        lv = [x for x in D['jump']['targets'] if self.st['level'] < x <= top]      # yalnız ilerisi: ilerlemede olan oyuncuya geri atlama penceresi açılmaz
        return ('ExpeditionJumpLevelInfoCommand', dict(levels=lv, costs=[D['jump']['cost_block'] * ((x - 1) // 5) for x in lv]))

    def jump(self, f):
        from shop import stack_msg
        target = int(f.get('jumpTargetLevel') or 0)
        top = self.st['highest']
        ok = target in D['jump']['targets'] and self.st['level'] < target <= top
        cost = D['jump']['cost_block'] * ((target - 1) // 5)
        if ok and self.p.d['pilot'].get('uridium', 0) >= cost:
            self.p.gain(uridium=-cost, reason='expedition_jump')
            with self.p.lock:
                self.st['level'] = target
                self.p.dirty = True
            self.log('   Echoes: %d. seviyeye atlandı (%d U)' % (target, cost))
        else:
            ok = False
        msgs = [('ExpeditionJumpTargetLevelCommand', dict(result=ok, stack=stack_msg('eqt_error_generic') if not ok else
                                                          mod('BaseStackCommand', type=0, enumBaseKey=0, stringBasekey='', argsList=[])))]
        return msgs + (self.m.money_msgs() if ok else []) + [self.info_cmd()]

    def reset(self):
        with self.p.lock:
            self.st.update(level=1, roster=[], none=[], order={}, run=False)
            self.p.dirty = True
        self.log('   Echoes sıfırlandı')
        return [self.info_cmd()]

    def buy_ticket(self):
        from shop import stack_msg
        ok = self.p.d['pilot'].get('uridium', 0) >= D['ticket_price']
        if ok:
            self.p.gain(uridium=-D['ticket_price'], reason='buy_expedition_ticket')
            self.p.add_resource(D['ticket'], 1)
        return [('ExpeditionBuyTicketCommand', dict(result=ok, stack=stack_msg('eqt_error_generic') if not ok else
                                                    mod('BaseStackCommand', type=0, enumBaseKey=0, stringBasekey='', argsList=[])))] + \
            (self.m.money_msgs() if ok else []) + [self.info_cmd()]
