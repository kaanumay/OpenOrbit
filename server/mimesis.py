"""Mimesis Mutiny / Payload Escort (yol haritası Ö4; veri data/buyuk_icerikler.json 'mimesis' <- tools/buyuk_icerikler.py).

Takvimde (12-26 Mart, 12-26 Kasım) X-1 ve X-8'deki portaldan bir Escort Key'le firmanın Escort haritasına (MMO 433, EIC 436, VRU 430)
girilir. EM Freighter her tam saatte (10:00-23:00) doğar; ilk 5 dakikada girilir, 45 dakikada hedefe varmalı (panelin "Seanslı
etkinlikler hep açık" ayarıyla sefer girince başlar). Gemi yalnız oyuncu koruma alanının (1.200) içindeyken ilerler; alanın dışı
radyasyon (ters RADIATION POI'si). Rota dört nokta ve işaret feneri: her noktada Mimesis dalgası, temizlenene dek gemi durur
(msg_mutiny_escort_disrupted); yolda arada bir Assailant/Raider. Uzaylıların atışlarının yarısı gemiye (Deep Space Echoes'un
eşlik kalıbı). Fenerde Marker ve taretler; temizlenip varınca 5 sn sonra gemi ve fener patlar, çıkış portalı açılır, harita radyasyon
olur. Puan: öldürme (türün puanı), nokta (400), varış (3.000 x geminin can oranı); sefer puanı başarısız seferde de saklanır. Başarılı
seferde sefer kademesinin ödülleri (1.000-8.000+). Toplam puan en iyi 10 seferin toplamı; pencerenin ödül sekmesi sıralama bantları
(RankRewardRequest rankType 5; tek oyunculu: oyuncu 1.). Gemi yok olursa ya da süre dolarsa sefer biter. Ölünce yerinde ücretsiz tamir
(kalırsın) ya da üste dönüş (bu sefere yeniden girilemez).
Ödüller (wiki aliens / Mimesis Box): uzaylı yok olunca Byte Remnant doğrudan (türün 'byte'ı; npc ek_odul), kutusundan ayrıca; kutu
toplanınca %30'la Mimesis Chest etkisi (mimesis_sandik.py).
Escort Key: günde bir "Freighter Protection" (radyasyon içinde 10.000 birim yol; istemcinin görevi 500483 sunucuda yok, uyarlama),
seferin seçkin Mimesis'lerinden olasılıkla. En çok 100.
İstemci: PayloadEscortInfoCommand (girişte, durum değişince, haritaya girip çıkınca), PayloadEscortTimeInfoCommand, KeyInfo, ScoreCommand.
Profilde: mimesis {donem, seferler [puan], son (girilen sefer), gun, yol, anahtar_gunu}.
"""
import datetime, json, math, os, random, time

import ayar as AY
import dunya
import etkinlik_kapi as EKP
import harita as H
import kapi as KAPI
import siralama as SR
import takvim as TK
from eski_protokol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'buyuk_icerikler.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('mimesis', {})
EVENT = D.get('etkinlik', 'mimesis_mutiny')
MAPS = {int(v): int(k) for k, v in (D.get('haritalar') or {}).items()}       # harita -> firma
PORTAL_ID = EKP.PORTAL_BASE + 95                   # X-1 / X-8'deki Escort portalı
EXIT_ID = EKP.PORTAL_BASE + 96
FREIGHTER = 'mm_freighter'
POI_ZONE = 'payloadEscortProtectionZone'
RANK_TYPE = 5
KEY = D.get('anahtar', 'resource_key_access-escort')
RUN_SN = 3600
BYTE = 'resource_collectable_byte-remnant'


def _register():
    for k, v in (D.get('turler') or {}).items():
        t = {x: y for x, y in v.items() if x not in ('puan', 'byte')}
        if v.get('byte'):
            t['ek_odul'] = {BYTE: v['byte']}         # wiki aliens: öldürünce doğrudan Byte Remnant (kutudaki ayrıca)
        dunya.CFG['tipler'][k] = t
    g = D.get('gemi')
    if g:
        dunya.CFG['tipler'][FREIGHTER] = dict(ad=g['ad'], model=g['model'], npc_kimlik=g['npc_kimlik'], hp=g['asgari_can'], kalkan=0,
                                              hasar=0, hiz=g['hiz'], saldirgan=False, dost=True, odul={}, kargo={})
    if D.get('siralama'):
        SR.TABLES[RANK_TYPE] = {'araliklar': [dict(den=r['den'], e=r['e'], esyalar=r['oduller'], unvan=r.get('unvan'))
                                              for r in D['siralama']]}


_register()


def active(now=None):
    return EVENT in TK.active(now)


def always_open():
    return bool(AY.get('seans_hep_acik'))


def run_state(now=None):
    """Seferin durumu -> (anahtar, giriş açık mı, giriş kapanışına kalan, sonraki doğmaya kalan, sefer bitişi)."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    if always_open():                                # her giriş yeni bir sefer (bir anahtar)
        return 'hep-%.3f' % now, True, 300 - now % 300, 0, None
    hours = D.get('saatler', [])
    base = t.replace(minute=0, second=0, microsecond=0)
    if t.hour in hours:
        a = base.timestamp()
        key = base.strftime('%Y-%m-%d-%H')
        if now < a + D['giris_sn']:
            return key, True, a + D['giris_sn'] - now, 0, a + D['sure_sn']
    for k in range(1, 48):
        nx = base + datetime.timedelta(hours=k)
        if nx.hour in hours:
            return None, False, 0, nx.timestamp() - now, None
    return None, False, 0, 0, None


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Mimesis:
    def __init__(self, profil, magaza, ekapilar, log=print):
        self.p, self.m, self.k, self.log = profil, magaza, ekapilar, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.in_map = False
        self.last_open = None
        self.last_pos = None

    @property
    def st(self):
        d = self.p.d.setdefault('mimesis', {})
        today = datetime.date.today().isoformat()
        if d.get('gun') != today:
            d.update(gun=today, yol=0)
        for k, v in (('seferler', []), ('yol', 0)):
            d.setdefault(k, v)
        return d

    def total(self):
        return int(sum(sorted(self.st['seferler'], reverse=True)[:D.get('en_iyi_sefer', 10)]))

    def keys(self):
        return int(self.p.resource(KEY))

    # ------------------------------------------------------------ pencere
    def time_cmd(self, now=None):
        key, open_, close_left, next_left, end = run_state(now)
        now = time.time() if now is None else now
        return mod('PayloadEscortTimeInfoCommand', timeToGateClose=int(close_left) if open_ else 0,
                   timeToNextSpawn=int(next_left) if not open_ else 0,
                   timeToSessionEnd=int(end - now) if end else (D['sure_sn'] if open_ else 0))

    def info_cmd(self, in_session=None):
        return ('PayloadEscortInfoCommand', dict(timeInfoCommand=self.time_cmd(), playerRankRanges=SR.ranges(RANK_TYPE),
                                                 totalScore=self.total(), keyInfoCommand=mod('PayloadEscortKeyInfoCommand', keyCount=self.keys()),
                                                 isInSession=bool(self.in_map if in_session is None else in_session)))

    def key_cmd(self):
        return ('PayloadEscortKeyInfoCommand', {'keyCount': self.keys()})

    def login_msgs(self):
        return [self.info_cmd()] if active() else []

    def window(self, item):
        return [self.info_cmd()] if item == 'payload_escort' and active() else []

    # ------------------------------------------------------------ portal
    def my_map(self):
        return next((m for m, f in MAPS.items() if f == self.p.d['pilot'].get('factionId')), None)

    def portals(self, map_id, station):
        if int(map_id) in MAPS or not active() or not station or H.map_class(map_id) not in D.get('girisler', ['X-1', 'X-8']) \
                or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.35), int(sy + (cy - sy) * 0.35 - 1500)
        return [dict(gateId=PORTAL_ID, x=x, y=y, hedef=0, designId=D.get('portal_tasarim', 1), pencere='mimesis',
                     ipucu=D.get('ipucu', 'ttip_jumpgate_escort'))]

    def portal_window(self, g, w, go):
        key, open_, close_left, next_left, end = run_state()
        if not active():
            return
        if not open_:
            w.send([legacy('0|A|STM|msg_mutiny_escort_closed')])
            return
        if self.st.get('son') == key:
            w.send([legacy('0|A|STM|msg_mutiny_escort_too_late')])
            return
        if self.keys() < 1:
            w.send([legacy('0|A|STM|msg_mutiny_escort_no_key')])
            return
        self.p.add_resource(KEY, -1)
        self.p.ach('spend', loot=KEY, adet=1)                      # Pass görevleri: "Escort Key kullan" (savas_bileti.py)
        with self.p.lock:
            self.st['son'] = key
            self.p.dirty = True
        w.send(self.m.resource_msgs(KEY, self.keys(), -1) + [self.key_cmd(), legacy('0|A|STM|resource_key_access-escort_used')])
        self.pending = (key, end)
        x, y = D['rota'][0]
        go(self.my_map(), (x - 600, y + 300))

    # ------------------------------------------------------------ dünya
    def attach(self, world):
        self.world = world
        self.run = None
        msgs = []
        if int(world.map_id) in MAPS and active() and getattr(self, 'pending', None):
            key, end = self.pending
            self.pending = None
            self.run = MmKosu(self, world, end)
            world.kapi = self.run
            world.ally = self.run
            self.in_map = True
            return [self.info_cmd(True)] + self.run.enter_msgs()
        if int(world.map_id) in MAPS:                       # sefer yok (girişte bu haritada doğdu): üsse
            import vortex
            vortex.send_home(self, world)
        if self.in_map:
            self.in_map = False
            msgs.append(self.info_cmd(False))
        return msgs

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        return []

    def tick(self, now):
        if not active(now):
            return self.event_end()
        msgs = []
        if self.st.get('donem') is None:
            with self.p.lock:
                self.st['donem'] = (TK.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        open_ = run_state(now)[1]
        if open_ != self.last_open:
            if self.last_open is not None and open_ and not always_open():
                msgs.append(legacy('0|A|STM|msg_mutiny_escort_spawn_now'))
            self.last_open = open_
            msgs.append(self.info_cmd())
        msgs += self.protection_mission(now)
        return msgs

    def protection_mission(self, now):
        """Günlük "Freighter Protection" (uyarlama): radyasyon içinde 10.000 birim yol -> 1 Escort Key (günde bir)."""
        w = self.world
        st = self.st
        if not w or w.hero_dead or st.get('anahtar_gunu') == st['gun']:
            self.last_pos = None
            return []
        pos = w.hero_pos(now)
        if w.radiation_since is None:
            self.last_pos = None
            return []
        if self.last_pos:
            d = math.hypot(pos[0] - self.last_pos[0], pos[1] - self.last_pos[1])
            if d < 2000:                             # ışınlanma sayılmaz
                with self.p.lock:
                    st['yol'] += d
                    self.p.dirty = True
        self.last_pos = pos
        if st['yol'] < 10000:
            return []
        return self.grant_keys(1, daily=True)

    def grant_keys(self, n, daily=False):
        st = self.st
        have = self.keys()
        n = min(n, D.get('anahtar_azami', 100) - have)
        with self.p.lock:
            if daily:
                st['anahtar_gunu'] = st['gun']
            self.p.dirty = True
        if n > 0:
            self.p.add_resource(KEY, n)
        if n <= 0:
            return []
        self.log('   Mimesis Mutiny: +%d Escort Key%s' % (n, ' (Freighter Protection)' if daily else ''))
        return self.m.resource_msgs(KEY, self.keys(), n) + [self.key_cmd(),
                                                             KAPI.screen('Freighter Protection completed: +1 Escort Key' if daily
                                                                         else '+%d Escort Key' % n)]

    def finish_run(self, score, success):
        msgs = []
        with self.p.lock:
            self.st['seferler'] = sorted(self.st['seferler'] + [int(score)], reverse=True)[:50]
            self.p.dirty = True
        if success:
            row = next((r for r in D['sefer_kademeleri'] if score >= r['den'] and (r['e'] is None or score <= r['e'])), None)
            if row:
                for loot, n in row['oduller']:
                    msgs += self.m.prize(loot, n)
                msgs.append(KAPI.screen('Escort reward tier: %d+ points' % row['den'], big=True))
        msgs.append(('PayloadEscortScoreCommand', dict(totalScore=self.total(), runScore=int(score))))
        self.log('   Mimesis Mutiny seferi bitti: %d puan (%s), toplam %d' % (score, 'başarılı' if success else 'başarısız', self.total()))
        return msgs + self.m.money_msgs()

    def event_end(self):
        st = self.p.d.get('mimesis')
        if not st or st.get('donem') is None:
            return []
        msgs = []
        total = sum(sorted(st.get('seferler', []), reverse=True)[:D.get('en_iyi_sefer', 10)])
        if total > 0:                             # etkinlik sonu sıralama ödülü (tek oyunculu: 1.)
            r = SR.TABLES[RANK_TYPE]['araliklar'][0]
            for loot, n in r['esyalar']:
                msgs += self.m.prize(loot, n)
            if r.get('unvan') and self.titles:
                msgs += self.titles(r['unvan'])
            msgs.append(SR.confirmation(1, SR.PAYLOAD_ESCORT_REWARD, r))
            self.log('   Mimesis Mutiny bitti: toplam %d, 1. sıra ödülü' % total)
        with self.p.lock:
            self.p.d['mimesis'] = {}
            self.p.dirty = True
        return msgs

    def home(self):
        return self.k.home() if self.k else 5


class MmKosu:
    """Escort haritasında sefer (dünyanın 'kapi'sı ve eşlik edilen gemi: dunya.ally)."""
    key = 'mimesis'

    def __init__(self, mode, world, end):
        self.m, self.w = mode, world
        self.g = {'ad': 'Mimesis Mutiny'}
        now = time.time()
        self.end = end or now + D['sure_sn']
        self.leg = 0                                 # sıradaki rota noktası
        self.phase = 'bekle'                         # bekle, yol, nokta, fener, bitti
        self.wave = set()
        self.score = 0
        self.ship = None
        self.next_move = 0.0
        self.next_trickle = now + D['dalgalar']['yol_sn']
        self.disrupted = None
        self.done_at = None
        self.success = False
        import dunya_patronu as WB
        s = WB.scale(mode.p, world, None)           # oyuncunun gücü (donanımın sürekli lazer hasarı / 60.000, 0,25-2,5)
        k = D['tek_oyuncu']
        self.hp_f = k['can'] * s                     # uyarlama (canlı tur): sabit x0,3 / x0,5'te ilk dalga 356.000 canlık gemiyi 25 sn'de
        self.dmg_f = k['hasar'] * max(0.5, min(1.5, s))     # yıkıyordu, oyuncu o sürede bir Mimesis'i bitiremiyordu

    @property
    def npcs(self):
        return set(self.wave)

    def wave_name(self):
        return self.phase

    def enter_msgs(self):
        self.spawn_ship()
        self.spawn_wave(D['dalgalar']['baslangic'], near=D['rota'][0])
        return [self.score_cmd(), self.zone_poi()]

    def score_cmd(self):
        return ('PayloadEscortScoreCommand', dict(totalScore=self.m.total(), runScore=int(self.score)))

    # ------------------------------------------------------------ gemi
    def spawn_ship(self):
        w = self.w
        x, y = D['rota'][0]
        n = w.spawn_npc_at(FREIGHTER, x, y)
        n.gate = True
        n.next_think = time.time() + 10 ** 6
        hp = self.ship_hp()
        n.d = dict(n.d, hp=hp, kalkan=0)
        n.hp, n.shield = hp, 0
        self.ship = n
        w.log('   Mimesis Mutiny: EM Freighter %d can' % hp)

    def ship_hp(self):
        """Gemi en güçlü dalganın ateşine dayanma_sn dayanır (Echoes'un toughen_ally'si; tek oyunculu hasar çarpanıyla)."""
        T = dunya.CFG['tipler']
        waves = D['dalgalar']['noktalar'] + [D['dalgalar']['fener']]
        dps = max(sum(c * float(T.get(t, {}).get('hasar', 0)) for t, c in wv) for wv in waves)
        dps *= self.dmg_f * 0.5 * 0.85 / dunya.SAVAS['npc_saldiri_aralik_sn']
        return int(max(D['gemi']['asgari_can'], dps * D['gemi']['dayanma_sn']))

    def ship_pos(self, now=None):
        return self.ship.mover.pos(time.time() if now is None else now) if self.ship else D['rota'][0]

    def zone_poi(self, now=None):
        x, y = self.ship_pos(now)
        return ('MapAddPOICommand', dict(inverted=True, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=8), shape=0,
                                         active=True, design=mod('POIDesignModule', designValue=10), poiId=POI_ZONE,
                                         shapeCoordinates=[int(x), int(y), int(D['gemi']['koruma_yaricap'])]))

    def safe_at(self, x, y, now):
        """Radyasyon kancası (dunya.radiation_tick): seferde koruma alanının içi, sonra çıkış portalının çevresi güvenli."""
        if self.phase == 'bitti':
            return math.hypot(x - self.exit_x, y - self.exit_y) <= 1500
        sx, sy = self.ship_pos(now)
        return math.hypot(x - sx, y - sy) <= D['gemi']['koruma_yaricap']

    def take_shot(self, n, now):
        """Uzaylının atışı gemiye mi (menzildeyse yarı yarıya; Echoes'un kalıbı) -> True."""
        a, w = self.ship, self.w
        if not a or not a.alive or self.phase == 'bitti' or random.random() > 0.5:
            return False
        ax, ay = a.mover.pos(now)
        nx, ny = n.mover.pos(now)
        if math.hypot(ax - nx, ay - ny) > w.npc_range(n) + 200:
            return False
        n.next_shot = now + n.d.get('atis_aralik_sn', dunya.SAVAS['npc_saldiri_aralik_sn'])
        dmg = int(n.d['hasar'] * random.uniform(0.8, 1.0) * AY.carpan('npc_hasar', 'dalga' if n.hunt else 'harita'))
        a.hp = max(0, a.hp - dmg)
        w.send([('AttackLaserRunCommand', dict(attackerId=n.id, targetId=a.id, laserColor=0, isDiminishedBySkillShield=False,
                                               skilledLaser=False, visualType=0)),
                ('AttackHitCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=1), attackerId=n.id, victimId=a.id,
                                          victimHitpoints=int(a.hp), victimShield=0, victimNanoHull=0, damage=dmg,
                                          skilled=False, strike=False, cannonType=0))])
        if a.hp <= 0:
            a.alive = False
            w.npcs.pop(a.id, None)
            w.send([('ShipDestroyedCommand', dict(destroyedUserId=a.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': a.id})])
            self.fail('msg_mutiny_escort_failed_destroyed')
        return True

    # ------------------------------------------------------------ dalgalar
    def spawn_wave(self, rows, near=None):
        w = self.w
        import pve_ortak as PO
        cx, cy = near or self.ship_pos()
        for tip, count in rows:
            for _ in range(count):
                a, r = random.uniform(0, 2 * math.pi), random.uniform(900, 1600)
                x = min(max(int(cx + math.cos(a) * r), 500), w.map_w - 500)
                y = min(max(int(cy + math.sin(a) * r), 500), w.map_h - 500)
                n = w.spawn_npc_at(tip, x, y, prep=lambda n: PO.scale_npc(n, hp=self.hp_f, dmg=self.dmg_f), dalga=True)
                n.gate, n.engaged, n.hunt = True, True, True
                n.next_think = 0
                self.wave.add(n.id)

    def alive_wave(self):
        return [i for i in self.wave if i in self.w.npcs]

    # ------------------------------------------------------------ döngü
    def tick(self, now):
        w = self.w
        if self.phase == 'bitti':
            if self.done_at and now >= self.done_at + 300 and self.m.change_map and not w.hero_dead:
                self.done_at = None
                w.send([legacy('0|A|STM|msg_mutiny_escort_sent_home')])
                w.later(2.0, lambda: self.m.change_map(self.m.home(), None, 'istasyon'))
            return
        if now >= self.end:
            self.fail('msg_mutiny_escort_failed_time')
            return
        alive = self.alive_wave()
        if self.phase in ('nokta', 'fener'):
            if alive:
                if len(alive) != self.disrupted:
                    self.disrupted = len(alive)
                    w.send([legacy('0|A|STM|msg_mutiny_escort_disrupted|%%AMOUNT%%|%d' % len(alive))])
                return
            self.disrupted = None
            if self.phase == 'fener':
                self.arrive(now)
                return
            self.score += D['nokta_puani']
            w.send([self.score_cmd(), KAPI.screen('Checkpoint %d cleared!' % self.leg)])
            self.phase = 'yol'
        if self.phase == 'bekle':
            self.phase = 'yol'
        if self.phase == 'yol':
            if now >= self.next_trickle:
                self.next_trickle = now + D['dalgalar']['yol_sn']
                self.spawn_wave(D['dalgalar']['yol'])
            self.move(now)

    def move(self, now):
        w, a = self.w, self.ship
        if not a or not a.alive or now < self.next_move:
            return
        hx, hy = w.hero_pos(now)
        ax, ay = a.mover.pos(now)
        if w.hero_dead or math.hypot(hx - ax, hy - ay) > D['gemi']['koruma_yaricap']:
            if a.mover.pos(now) != a.mover.pos(now + 0.5):           # oyuncu alandan çıktı: gemi durur
                a.mover.go(ax, ay, D['gemi']['hiz'], now)
                w.send([('MoveCommand', dict(userId=a.id, x=int(ax), y=int(ay), timeToTarget=0))])
            self.next_move = now + 0.5
            return
        tx, ty = D['rota'][self.leg + 1] if self.leg + 1 < len(D['rota']) else D['rota'][-1]
        d = math.hypot(tx - ax, ty - ay)
        if d < 60:
            self.reach(now)
            return
        step = min(d, 700)
        nx, ny = ax + (tx - ax) * step / d, ay + (ty - ay) * step / d
        ms = a.mover.go(nx, ny, D['gemi']['hiz'], now)
        self.next_move = now + ms / 1000.0
        w.send([('MoveCommand', dict(userId=a.id, x=int(nx), y=int(ny), timeToTarget=ms)), ('MapRemovePOICommand', {'poiId': POI_ZONE}),
                self.zone_poi(now + ms / 2000.0)])

    def reach(self, now):
        self.leg += 1
        w = self.w
        last = self.leg >= len(D['rota']) - 1
        if last:
            self.phase = 'fener'
            self.spawn_wave(D['dalgalar']['fener'])
            w.send([KAPI.screen('The signalling beacon is guarded!', big=True)])
        else:
            self.phase = 'nokta'
            self.spawn_wave(D['dalgalar']['noktalar'][min(self.leg - 1, len(D['dalgalar']['noktalar']) - 1)])
        w.log('   Mimesis Mutiny: nokta %d%s' % (self.leg, ' (fener)' if last else ''))

    def arrive(self, now):
        w, a = self.w, self.ship
        ratio = a.hp / float(max(1, a.d['hp'])) if a and a.alive else 0
        self.score += int(D['varis_bonusu'] * ratio)
        self.success = True
        self.phase = 'varis'                         # 5 sn sonra patlama (zamanlayıcıdan önce: hemen çalışırsa 'bitti' ezilmesin)
        w.send([legacy('0|A|STM|msg_mutiny_escort_succeeded'), self.score_cmd()])

        def boom():
            if a and a.alive:
                a.alive = False
                w.npcs.pop(a.id, None)
                w.send([('ShipDestroyedCommand', dict(destroyedUserId=a.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': a.id})])
            self.end_run(True)
        w.later(5.0, boom)

    def fail(self, key):
        if self.phase in ('bitti', 'varis'):         # varıştan sonra süre dolması başarıyı ikinci kez (başarısız) bitirmesin
            return
        self.w.send([legacy('0|A|STM|%s' % key)])
        self.end_run(False)

    def end_run(self, success):
        w = self.w
        self.phase = 'bitti'
        self.done_at = time.time()
        bx, by = D['rota'][-1]
        self.exit_x, self.exit_y = min(bx, w.map_w - 1500), by
        w.add_gate(dict(gateId=EXIT_ID, x=self.exit_x, y=self.exit_y, hedef=self.m.home(), designId=1, kapi=self.key, cikis=True,
                        varis='istasyon'))
        for i in self.alive_wave():
            n = w.npcs.get(i)
            if n:
                w.send(w.remove_npc(n))
        w.send([('MapRemovePOICommand', {'poiId': POI_ZONE})] + self.m.finish_run(self.score, success))

    def on_kill(self, npc, x, y):
        t = (D.get('turler') or {}).get(npc.tip)
        if not t or self.phase == 'bitti':
            return []
        self.score += t.get('puan', 0)
        msgs = [self.score_cmd()]
        chance = 0.1 if t.get('puan', 0) >= 350 else 0                 # seçkin Mimesis: Escort Key (uyarlama)
        if chance and random.random() < chance:
            msgs += self.m.grant_keys(1)
        return msgs

    # ölüm ekranı: yerinde ücretsiz tamir (kalırsın) ya da üste dönüş
    def on_death(self):
        return None

    def revive(self):
        pass

    def repair_offers(self):
        return {dunya.REPAIR_BASE: 0, dunya.REPAIR_LOCATION: 0}
