"""Kristallon Apotheosis (istemci 1.1.115; veri data/major_content.json 'kristallon_apotheosis' <- tools/version_115.py).

Takvimde (21 Ekim 2026 - 2027 sonu: resmî sunucu kaydı) pazartesi-cumartesi üç toplama penceresi (08-10, 14-16, 20-22; panelin
"Seanslı etkinlikler hep açık" ayarıyla iki saatlik dilimlerle hep açık): X-2..X-8'de etkinlik uzaylıları (Icy, Kristallon, Boss
Kristallon kopyaları; harita sınıfına göre puan) öldürülerek hedef puan toplanır. Hedefe ulaşınca uzaylılar çekilir, 1-1 / 2-1 /
3-1'de portal (tasarım 307) açılır: harita 510'da 5 dk bekleme, sonra Emperor Kristallon (EMPEROR_KRISTALLON_BOSS_2, npcId 518)
30 dk kalır. Saldırıları istemcinin efektleriyle (VisualModifierCommand, istemcinin VisualModifierAssemblyHelper'ı):
  evre 1 (%100-66): yarık (159, etkin; additionalAttribute "x1|y1|x2|y2": patrondan oyuncunun konumuna ve öteye çizgi; istemci 2,1 +
          2 sn sonra patlatır): çizgideki gemiye canının %20'si
  evre 2 (%66-33): + buz (158, attribute oyuncu; 2,2 sn): menzildeki oyuncuya hasar ve yavaşlama (istemci oyuncunun üstünde çizer)
  evre 3 (%33-0): + radyasyon (160 oyuncunun üstünde, "x|y" güvenli nokta: kılavuz oku): süre dolunca güvenli alanın dışına hasar
Ölmek savaşı bitirmez (üsse döner; portal açıkken geri girilir, patron kaldığı canla). Yenilince: katılım ödülü (patron seviyesinin
satırı), yenilgi ödülü (tablodan tek eşya), 20 Apotheosis Booty Box (anahtarla; loot.py APOTHEOSIS), son vuruş (unvan, 1 anahtar),
patron seviyesi +1 (en çok 12). Kaçarsa yalnız katılım ödülü (hasar patron canının %1'ini geçtiyse). Hafta pazartesi sıfırlanır
(seviye 1); önceki haftanın sanal sırasının ödülleri (yenilgi sayısından) o an verilir.
Pencere (menü öğesi 'apotheosis', istemcide UIDarkMatterWar): açılınca ApotheosisProgressRequest -> ApotheosisProgressCommand {phase
0 WAITING / 1 COLLECTING / 2 BOSS, currentPoints / totalPoints, remainingSeconds, hpPercent, bossLevel, katılım / yenilgi / son vuruş
ödülleri (LootProbabilityModule), haftalık sıra}. HUD'daki anahtar sayacı "0|A|BKAPO|n".
Profilde: apotheosis {hafta, seviye, puan, pencere, durum (toplama / patron / bitti), patron_basi, yenilgi, katilim, son_vurus, hasar}.
"""
import datetime, json, math, os, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as KAPI
import pve_common as PS
import event_calendar as CAL
from world_boss import mod, rewards, scale, seg_dist
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('kristallon_apotheosis', {})
EVENT = D.get('etkinlik', 'kristallon_apotheosis')
MAP = D.get('harita', 510)
PORTAL_ID = EKP.PORTAL_BASE + 97           # 1-1 / 2-1 / 3-1'deki patron portalı
EXIT_ID = EKP.PORTAL_BASE + 98             # haritadaki üsse dönüş
BOSS = 'apo_emperor'
ICE, RIFT, GUIDE = 158, 159, 160
WAITING, COLLECTING, FIGHT = 0, 1, 2       # ApotheosisProgressCommand.phase (istemcinin Phase enum'u)
SLICE = 2 * 3600                           # seans_hep_acik: pencere dilimi
KEY = 'resource_booty-key-apotheosis'


def _register():
    T = world_module.CFG['types']
    for rows in D.get('collecting', {}).values():
        for tip, _, _ in rows:
            if tip in T:
                # model: tür anahtarı modelin kendisi olan türlerde (79, 35) kopyanın adı ("apo_79") istemcide çizilmiyordu
                T['apo_' + tip] = dict({k: v for k, v in T[tip].items() if k not in ('haritalar', 'etkinlik')}, model=T[tip].get('model', tip))
    if D.get('boss'):
        T[BOSS] = dict(D['boss'])


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def _hm(s):
    h, m = s.split(':')
    return int(h), int(m)


def window(now=None):
    """(açık mı, başlangıç, bitiş, sonraki başlangıç): pazartesi-cumartesi pencereleri; seans_hep_acik: iki saatlik dilimler."""
    now = time.time() if now is None else now
    if SET.get('session_always_open'):
        a = now - now % SLICE
        return True, a, a + SLICE, a + SLICE
    t = datetime.datetime.fromtimestamp(now)
    spans = []
    for day in range(-1, 3):
        base = (t + datetime.timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        if base.weekday() not in D.get('days', range(7)):
            continue
        for a, b in D.get('windows', []):
            (ah, am), (bh, bm) = _hm(a), _hm(b)
            spans.append((base.replace(hour=ah, minute=am).timestamp(), base.replace(hour=bh, minute=bm).timestamp()))
    spans.sort()
    for a, b in spans:
        if a <= now < b:
            return True, a, b, next((x for x, _ in spans if x > a), a + 86400)
    return False, None, None, next((a for a, _ in spans if a > now), now + 86400)


def week_id(now=None):
    y, w, _ = datetime.date.fromtimestamp(time.time() if now is None else now).isocalendar()
    return '%d-W%02d' % (y, w)


def week_end(now=None):
    """Haftanın sıfırlandığı an: sonraki pazartesi 00:00."""
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    return datetime.datetime.combine(d + datetime.timedelta(days=7 - d.weekday()), datetime.time()).timestamp()


def probs(rows):
    return [mod('LootProbabilityModule', lootId=l, probabilityPercentage=float(p), minLootAmount=int(n), maxLootAmount=int(n))
            for l, n, p in rows]


def virtual_rank(kills):
    return next((r for need, r in D.get('virtual_rank', []) if kills >= need), None)


def rank_row(rank):
    return next((x for x in D.get('ranking', []) if rank and x['den'] <= rank <= x['e']), None)


class Apotheosis:
    REQUESTS = ('ApotheosisProgressRequest',)

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.run = None
        self.change_map = None
        self.titles = None
        self.saved = None                       # haritadan çıkınca patronun durumu (portal açıkken geri girilince sürer)
        self.spawned = set()                    # bu haritanın toplama uzaylıları

    @property
    def st(self):
        return self.p.d.setdefault('apotheosis', {})

    def level(self):
        return min(max(1, self.st.get('seviye', 1)), len(D['participation']))

    # ------------------------------------------------------------ durum
    def ensure(self, now=None):
        """Hafta ve pencere değişimleri -> mesajlar (haftanın sırası ödülleri, toplamanın başı ve sonu)."""
        now = time.time() if now is None else now
        st, msgs = self.st, []
        wk = week_id(now)
        if st.get('hafta') != wk:
            if st.get('hafta'):
                msgs += self.week_rewards()
            with self.p.lock:
                st.update(hafta=wk, seviye=1, defeats=0, participation=0, last_hit=0, hasar=0)
                self.p.dirty = True
        open_, a, b, nxt = window(now)
        if open_ and st.get('windowed') != a:
            with self.p.lock:
                st.update(windowed=a, puan=0, durum='collecting')
                self.p.dirty = True
            self.saved = None
            msgs.append(legacy('0|A|STM|kristallon_apotheosis_start_event'))
            self.log('   Kristallon Apotheosis: toplama başladı')
        elif st.get('durum') == 'collecting' and not open_:
            with self.p.lock:
                st['durum'] = 'finished'
                self.p.dirty = True
            msgs.append(legacy('0|A|STM|kristallon_apotheosis_not_completed'))
        elif st.get('durum') == 'boss' and now >= st.get('boss_start', 0) + D['bekleme_sn'] + D['combat_sec'] + D['closing_sec'] \
                and not (self.run and self.run.phase not in ('finished', 'closed')):
            with self.p.lock:
                st['durum'] = 'finished'
                self.p.dirty = True
        return msgs

    def phase(self):
        return {'collecting': COLLECTING, 'boss': FIGHT}.get(self.st.get('durum'), WAITING)

    def week_rewards(self):
        """Biten haftanın sanal sırası (tek oyunculu: yenilgi sayısından) -> ödüller ve unvan."""
        rank = virtual_rank(self.st.get('defeats', 0))
        row = rank_row(rank)
        if not row:
            return []
        msgs = []
        for loot, n in row['rewards']:
            msgs += self.m.prize(loot, n)
        if self.titles:
            msgs += self.titles(row['title'])
        msgs.append(KAPI.screen('Kristallon Apotheosis weekly rank: %d' % rank, big=True))
        self.log('   Kristallon Apotheosis haftalık sıra %d' % rank)
        return msgs

    # ------------------------------------------------------------ pencere
    def progress_cmd(self, now=None):
        now = time.time() if now is None else now
        st = self.st
        open_, a, b, nxt = window(now)
        ph = self.phase() if active(now) else WAITING
        if ph == COLLECTING:
            left = b - now
        elif ph == FIGHT:
            left = st.get('boss_start', now) + D['bekleme_sn'] + D['combat_sec'] - now
        else:
            left = (nxt if not open_ else b) - now
        lv = self.level()
        kills = st.get('defeats', 0)
        rank = virtual_rank(kills)
        row = rank_row(rank)
        me = mod('ApotheosisRankingEntryModule', userId=self.p.user_id, name=self.p.d['pilot'].get('userName', ''),
                 damage=int(st.get('hasar', 0)), rewards=rewards(row['rewards']) if row else [])
        cap = D.get('weekly_limit', {})                     # resmî sunucu kaydı: katılım 3, yenilgi 3, son vuruş 18
        return ('ApotheosisProgressCommand', dict(
            phase=ph, currentPoints=int(min(st.get('puan', 0), D['target_points'])), totalPoints=int(D['target_points']),
            remainingSeconds=max(0, int(left)), hpPercent=int(round(self.boss_left() * 100)), bossLevel=lv,
            rewardStatusIncluded=True, nextResetTime=int(week_end(now) * 1000),     # sıfırlanma anı, ms (kayıt)
            timeToEventEndSeconds=int(CAL.time_left(EVENT, now)) if active(now) else 0,
            participationReward=mod('ApotheosisRewardModule', rewards=probs([r + [100] for r in D['participation'][lv - 1]]),
                                    claimedCount=int(st.get('participation', 0)), weeklyLimit=cap.get('participation', 0)),
            victoryReward=mod('ApotheosisRewardModule', rewards=probs(D['defeats']), claimedCount=int(kills),
                              weeklyLimit=cap.get('defeats', 0)),
            lastHitReward=mod('ApotheosisRewardModule', rewards=probs([r + [100] for r in D['last_hit']['rewards']]
                                                                       + [[D['last_hit']['title'], 1, 100]]),     # unvan da (kayıt)
                              claimedCount=int(st.get('last_hit', 0)), weeklyLimit=cap.get('last_hit', 0)),
            weeklyRanking=[me] if st.get('hasar') else []))

    def boss_left(self):
        if self.run and self.run.boss and self.run.boss.alive:
            return self.run.left()
        if self.saved:
            return self.saved['oran']
        return 1.0

    def handle(self, name, f):
        self.ensure()
        return [self.progress_cmd()]

    # ------------------------------------------------------------ toplama
    def add_points(self, n):
        st = self.st
        if st.get('durum') != 'collecting':
            return []
        with self.p.lock:
            st['puan'] = st.get('puan', 0) + n
            self.p.dirty = True
        if st['puan'] < D['target_points']:
            return []
        with self.p.lock:
            st.update(durum='boss', boss_start=time.time())
            self.p.dirty = True
        self.saved = None
        self.log('   Kristallon Apotheosis: hedef puan, portallar açıldı')
        return [legacy('0|A|STM|kristallon_apotheosis_start_portal'), KAPI.screen('key:kristallon_apotheosis_start_portal', big=True)]

    def collect_rows(self, world):
        return D.get('collecting', {}).get(H.map_class(world.map_id), [])

    def spawn_collect(self, world, tip=None, pts=None, count=1):
        """Toplama uzaylıları (haritanın satırları; tip verilirse yalnız o türden count tane)."""
        g = D['power'].get(H.map_class(world.map_id), 1.0)
        rows = [[tip, pts, count]] if tip else self.collect_rows(world)
        for t, p, n in rows:
            for _ in range(n):
                x, y = world.random_spot()
                npc = world.spawn_npc_at('apo_' + t, x, y, prep=lambda c: PS.scale_npc(c, hp=g, dmg=g, reward=g))
                npc.gate, npc.apo = True, (t, p)
                self.spawned.add(npc.id)

    def clear_collect(self):
        w = self.world
        if not w:
            return
        for i in list(self.spawned):
            n = w.npcs.get(i)
            if n and n.alive:
                w.send(w.remove_npc(n))
        self.spawned.clear()

    # ------------------------------------------------------------ portallar
    def portals(self, map_id, station):
        if int(map_id) == MAP or not station or H.name(map_id) not in D.get('entries', []):
            return []
        self.ensure()
        if not active() or self.st.get('durum') != 'boss':
            return []
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        x, y = int(sx + (cx - sx) * 0.35), int(sy + (cy - sy) * 0.35 - 1200)
        return [dict(gateId=PORTAL_ID, x=x, y=y, hedef=0, designId=D.get('portal_design', 307), windowed='apotheosis',
                     hint_target=MAP)]

    def portal_window(self, g, w, go):
        self.ensure()
        if not active() or self.st.get('durum') != 'boss':
            w.send([legacy('0|A|STM|kristallon_apotheosis_not_enabled')])
            return
        go(MAP, (KAPI.MAP_W // 2 + random.randint(-800, 800), KAPI.MAP_H // 2 + 2500))

    # ------------------------------------------------------------ dünya
    def attach(self, world):
        if self.run and self.run.w is not world and self.run.boss and self.run.boss.alive:
            self.saved = self.run.snapshot()
        self.world = world
        self.run = None
        self.spawned = set()
        msgs = self.ensure()
        if int(world.map_id) == MAP:
            if not active() or self.st.get('durum') != 'boss':
                import vortex
                vortex.send_home(self, world)              # savaş yok (girişte bu haritada doğdu): üsse
                return msgs
            self.run = ApoRun(self, world, self.saved)
            self.saved = None
            world.gate = self.run
            return msgs + self.run.enter_msgs()
        if active() and self.st.get('durum') == 'collecting' and self.collect_rows(world):
            self.spawn_collect(world)
        return msgs

    def on_kill(self, w, npc, x, y):
        if self.run and self.run.w is w:
            return self.run.on_kill(npc, x, y)
        if npc.id not in self.spawned:
            return []
        self.spawned.discard(npc.id)
        tip, pts = npc.apo
        msgs = [KAPI.screen('Kristallon Apotheosis: +%d (%d/%d)' % (pts, min(self.st.get('puan', 0) + pts, D['target_points']),
                                                                 D['target_points']))] if self.st.get('durum') == 'collecting' else []
        msgs += self.add_points(pts)
        if self.st.get('durum') == 'collecting':
            w.later(D.get('renew_sec', 15), lambda: self.world is w and self.st.get('durum') == 'collecting'
                    and self.spawn_collect(w, tip, pts))
        else:
            self.clear_collect()
        return msgs

    def tick(self, now):
        if not active(now):
            return []
        before = self.st.get('durum')
        msgs = self.ensure(now)
        w = self.world
        if w and before != self.st.get('durum') and w.gate is None:
            if self.st.get('durum') == 'collecting' and self.collect_rows(w):
                self.spawn_collect(w)                    # oyuncu bir X-2..X-8 haritasındayken pencere açıldı
            elif before == 'collecting':
                self.clear_collect()
        return msgs

    def boss_defeated(self, last_hit=True):
        """Yenilgi: sayaçlar, ödüller (kutular koşuda; yenilgi ve son vuruş ödülü haftalık sınıra kadar), seviye."""
        st, msgs = self.st, []
        lv = self.level()
        cap = D.get('weekly_limit', {})
        with self.p.lock:
            st['defeats'] = st.get('defeats', 0) + 1
            st['seviye'] = min(len(D['participation']), lv + 1)
            win = st['defeats'] <= cap.get('defeats', st['defeats'])
            last_hit = last_hit and st.get('last_hit', 0) < cap.get('last_hit', st.get('last_hit', 0) + 1)
            if last_hit:
                st['last_hit'] = st.get('last_hit', 0) + 1
            self.p.dirty = True
        loot, n, _ = random.choices(D['defeats'], [r[2] for r in D['defeats']])[0]
        if win:
            msgs += self.m.prize(loot, n)
        if last_hit:
            k0 = self.p.resource(KEY)
            for l, k in D['last_hit']['rewards']:
                msgs += self.m.prize(l, k)
            msgs += self.key_msgs(self.p.resource(KEY) - k0)          # panelin ödül çarpanıyla gelen adet
            if self.titles:
                msgs += self.titles(D['last_hit']['title'])
        self.log('   Kristallon Apotheosis: patron yenildi (seviye %d), %s' % (lv, 'yenilgi ödülü %s x%d' % (loot, n) if win else
                                                                            'yenilgi ödülünün haftalık sınırı doldu'))
        return msgs

    def participation(self, lv):
        """Katılım ödülü (haftalık sınıra kadar)."""
        st, msgs = self.st, []
        with self.p.lock:
            if st.get('participation', 0) >= D.get('weekly_limit', {}).get('participation', st.get('participation', 0) + 1):
                return msgs
            st['participation'] = st.get('participation', 0) + 1
            self.p.dirty = True
        for loot, n in D['participation'][lv - 1]:
            msgs += self.m.prize(loot, n)
        return msgs

    def key_msgs(self, n):
        """Anahtar alındı: istemcinin metni (HUD sayacını mağazanın ödül işlevi gönderir)."""
        if n < 1:
            return []
        text = 'msg_booty-key-apotheosis_received_s' if n == 1 else 'msg_booty-key-apotheosis_received_p|%%AMOUNT%%|%d' % n
        return [legacy('0|A|STM|' + text)]

    def login_msgs(self):
        """HUD'daki anahtar sayacı (kayıttaki giriş demetinde BKAPO satırı yok: 1.1.115'le geldi)."""
        return [legacy('0|A|BKAPO|%d' % self.p.resource(KEY))]


class ApoRun:
    """Harita 510'da patron savaşı (dünyanın 'kapi'sı)."""
    key = 'kristallon_apotheosis'

    def __init__(self, mode, world, restore=None):
        self.m, self.w = mode, world
        self.g = {'ad': 'Kristallon Apotheosis'}
        st = mode.st
        self.boss_at = st.get('boss_start', time.time()) + D['bekleme_sn']
        if SET.get('session_always_open'):
            self.boss_at = min(self.boss_at, time.time() + 30)      # hep açık: kısa bekleme
        self.end = self.boss_at + D['combat_sec']
        if restore:                                  # savaş sürüyordu: patron hemen, kaldığı canla ve süresiyle
            self.boss_at, self.end = time.time(), restore['bitis']
        self.close_at = None
        self.phase = 'cooldown'
        self.boss = None
        self.s = 1.0
        self.stage = 1
        self.dealt = restore['hasar'] if restore else 0
        self.restore = restore
        self.lv = mode.level()
        self.next = {}
        self.cx, self.cy = world.map_w // 2, world.map_h // 2
        self.guide = None

    def wave(self):
        return self.phase

    def enter_msgs(self):
        self.w.add_gate(dict(gateId=EXIT_ID, x=self.cx - 3000, y=self.cy + 2400, hedef=self.m.k.home() if self.m.k else 5,
                             designId=1, kapi=self.key, cikis=True, arrival='istasyon'))
        if time.time() >= self.boss_at:
            self.spawn_boss()
            return []
        return [KAPI.screen('Emperor Kristallon arrives in %d s.' % max(1, int(self.boss_at - time.time())), big=True)]

    def snapshot(self):
        b = self.boss
        return dict(oran=self.left(), hp=b.hp / float(max(1, b.d['hp'])), kalkan=b.shield / float(max(1, b.d['kalkan'])),
                    hasar=self.dealt, s=self.s, bitis=self.end)

    def boss_max(self):
        return self.boss.d['hp'] + self.boss.d['kalkan']

    def left(self):
        b = self.boss
        return (b.hp + b.shield) / float(max(1, self.boss_max())) if b else 1.0

    def spawn_boss(self):
        w, r = self.w, self.restore
        if r:
            self.s = r['s']
        else:
            probe = w.spawn_npc_at(BOSS, self.cx, self.cy)
            self.s = scale(self.m.p, w, probe) * (1 + D.get('level_multiplier', 0.15) * (self.lv - 1))
            w.remove_npc(probe)
        b = w.spawn_npc_at(BOSS, self.cx, self.cy - 800, prep=lambda n: PS.scale_npc(n, hp=self.s, dmg=max(0.5, min(1.5, self.s))))
        b.gate, b.engaged = True, True
        b.damage_hook = self.boss_hit
        if r:
            b.hp, b.shield = max(1, int(b.d['hp'] * r['hp'])), int(b.d['kalkan'] * r['kalkan'])
        self.boss = b
        self.phase = 'savas'
        now = time.time()
        self.next.update(rift=now + 8, ice=now + 12, radiation=now + 15)
        self.stage = next(i for i, th in reversed(list(enumerate(D['phases'], 1))) if self.left() <= th)
        w.send([KAPI.screen('Emperor Kristallon has appeared!', big=True)])
        w.log('   Kristallon Apotheosis: Emperor Kristallon geldi (seviye %d, güç %.2f, can %d + %d)' % (self.lv, self.s, b.hp, b.shield))

    def boss_hit(self, dmg):
        self.dealt += dmg
        with self.m.p.lock:
            self.m.st['hasar'] = self.m.st.get('hasar', 0) + dmg
            self.m.p.dirty = True
        left = self.left()
        for i, th in enumerate(D['phases'][1:], 2):
            if self.stage < i and left <= th:
                self.stage = i
                self.w.send([KAPI.screen('Emperor Kristallon: phase %d!' % i, big=True)])
                self.w.log('   Kristallon Apotheosis: evre %d' % i)

    # ------------------------------------------------------------ döngü
    def tick(self, now):
        w = self.w
        if self.phase == 'closed':
            return
        if self.phase == 'cooldown':
            if now >= self.boss_at:
                self.spawn_boss()
            return
        if self.phase == 'finished':
            if now >= self.close_at:
                self.close()
            return
        if now >= self.end:
            self.escape()
            return
        b = self.boss
        if not b or not b.alive or w.hero_dead:
            return
        attacks = D['attacks']
        if now >= self.next['rift']:
            self.next['rift'] = now + attacks['rift']['interval_sec']
            self.rift(now)
        if self.stage >= 2 and now >= self.next['ice']:
            self.next['ice'] = now + attacks['ice']['interval_sec']
            self.ice(now)
        if self.stage >= 3 and now >= self.next['radiation'] and not self.guide:
            self.next['radiation'] = now + attacks['radiation']['interval_sec']
            self.radiation(now)

    def vm(self, uid, modifier, on, attr=0, extra=''):
        return ('VisualModifierCommand', dict(userId=uid, modifier=modifier, attribute=attr, additionalAttribute=extra,
                                              count=1 if on else 0, activated=on))

    def max_hp(self):
        return self.m.p.d['gemi'].get('hitMax', 1)

    def rift(self, now):
        """Yarık: patrondan oyuncunun konumuna ve öteye çizgi; istemci 4,1 sn'de patlatır, çizgideki gemi hasar alır."""
        w, b, R = self.w, self.boss, D['attacks']['rift']
        bx, by = b.mover.pos(now)
        hx, hy = w.hero_pos(now)
        d = math.hypot(hx - bx, hy - by) or 1.0
        ex, ey = bx + (hx - bx) / d * R['length'], by + (hy - by) / d * R['length']
        w.send([self.vm(b.id, RIFT, True, extra='%d|%d|%d|%d' % (bx, by, ex, ey))])

        def burst():
            w.send([self.vm(b.id, RIFT, False)])
            if b.alive and not w.hero_dead:
                px, py = w.hero_pos()
                if seg_dist(px, py, bx, by, ex, ey) <= R['width']:
                    w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
        w.later(R['warning_sec'], burst)

    def ice(self, now):
        """Buz: patronun menzilindeki oyuncuya atılır (istemci patlamayı oyuncunun üstünde, onunla birlikte çizer); 2,2 sn sonra
        hasar ve yavaşlama."""
        w, b, R = self.w, self.boss, D['attacks']['ice']
        bx, by = b.mover.pos(now)
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - bx, hy - by) > R['yaricap']:
            return
        w.send([self.vm(b.id, ICE, True, attr=w.hid)])

        def burst():
            w.send([self.vm(b.id, ICE, False)])
            if b.alive and not w.hero_dead:
                w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
                w.hero_effect('slow', R['slow'][1], R['slow'][0], source='apotheosis')
        w.later(R['warning_sec'], burst)

    def radiation(self, now):
        """Radyasyon: oyuncunun üstünde kılavuz (güvenli noktaya ok); süre dolunca güvenli alanın dışı hasar alır."""
        w, b, R = self.w, self.boss, D['attacks']['radiation']
        a = random.uniform(0, 2 * math.pi)
        sx = min(max(int(self.cx + math.cos(a) * 3000), 800), w.map_w - 800)
        sy = min(max(int(self.cy + math.sin(a) * 2000), 800), w.map_h - 800)
        self.guide = (sx, sy)
        w.send([self.vm(w.hid, GUIDE, True, extra='%d|%d' % (sx, sy)), KAPI.screen('Radiation surge! Reach the safe zone.', big=True)])

        def burst():
            self.guide = None
            w.send([self.vm(w.hid, GUIDE, False)])
            if b.alive and not w.hero_dead:
                px, py = w.hero_pos()
                if math.hypot(px - sx, py - sy) > R['safe_radius']:
                    w.send(w.hurt_hero(int(self.max_hp() * R['damage_max_hp_ratio']), b, atype=0))
        w.later(R['warning_sec'], burst)

    # ------------------------------------------------------------ son
    def on_kill(self, npc, x, y):
        if not self.boss or npc.id != self.boss.id:
            return []
        w = self.w
        self.phase = 'finished'
        self.close_at = time.time() + D['closing_sec']
        msgs = self.m.participation(self.lv) + self.m.boss_defeated(last_hit=True)
        k = D['kutu']
        for i in range(k['adet']):
            a = 2 * math.pi * i / k['adet']
            r = 250 + 120 * (i % 3)
            w.drop_box(k['tur'], x + math.cos(a) * r, y + math.sin(a) * r, None, k['omur_sn'])
        msgs += [legacy('0|A|STM|kristallon_apotheosis_finisher|%%PLAYER%%|%s' % self.m.p.d['pilot'].get('userName', '')),
                 legacy('0|A|STM|kristallon_apotheosis_completed'), KAPI.screen('key:kristallon_apotheosis_completed', big=True)]
        with self.m.p.lock:
            self.m.st['durum'] = 'finished'
            self.m.p.dirty = True
        w.log('   Kristallon Apotheosis: Emperor Kristallon yenildi')
        return msgs

    def escape(self):
        w, b = self.w, self.boss
        self.phase = 'finished'
        self.close_at = time.time() + D['closing_sec']
        msgs = [KAPI.screen('Emperor Kristallon has escaped.', big=True)]
        if b and self.dealt >= self.boss_max() * D.get('participation_threshold', 0.01):
            msgs += self.m.participation(self.lv)
        if b and b.alive:
            w.send(w.remove_npc(b))
        with self.m.p.lock:
            self.m.st['durum'] = 'finished'
            self.m.p.dirty = True
        w.send(msgs)
        w.log('   Kristallon Apotheosis: patron kaçtı')

    def close(self):
        w = self.w
        self.phase = 'closed'
        w.send([KAPI.screen('Kristallon Apotheosis is closing.', big=True)])
        if self.m.change_map and not w.hero_dead:
            home = self.m.k.home() if self.m.k else 5
            w.later(3.0, lambda: self.m.change_map(home, None, 'istasyon'))

    def on_death(self):
        return None

    def revive(self):
        pass
