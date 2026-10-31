"""World Boss 2025: Treacherous Domain / Dreadfyre Fortress (yol haritası Ö4; veri data/buyuk_icerikler.json 'dunya_patronu').

Takvimde (17 Haziran - 1 Temmuz) günde altı pencere (09, 11, 16, 19, 20, 22; 30 dk; panelin "Seanslı etkinlikler hep açık" ayarıyla
portal hep açık ve savaş girişte başlar): X-1 ve X-8'deki geçici portaldan ücretsiz harita 482. İlk 5 dk hazırlık (Harbinger'lar; Dreadfyre Box: can,
hız, kalkan ya da iyileştirme), sonra Dreadfyre Fortress gelir ve 20 dk kalır:
  evre 1: Fortress hasar almaz, haritanın ortası çevresinde döner (yolundakine çarpma hasarı); 4 Guardian sabit, manyetik alan; ilk
          vuruşta Harbinger çağırır; 1 HP'de "düşer". Dördü düşünce
  evre 2: Fortress vurulabilir; etkin her Guardian %25 hasar azaltma; her 30 sn bir Guardian döner (20 sn ayakta kalan güdümlü roket
          atar); Fortress roket atar, 20 sn'de bir radyasyon patlaması, %80'de halka mayın tarlası; %50'de
  evre 3: harita boyu lazer (10 sn'de bir, 3 sn uyarı), %50 ve %30'da mayın, 30 sn'de iki Guardian döner; %10'da
  evre 4: lazer durur, radyasyon 10 sn'de bir, %10'da mayın, dört Guardian döner ve artık ölür.
Ortadaki şifa feneri saniyede 30.000 can. Öldürülmezse kaçar; harita 5 dk sonra kapanır. Ödüller: savaş başına ilerleme (Fortress'e
verilen hasar canının %10/25/50/75/100'ü; her biri günde 3 kez), etkinlik boyu 20 kademe (toplam hasar, kademe başına savaşın Fortress
canının 0,5-2 katı; 20.'de unvan), son vuruş (777 U, 777 Infiltrator Fragment, 777 UCB-100, Spirefall), savaş sıralaması (tek oyunculu:
kaldırılan can payından sanal sıra; 1. ve Fortress öldüyse Dread Overlord, ilk 10 Dread Warlord). Canlar oyuncunun gücüyle ölçeklenir
(donanımın UCB-100 x6 sürekli hasarı / 60.000, 0,25-2,5). Etkinlik bitince Infiltrator Fragment'ler onura (1:1).
İstemci: PublicWorldBossRequest {action 0} -> PublicWorldBossInfoCommand (pencere 0x82'yi açar), 0,5 sn sonra Raid ve Rank komutları.
Rankings'in Events sayfası: RankingsEventsInfoRequest {rankType 0 bugün, 1 dün, 2 etkinlik} -> WorldBossRankingInfoCommand (yalnız
oyuncunun satırı: puan Fortress'e verilen hasar, sıra o dönemin en iyi sanal savaş sırası, timeTaken saniye: istemci FormatTime(sn)).
Profilde: dunya_patronu {donem, toplam, kademe, h_ref, gun, alinan {kademe: adet}, girdi, gunler {tarih: {hasar, sn, sira}} (bugün ve
dün), etkinlik {hasar, sn, sira}, son (son vuruş anı)}.
"""
import datetime, json, math, os, random, threading, time

import ayar as AY
import dunya
import etkinlik_kapi as EKP
import harita as H
import kapi as KAPI
import takvim as TK
from eski_protokol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'buyuk_icerikler.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('dunya_patronu', {})
EVENT = D.get('etkinlik', 'world_boss')
MAP = D.get('harita', 482)
PORTAL_ID = EKP.PORTAL_BASE + 93           # X-1 / X-8'deki geçici portal
EXIT_ID = EKP.PORTAL_BASE + 94             # haritadaki üsse dönüş
FORTRESS, GUARDIAN, HARBINGER = 'wb_fortress', 'wb_guardian', 'wb_harbinger'
ZONE, TELEGRAPH, BOSS_ESCAPE = 121, 122, 133                      # VisualModifierCommand (istemci: halka, roket işareti, kaçış)
LASER_PREP, LASER_CHARGE, LASER_SHOT = 134, 135, 136
POI_HEAL = 'worldBossHealingBeacon'
AMMO_BONUS = {'ammunition_laser_ucb-100': 6, 'ammunition_laser_rsb-75': 7}     # resmî SSS: etkinlikte UCB-100 x6, RSB-75 x7
WINDOW = 30 * 60


def _register():
    for key, tip in (('dreadfyre_fortress', FORTRESS), ('dreadfyre_guardian', GUARDIAN), ('dreadfyre_harbinger', HARBINGER)):
        a = (D.get('npcler') or {}).get(key)
        if a:
            d = {k: v for k, v in a.items() if k not in ('yorunge_yaricap',)}
            d['cephane_carpani'] = dict(AMMO_BONUS)
            dunya.CFG['tipler'][tip] = d
    if FORTRESS in dunya.CFG['tipler']:
        dunya.CFG['tipler'][FORTRESS]['menzil'] = D['fortress_lazer']['menzil']
        dunya.CFG['tipler'][FORTRESS]['hasar'] = D['fortress_lazer']['hasar']


_register()


def active(now=None):
    return EVENT in TK.active(now)


def _hm(s):
    h, m = s.split(':')
    return int(h), int(m)


def window(now=None):
    """(açık mı, başlangıç, bitiş, sonraki başlangıç)."""
    now = time.time() if now is None else now
    if AY.get('seans_hep_acik'):
        a = now - now % WINDOW
        return True, a, a + WINDOW, a + WINDOW
    t = datetime.datetime.fromtimestamp(now)
    spans = []
    for day in (-1, 0, 1):
        base = (t + datetime.timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        for a, b in D.get('pencereler', []):
            (ah, am), (bh, bm) = _hm(a), _hm(b)
            spans.append((base.replace(hour=ah, minute=am).timestamp(), base.replace(hour=bh, minute=bm).timestamp()))
    spans.sort()
    for a, b in spans:
        if a <= now < b:
            return True, a, b, next((x for x, _ in spans if x > a), a + 86400)
    return False, None, None, next((a for a, _ in spans if a > now), now + 86400)


def mod(_cls, **f):
    f['_'] = _cls
    return f


def rewards(rows):
    return [mod('RewardModule', lootId=l, amount=int(n)) for l, n in rows]


def title_mod(key):
    return mod('RewardTitleModule', titleKey=key) if key else None


class DunyaPatronu:
    REQUESTS = ('PublicWorldBossRequest', 'RankingsEventsInfoRequest')

    def __init__(self, profil, magaza, ekapilar, log=print):
        self.p, self.m, self.k, self.log = profil, magaza, ekapilar, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.send = lambda msgs: None             # kap bağlar (Raid/Rank pencereden sonra)
        self.saved = None                         # haritadan çıkınca süren savaşın durumu (aynı pencerede geri dönülünce sürer)

    @property
    def st(self):
        d = self.p.d.setdefault('dunya_patronu', {})
        today = datetime.date.today().isoformat()
        if d.get('gun') != today:
            d.update(gun=today, alinan={})
        for k, v in (('toplam', 0), ('kademe', 0), ('h_ref', 0), ('alinan', {}), ('girdi', False)):
            d.setdefault(k, v)
        return d

    def h_ref(self):
        """Kademe birimi: son savaşın Fortress etkin canı (henüz yoksa oyuncunun gücüyle hesaplanan)."""
        return self.st['h_ref'] or int(scale(self.p, None) * (D['npcler']['dreadfyre_fortress']['hp'] + D['npcler']['dreadfyre_fortress']['kalkan']))

    def tier_need(self, k):
        row = D['kademe'][k - 1]
        return int(row['carpan'] * self.h_ref())

    # ------------------------------------------------------------ pencere
    def info_cmd(self, now=None):
        now = time.time() if now is None else now
        open_, a, b, nxt = window(now)
        st = self.st
        cur = min(st['kademe'] + 1, len(D['kademe']))
        need = self.tier_need(cur)
        have = need if st['kademe'] >= len(D['kademe']) else st['toplam']
        tiers = [mod('PublicWorldBossTier', rewardModuleList=rewards(r['oduller']), tierName='Tier %d' % r['kademe'], to=r['kademe'],
                     rewardTitleModule=title_mod(r.get('unvan')), **{'from': r['kademe']}) for r in D['kademe']]
        return ('PublicWorldBossInfoCommand', dict(publicWorldBossTierList=tiers, timeToNextRaidSeconds=0 if open_ else max(0, int(nxt - now)),
                                                   raiding=bool(open_ and active(now)),
                                                   timeToEventEndSeconds=int(TK.time_left(EVENT, now)) if active(now) else 0,
                                                   currHealth=int(min(have, need)), maxHealth=int(max(1, need)), currTier=int(st['kademe'])))

    def raid_cmd(self):
        run = self.run
        hp = run.fortress_max() if run else self.h_ref()
        done = run.dealt if run else 0
        return ('PublicWorldBossRaidCommand', dict(raidlist=[
            mod('PublicWorldBossRaidIntensity', currDamage=int(done), maxDamage=int(hp * r['oran']), intensity=r['kademe'],
                claim=int(self.st['alinan'].get(str(r['kademe']), 0)), rewards=rewards(r['oduller']), claimLimit=r['gunluk'])
            for r in D['ilerleme']]))

    def rank_cmd(self):
        return ('PublicWorldBossRankCommand', dict(ranklist=[
            mod('PublicWorldBossRankReward', rewardTitleModule=title_mod((r['unvanlar'] or [None])[0]), to=r['e'], rewards=rewards(r['oduller']),
                **{'from': r['den']}) for r in D['siralama']]))

    def ranking_cmd(self, kind):
        st = self.st
        day = (datetime.date.today() - datetime.timedelta(days=kind)).isoformat()
        row = (st.get('etkinlik') if kind == 2 else st.get('gunler', {}).get(day)) or {}
        me = mod('WorldBossRankingInfoModule', username=self.p.d['pilot'].get('userName', ''), score=min(int(row['hasar']), 2 ** 31 - 1),
                 rank=int(row.get('sira') or D['sanal_sira'][-1][1]), timeTaken=int(row.get('sn', 0))) if row.get('hasar') else None
        return ('WorldBossRankingInfoCommand', dict(isActive=active(), titleStr='', myRank=me, prevRank=None, nextRank=None,
                                                    rankingInfoList=[me] if me else []))

    def tally(self, dmg=0, rank=None):
        """Rankings ve Hall of Fame için: bugünün ve etkinliğin hasarı, savaşta geçen süre (vuruşlar arası 60 sn'den kısaysa), en iyi sıra."""
        now = time.time()
        st = self.st
        today = datetime.date.today()
        with self.p.lock:
            days = st.setdefault('gunler', {})
            for k in [k for k in days if k < (today - datetime.timedelta(days=1)).isoformat()]:
                del days[k]
            for row in (days.setdefault(today.isoformat(), {}), st.setdefault('etkinlik', {})):
                row['hasar'] = row.get('hasar', 0) + dmg
                if dmg and now - st.get('son', 0) < 60:
                    row['sn'] = row.get('sn', 0) + now - st['son']
                if rank:
                    row['sira'] = min(row.get('sira') or rank, rank)
            if dmg:
                st['son'] = now
            self.p.dirty = True

    def handle(self, name, f):
        if name == 'RankingsEventsInfoRequest':
            kind = int(f.get('rankType') or 0)
            return [self.ranking_cmd(kind)] if kind in (0, 1, 2) else []           # 3: Title Frenzy (unvan_avi.py)
        later = [self.raid_cmd(), self.rank_cmd()]
        threading.Timer(0.5, lambda: self.send(later)).start()      # pencere kurulduktan sonra (istemci yoksa sessizce düşürür)
        return [self.info_cmd()]

    # ------------------------------------------------------------ portallar
    def portals(self, map_id, station):
        if int(map_id) == MAP:
            return []
        if not active() or not window()[0] or not station or H.map_class(map_id) not in D.get('girisler', ['X-1', 'X-8']) \
                or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.4), int(sy + (cy - sy) * 0.4 + 1300)
        return [dict(gateId=PORTAL_ID, x=x, y=y, hedef=0, designId=D.get('portal_tasarim', 1), pencere='dunya_patronu',
                     ipucu_hedef=MAP)]                # "This Jump Gate takes you to Treacherous Domain." (istemcinin harita adı)

    def portal_window(self, g, w, go):
        if not active() or not window()[0]:
            w.send([KAPI.screen('Treacherous Domain is closed.')])
            return
        go(MAP, (KAPI.MAP_W // 2 + random.randint(-600, 600), KAPI.MAP_H // 2 + 1500))

    # ------------------------------------------------------------ dünya
    def attach(self, world):
        if self.run and self.run.w is not world and self.run.phase not in ('bitti', 'kapandi'):
            self.saved = self.run.snapshot()              # ölüp üste dönünce ya da çıkınca: savaş sürer (resmî: pencere açıkken geri girilir)
        self.world = world
        self.run = None
        if int(world.map_id) != MAP:
            return []
        open_, a, b, nxt = window()
        if not (open_ and active()):
            import vortex
            vortex.send_home(self, world)                  # pencere kapalı (girişte bu haritada doğdu): üsse
            return []
        s = self.saved if self.saved and time.time() < self.saved['end'] else None
        self.saved = None
        if s:
            a, b = s['start'], s['end']
        elif AY.get('seans_hep_acik'):                    # "hep açık": savaş girişte başlar (5 dk hazırlık, 20 dk patron)
            a, b = time.time(), time.time() + WINDOW
        with self.p.lock:
            self.st['girdi'] = True
            self.p.dirty = True
        self.run = WbKosu(self, world, a, b, restore=s)
        world.kapi = self.run
        return self.run.enter_msgs()

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        return []

    def add_damage(self, dmg):
        """Etkinlik boyu toplam hasar: kademe geçilince ödülleri (oyun içi postası yerine doğrudan)."""
        st = self.st
        msgs = []
        with self.p.lock:
            st['toplam'] += dmg
            self.p.dirty = True
        self.tally(dmg)
        while st['kademe'] < len(D['kademe']) and st['toplam'] >= self.tier_need(st['kademe'] + 1):
            k = st['kademe'] + 1
            with self.p.lock:
                st['toplam'] -= self.tier_need(k)
                st['kademe'] = k
                self.p.dirty = True
            row = D['kademe'][k - 1]
            for loot, n in row['oduller']:
                msgs += self.m.prize(loot, n)
                if loot == D.get('parca', 'resource_collectable_infiltrator-fragment'):
                    self.p.ach('loot', loot=loot, amount=n)         # Treacherous Domain Pass: "Infiltrator Fragment topla" (savas_bileti.py)
            if row.get('unvan') and self.titles:
                msgs += self.titles(row['unvan'])
            msgs += legacy_line('log_msg_worldboss_tier_increase', BOSSNAME='Dreadfyre Fortress', TIER=k)
            self.log('   World Boss kademe %d' % k)
        return msgs

    def tick(self, now):
        if active(now):
            if self.st.get('donem') is None:
                with self.p.lock:
                    self.st['donem'] = (TK.period(EVENT, now) or (now,))[0]
                    self.p.dirty = True
            return []
        st = self.p.d.get('dunya_patronu')
        if not st or st.get('donem') is None:
            return []
        frag = D.get('parca', 'resource_collectable_infiltrator-fragment')
        n = self.p.resource(frag)
        msgs = []
        if n > 0:                                   # etkinlik bitti: kalan parçalar onura (resmî: 24 sa sonra; oran yok, 1:1)
            self.p.add_resource(frag, -n)
            msgs += self.m.money_msgs()
            tot = self.p.gain(onur=n * D.get('parca_onur', 1), neden='worldboss_fragments')
            msgs += legacy_line('history_msg_event_infiltrator_fragment_honor_converted', AMOUNT=n)
            self.log('   World Boss bitti: %d Infiltrator Fragment onura' % n)
        with self.p.lock:
            self.p.d['dunya_patronu'] = {}
            self.p.dirty = True
        return msgs


def legacy_line(key, **params):
    return [legacy('0|A|STM|%s%s' % (key, ''.join('|%%%s%%|%s' % (k, v) for k, v in params.items())))]


def scale(p, w, target=None):
    """Oyuncunun gücü s = donanımın sürekli hasarı (UCB-100 x6) / 60.000, 0,25-2,5 (uyarlama)."""
    g = D['guc']
    if w is None:
        return 1.0
    dummy = target
    try:
        hits = [w.laser_damage('ammunition_laser_ucb-100', dummy)[0] for _ in range(6)]
        dps = sum(hits) / len(hits) * dunya.SAVAS['lazer_isabet'] / dunya.SAVAS['lazer_aralik_sn']
    except Exception:
        dps = g['taban_dps']
    return max(g['asgari'], min(g['azami'], dps / float(g['taban_dps'])))


class WbKosu:
    """Treacherous Domain'de savaş (dünyanın 'kapi'sı)."""
    key = 'dunya_patronu'

    def __init__(self, mode, world, start, end, restore=None):
        self.m, self.w = mode, world
        self.restore = restore
        self.g = {'ad': 'Treacherous Domain'}
        self.start, self.end = start, end
        self.boss_at = start + D['hazirlik_sn']
        self.escape_at = self.boss_at + D['patron_sn']
        if restore:
            self.boss_at, self.escape_at = restore['boss_at'], restore['escape_at']
        self.close_at = min(end, self.escape_at + D['kapanis_sn'])
        self.phase = 'hazirlik'
        self.fortress = None
        self.guardians = []
        self.harbingers = set()
        self.dealt = 0                              # bu savaşta Fortress'e verilen hasar
        self.paid = set()                           # bu savaşta alınan ilerleme kademeleri
        self.mines_done = set()
        self.s = 1.0
        self.next = {}
        self.ended = None
        self.angle = random.uniform(0, 2 * math.pi)
        self.cx, self.cy = world.map_w // 2, world.map_h // 2
        self.laser = None
        self.heal_next = 0.0
        self.closing_sent = False

    @property
    def npcs(self):
        return {n.id for n in ([self.fortress] if self.fortress else []) + self.guardians} | self.harbingers

    def wave(self):
        return self.phase

    def enter_msgs(self):
        w = self.w
        msgs = [poi(POI_HEAL, self.cx, self.cy, D['sifa_feneri']['yaricap'], ptype=4, design=6)]
        w.add_gate(dict(gateId=EXIT_ID, x=self.cx - 2600, y=self.cy + 2200, hedef=self.m.k.home() if self.m.k else 5, designId=1,
                        kapi=self.key, cikis=True, varis='istasyon'))
        r = self.restore
        if r:
            self.dealt, self.paid, self.mines_done = r['dealt'], set(r['paid']), set(r['mines'])
        if time.time() < self.boss_at:
            if not r:
                msgs.append(legacy('0|A|STM|log_msg_worldboss_event_open'))
            self.spawn_harbingers(D['harbinger_hazirlik'])
        else:
            self.spawn_boss(r)
        return msgs

    def snapshot(self):
        """Savaşın durumu (oyuncu haritadan çıkınca; aynı pencerede geri dönünce enter_msgs sürdürür)."""
        f = self.fortress
        return dict(start=self.start, end=self.end, boss_at=self.boss_at, escape_at=self.escape_at, phase=self.phase, s=self.s,
                    dealt=self.dealt, paid=sorted(self.paid),
                    mines=sorted(self.mines_done),
                    fortress=[f.hp / float(max(1, f.d['hp'])), f.shield / float(max(1, f.d['kalkan']))] if f and f.alive else None,
                    guardians=[[g.alive, g.downed, g.hp / float(max(1, g.d['hp']))] for g in self.guardians])

    def fortress_max(self):
        f = self.fortress
        if f:
            return f.d['hp'] + f.d['kalkan']
        return self.m.h_ref()

    def fortress_left(self):
        f = self.fortress
        return (f.hp + f.shield) / float(max(1, self.fortress_max())) if f else 0.0

    # ------------------------------------------------------------ doğurma
    def spot_near(self, x, y, r0, r1):
        a, r = random.uniform(0, 2 * math.pi), random.uniform(r0, r1)
        return (min(max(int(x + math.cos(a) * r), 500), self.w.map_w - 500), min(max(int(y + math.sin(a) * r), 500), self.w.map_h - 500))

    def spawn_harbingers(self, count, near=None):
        w = self.w
        for _ in range(count):
            x, y = self.spot_near(*(near or (self.cx, self.cy)), 400 if near else 2000, 900 if near else 5500)
            n = w.spawn_npc_at(HARBINGER, x, y, prep=lambda n: self.scaled(n))
            n.gate = True
            if near:
                n.engaged, n.next_think = True, 0
            self.harbingers.add(n.id)

    def scaled(self, n):
        """Can oyuncunun gücüyle; lazer hasarı da (0,5-1,5 arası; uyarlama: zayıf gemiye Harbinger sürüsü fazla sertti, canlı tur)."""
        import pve_ortak as PO
        PO.scale_npc(n, hp=self.s, dmg=max(0.5, min(1.5, self.s)))

    def spawn_boss(self, restore=None):
        w = self.w
        if restore and restore.get('fortress'):
            self.s = restore['s']                                # sürdürülen savaş: aynı güç ölçeği
        else:
            probe = w.spawn_npc_at(FORTRESS, self.cx, self.cy)    # gücün ölçümü için hedef (cephane bonusu)
            self.s = scale(self.m.p, w, probe)
            w.remove_npc(probe)
        x, y = self.orbit_point()
        f = w.spawn_npc_at(FORTRESS, x, y, prep=lambda n: self.scaled(n))
        f.gate, f.engaged = True, True
        f.next_think = time.time() + 3600                          # hareketi koşu yönetir (yörünge)
        f.invulnerable = lambda: self.phase in ('hazirlik', 1)
        f.hasar_azaltma = self.fortress_reduction
        f.hasar_kancasi = self.fortress_hit
        self.fortress = f
        with self.m.p.lock:
            self.m.st['h_ref'] = f.d['hp'] + f.d['kalkan']
            self.m.p.dirty = True
        r = D['guardian_uzaklik']
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            gx = min(max(self.cx + dx * r, 800), w.map_w - 800)
            gy = min(max(self.cy + dy * int(r * 0.7), 800), w.map_h - 800)
            g = w.spawn_npc_at(GUARDIAN, gx, gy, prep=lambda n: self.scaled(n))
            g.gate, g.engaged = True, True
            g.downed, g.summoned, g.up_since = False, False, time.time()
            g.can_tabani = 1
            g.tabanda = self.guardian_down
            g.invulnerable = (lambda gg: lambda: gg.downed)(g)
            g.hasar_kancasi = (lambda gg: lambda dmg: self.guardian_hit(gg))(g)
            self.guardians.append(g)
        self.phase = 1
        self.next.update(rocket=0, radiation=time.time() + 20, laser=time.time() + 10, revive=time.time() + 30, move=0, ram=0,
                         field=0, seeker=0)
        if restore and restore.get('fortress'):                   # sürdürülen savaş: canlar, düşmüş ve ölmüş Guardian'lar, evre
            f.hp, f.shield = int(f.d['hp'] * restore['fortress'][0]), int(f.d['kalkan'] * restore['fortress'][1])
            saved = restore['guardians']        # önceki geri dönüşte ölenler süzülmüştü: eksik yuvalar ölü (yoksa fazla Guardian tam canla kalıyordu)
            saved = saved + [[False, False, 0.0]] * (len(self.guardians) - len(saved))
            for g, (alive, downed, ratio) in zip(self.guardians, saved):
                if not alive:
                    w.send(w.remove_npc(g))
                    continue
                g.downed, g.hp = downed, max(1, int(g.d['hp'] * ratio))
                if restore['phase'] == 4:
                    g.can_tabani = 0
            self.guardians = [g for g in self.guardians if g.alive]
            self.phase = restore['phase'] if restore['phase'] in (1, 2, 3, 4) else 1
            w.send([self.field_visual(g, True) for g in self.active_guardians()])
            w.log('   World Boss: savaş sürüyor (evre %s, Fortress %%%d)' % (self.phase, self.fortress_left() * 100))
            return
        w.send([legacy('0|A|STM|log_msg_worldboss_boss_appear')] + [self.field_visual(g, True) for g in self.guardians])
        w.log('   World Boss: Dreadfyre Fortress geldi (güç %.2f, can %d + %d)' % (self.s, f.hp, f.shield))

    def orbit_point(self):
        r = D['npcler']['dreadfyre_fortress'].get('yorunge_yaricap', 2500)
        return int(self.cx + math.cos(self.angle) * r), int(self.cy + math.sin(self.angle) * r * 0.6)

    def field_visual(self, g, on):
        vm = ('VisualModifierCommand', dict(userId=g.id, modifier=ZONE, attribute=D['saldirilar']['manyetik']['yaricap'],
                                            additionalAttribute='', count=1 if on else 0, activated=on))
        g.gorseller = {ZONE: vm} if on else {}   # görüşe girince yeniden (dunya.show): Guardian görüş dışında doğar
        return vm

    # ------------------------------------------------------------ Guardian ve Fortress kuralları
    def active_guardians(self):
        return [g for g in self.guardians if g.alive and not g.downed]

    def fortress_reduction(self):
        return min(1.0, D.get('guardian_kalkan_orani', 0.25) * len(self.active_guardians()))

    def guardian_hit(self, g):
        if not g.summoned:
            g.summoned = True                       # ilk vuruşta Harbinger çağırır
            gx, gy = g.mover.pos(time.time())
            self.spawn_harbingers(D['harbinger_cagri'], near=(gx, gy))

    def guardian_down(self, g):
        if self.phase == 4:
            return
        if not g.downed:
            g.downed = True
            self.w.send([self.field_visual(g, False), KAPI.screen('A Dreadfyre Guardian has fallen.')])
            if self.phase == 1 and not self.active_guardians():
                self.phase = 2
                self.next['revive'] = time.time() + 30
                self.w.send([KAPI.screen('The Fortress is vulnerable!', big=True)])
                self.w.log('   World Boss: evre 2')

    def revive_guardians(self, count):
        down = [g for g in self.guardians if g.alive and g.downed]
        random.shuffle(down)
        msgs = []
        for g in down[:count]:
            g.downed, g.summoned, g.up_since = False, False, time.time()
            g.hp, g.shield = g.d['hp'], g.d['kalkan']
            msgs += [self.field_visual(g, True)]
        if msgs:
            self.w.send(msgs + [KAPI.screen('A Dreadfyre Guardian has returned!')])

    def fortress_hit(self, dmg):
        self.dealt += dmg
        msgs = self.m.add_damage(dmg)
        for r in D['ilerleme']:                     # ilerleme ödülleri: bu savaşta kademe başına bir kez, günde 3 kez
            k = r['kademe']
            if k in self.paid or self.dealt < self.fortress_max() * r['oran']:
                continue
            self.paid.add(k)
            st = self.m.st
            if st['alinan'].get(str(k), 0) >= r['gunluk']:
                continue
            with self.m.p.lock:
                st['alinan'][str(k)] = st['alinan'].get(str(k), 0) + 1
                self.m.p.dirty = True
            for loot, n in r['oduller']:
                msgs += self.m.m.prize(loot, n)
            msgs.append(KAPI.screen('Progress reward %d received!' % k))
        left = self.fortress_left()
        if self.phase == 2 and left <= 0.5:
            self.phase = 3
            self.next['laser'] = time.time() + 5
            msgs.append(legacy('0|A|STM|log_msg_worldboss_half_health|%%BOSSNAME%%|Dreadfyre Fortress'))
            self.w.log('   World Boss: evre 3')
        elif self.phase == 3 and left <= 0.1:
            self.phase = 4
            for g in self.guardians:
                g.can_tabani = 0                      # artık ölür
            self.revive_guardians(4)
            self.next['radiation'] = time.time() + 10
            msgs.append(KAPI.screen('The Guardians have returned for the last time!', big=True))
            self.w.log('   World Boss: evre 4')
        for th in D['mayin_esikleri']:
            if th not in self.mines_done and left <= th and self.phase in (2, 3, 4):
                self.mines_done.add(th)
                self.mine_ring()
        if msgs:
            self.w.send(msgs)

    def mine_ring(self):
        w, f = self.w, self.fortress
        now = time.time()
        fx, fy = f.mover.pos(now)
        m = D['saldirilar']['mayin']
        n = m.get('mayin_sayisi', 24)
        for i in range(n):
            a = 2 * math.pi * i / n
            r = random.uniform(*m.get('halka_yaricap', [1000, 1400]))
            w.items.alien_mine('ammunition_mine_acm-01', fx + math.cos(a) * r, fy + math.sin(a) * r, f.id, now)
        w.log('   World Boss: halka mayın tarlası')

    # ------------------------------------------------------------ döngü
    def tick(self, now):
        w = self.w
        if self.phase == 'kapandi':
            return
        self.heal_tick(now)
        if self.phase == 'hazirlik':
            if now >= self.boss_at:
                for i in list(self.harbingers):
                    n = w.npcs.get(i)
                    if n:
                        w.send(w.remove_npc(n))
                self.harbingers.clear()
                self.spawn_boss()
            return
        if self.phase == 'bitti':
            if now >= self.close_at:
                self.close()
            return
        if now >= self.escape_at:
            self.escape()
            return
        f = self.fortress
        if not f or not f.alive:
            return
        self.move_fortress(now)
        hx, hy = w.hero_pos(now)
        if w.hero_dead:
            return
        maxhp = self.m.p.d['gemi'].get('hitMax', 1)
        sal = D['saldirilar']
        if now >= self.next['field']:               # Guardian manyetik alanı (saniyede)
            self.next['field'] = now + 1.0
            for g in self.active_guardians():
                gx, gy = g.mover.pos(now)
                if math.hypot(hx - gx, hy - gy) <= sal['manyetik']['yaricap']:
                    w.send(w.hurt_hero(int(maxhp * sal['manyetik']['hasar_sn_azami_hp_orani']), g, atype=0))
        fx, fy = f.mover.pos(now)
        if now >= self.next['ram'] and math.hypot(hx - fx, hy - fy) <= sal['carpma']['temas_yaricap']:
            self.next['ram'] = now + sal['carpma']['aralik_sn']
            w.send(w.hurt_hero(int(maxhp * sal['carpma']['hasar_azami_hp_orani']), f, atype=0))
        if self.phase in (2, 3, 4):
            if now >= self.next['rocket'] and math.hypot(hx - fx, hy - fy) <= sal['roket']['menzil'] * AY.carpan('npc_menzil'):
                self.next['rocket'] = now + sal['roket']['aralik_sn']
                w.send([legacy('0|v|%d|%d|H|1|0|0' % (f.id, w.hid))])
                dmg = sal['roket']['hasar']
                w.later(1.0, lambda: (not w.hero_dead) and w.send(w.hurt_hero(dmg, f, atype=0)))
            if now >= self.next['radiation']:
                self.next['radiation'] = now + (10 if self.phase == 4 else 20)
                self.radiation(now)
            if self.phase in (2, 3) and now >= self.next['revive']:
                self.next['revive'] = now + 30
                self.revive_guardians(1 if self.phase == 2 else 2)
            if now >= self.next['seeker']:
                self.next['seeker'] = now + 1.0
                for g in self.active_guardians():
                    if now - g.up_since >= sal['gudumlu']['tekrar_sn']:
                        g.up_since = now
                        self.seeker(g, now)
        if self.phase == 3 and now >= self.next['laser']:
            self.next['laser'] = now + 10
            self.map_laser(now)

    def heal_tick(self, now):
        w = self.w
        if now < self.heal_next or w.hero_dead:
            return
        self.heal_next = now + 1.0
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - self.cx, hy - self.cy) > D['sifa_feneri']['yaricap']:
            return
        g = self.m.p.d['gemi']
        if g.get('hitPoints', 0) >= g.get('hitMax', 0):
            return
        hp0 = g.get('hitPoints', 0)
        self.m.p.set_hull(hp=min(g['hitMax'], hp0 + D['sifa_feneri']['sn_can']))
        w.send([('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0)))])
        self.m.p.ach('wb_heal', adet=g['hitPoints'] - hp0)               # World Boss başarımı (recoverhp)

    def move_fortress(self, now):
        f = self.fortress
        if now < self.next['move']:
            return
        self.angle += 0.35
        x, y = self.orbit_point()
        ms = f.mover.go(x, y, max(60, f.d.get('hiz', 150)), now)
        self.next['move'] = now + ms / 1000.0
        f.next_think = now + 3600
        self.w.send([('MoveCommand', dict(userId=f.id, x=int(x), y=int(y), timeToTarget=ms))])

    def radiation(self, now):
        w, f = self.w, self.fortress
        r = D['saldirilar']['radyasyon']
        w.send([('VisualModifierCommand', dict(userId=f.id, modifier=ZONE, attribute=r['yaricap'], additionalAttribute='', count=1,
                                               activated=True))])

        def burst():
            if not f.alive:
                return
            w.send([('VisualModifierCommand', dict(userId=f.id, modifier=ZONE, attribute=0, additionalAttribute='', count=0,
                                                   activated=False))])
            if w.hero_dead:
                return
            hx, hy = w.hero_pos()
            fx, fy = f.mover.pos(time.time())
            if math.hypot(hx - fx, hy - fy) <= r['yaricap']:
                w.send(w.hurt_hero(int(self.m.p.d['gemi'].get('hitMax', 1) * r['hasar_azami_hp_orani']), f, atype=0))
        w.later(r.get('uyari_sn', 2), burst)

    def seeker(self, g, now):
        w = self.w
        s = D['saldirilar']['gudumlu']
        hx, hy = w.hero_pos(now)
        gx, gy = g.mover.pos(now)
        if math.hypot(hx - gx, hy - gy) > s['menzil'] * AY.carpan('npc_menzil'):      # panel: alien firing range
            return
        w.send([('VisualModifierCommand', dict(userId=g.id, modifier=TELEGRAPH, attribute=0,
                                               additionalAttribute='(%d,%d,0)' % (hx, hy), count=1, activated=True))])

        def hit():
            w.send([('VisualModifierCommand', dict(userId=g.id, modifier=TELEGRAPH, attribute=0, additionalAttribute='', count=0,
                                                   activated=False))])
            if not w.hero_dead and g.alive:
                ex, ey = w.hero_pos()
                if math.hypot(ex - hx, ey - hy) <= 400:               # işaretli noktadan kaçılabilir
                    w.send(w.hurt_hero(int(self.m.p.d['gemi'].get('hitMax', 1) * s['hasar_azami_hp_orani']), g, atype=0))
        w.later(1.2, hit)

    def map_laser(self, now):
        """Fortress'ten kilitli hedefe, harita kenarına dek uzanan ışın: 3 sn uyarı, sonra çizgideki gemiye hasar."""
        w, f = self.w, self.fortress
        L = D['saldirilar']['lazer']
        hx, hy = w.hero_pos(now)
        fx, fy = f.mover.pos(now)
        w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_PREP, attribute=w.hid, additionalAttribute='', count=1,
                                               activated=True))])

        def charge():
            if f.alive:
                w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_CHARGE, attribute=0, additionalAttribute='', count=1,
                                                       activated=True))])

        def shot():
            if not f.alive:
                return
            w.send([('VisualModifierCommand', dict(userId=f.id, modifier=LASER_SHOT, attribute=0,
                                                   additionalAttribute='%d|%d' % (hx, hy), count=1, activated=True))])
            if w.hero_dead:
                return
            ex, ey = w.hero_pos()
            if seg_dist(ex, ey, fx, fy, hx, hy, extend=True) <= L.get('genislik', 250):
                w.send(w.hurt_hero(int(self.m.p.d['gemi'].get('hitMax', 1) * L['hasar_azami_hp_orani']), f, atype=0))
        w.later(L.get('uyari_sn', 3) - 1.0, charge)
        w.later(L.get('uyari_sn', 3), shot)

    # ------------------------------------------------------------ son
    def on_kill(self, npc, x, y):
        w = self.w
        msgs = []
        if npc.id in self.harbingers:
            self.harbingers.discard(npc.id)
            if self.phase == 'hazirlik':
                if random.random() < D.get('kutu_sansi', 0.3):
                    self.buff_box(int(x), int(y))
                w.later(D.get('harbinger_yeniden_sn', 20), lambda: self.phase == 'hazirlik' and self.spawn_harbingers(1))
        elif self.fortress and npc.id == self.fortress.id:
            self.phase, self.ended = 'bitti', 'olum'
            self.close_at = min(self.end, time.time() + D['kapanis_sn'])
            for loot, n in D['son_vurus']['oduller']:
                msgs += self.m.m.prize(loot, n)
            if self.m.titles:
                msgs += self.m.titles(D['son_vurus']['unvan'])
            msgs.append(legacy('0|A|STM|log_msg_worldboss_boss_killed|%%USERNAME%%|%s' % self.m.p.d['pilot'].get('userName', '')))
            msgs.append(KAPI.screen('key:log_msg_gg_completed_world_boss', big=True))
            msgs += self.rank_rewards(1.0)
            self.clear_adds()
            w.log('   World Boss: Fortress yenildi')
        return msgs

    def rank_rewards(self, share):
        rank = next((r for th, r in D['sanal_sira'] if share >= th), None)
        if rank is None:
            return []
        row = next((x for x in D['siralama'] if x['den'] <= rank <= x['e']), None)
        self.m.tally(rank=rank)
        msgs = []
        if row:
            for loot, n in row['oduller']:
                msgs += self.m.m.prize(loot, n)
            for key in row.get('unvanlar') or []:
                if 'rank_1_' in key and self.ended != 'olum':
                    continue                           # 1. sıranın unvanı yalnız Fortress yenildiyse
                if self.m.titles:
                    msgs += self.m.titles(key)
        msgs.append(KAPI.screen('Battle rank: %d' % rank, big=True))
        self.m.log('   World Boss sırası %d (pay %.2f)' % (rank, share))
        return msgs

    def escape(self):
        w, f = self.w, self.fortress
        self.phase, self.ended = 'bitti', 'kacis'
        self.close_at = min(self.end, time.time() + D['kapanis_sn'])
        msgs = [legacy('0|A|STM|log_msg_worldboss_boss_escape')]
        if f and f.alive:
            msgs.append(('VisualModifierCommand', dict(userId=f.id, modifier=BOSS_ESCAPE, attribute=0, additionalAttribute='', count=1,
                                                       activated=True)))
            share = self.dealt / float(max(1, self.fortress_max()))
            w.send(msgs + self.rank_rewards(share))
            w.later(3.0, lambda: f.alive and w.send(w.remove_npc(f)))
        self.clear_adds()
        w.log('   World Boss: Fortress kaçtı')

    def clear_adds(self):
        """Savaş bitti: Guardian'lar ve Harbinger'lar çekilir (ödülsüz)."""
        w = self.w
        for i in [g.id for g in self.guardians] + list(self.harbingers):
            n = w.npcs.get(i)
            if n and n.alive:
                w.send(w.remove_npc(n))
        self.harbingers.clear()

    def close(self):
        w = self.w
        self.phase = 'kapandi'
        w.send([KAPI.screen('Treacherous Domain is closing.', big=True), ('MapRemovePOICommand', {'poiId': POI_HEAL})])
        if self.m.change_map and not w.hero_dead:
            home = self.m.k.home() if self.m.k else 5
            w.later(3.0, lambda: self.m.change_map(home, None, 'istasyon'))

    def buff_box(self, x, y):
        w = self.w
        k = D['kutu']
        h = w.drop_box(k['tur'], x, y, None, k['omur_sn'])
        w.boxes[h]['pet_yok'] = True
        w.boxes[h]['al'] = lambda b: self.buff(random.choice(k['guclendirmeler']))

    def buff(self, kind):
        w, p = self.w, self.m.p
        g = p.d['gemi']
        if kind == 'hiz':
            w.hero_effect('hizlanma', max(60, int(self.close_at - time.time())), int(g.get('speed', 300) * 1.1), source='dreadfyre')
            text = 'Speed boost!'
        elif kind == 'kalkan':
            p.set_hull(shield=min(g.get('shieldMax', 0), g.get('shield', 0) + int(g.get('shieldMax', 0) * 0.15)))
            text = 'Shield boost!'
        elif kind == 'can':
            p.set_hull(hp=min(g.get('hitMax', 0), g.get('hitPoints', 0) + int(g.get('hitMax', 0) * 0.15)))
            text = 'Hull boost!'
        else:
            p.set_hull(hp=min(g.get('hitMax', 0), g.get('hitPoints', 0) + int(g.get('hitMax', 0) * 0.5)))
            text = 'Repaired!'
        return [('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))),
                ('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}),
                KAPI.screen('Dreadfyre Box: ' + text)]

    def on_death(self):
        return None

    def revive(self):
        pass


def seg_dist(px, py, ax, ay, bx, by, extend=False):
    """Noktanın doğru parçasına (extend: a'dan b'ye doğru ışına) uzaklığı."""
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if not L2:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * vx + (py - ay) * vy) / L2
    t = max(0.0, t) if extend else max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def poi(pid, x, y, r, ptype=4, design=6, inverted=False):
    return ('MapAddPOICommand', dict(inverted=inverted, poiTypeSpecification='', poiType=mod('POITypeModule', typeValue=ptype), shape=0,
                                     active=True, design=mod('POIDesignModule', designValue=design), poiId=pid,
                                     shapeCoordinates=[int(x), int(y), int(r)]))
