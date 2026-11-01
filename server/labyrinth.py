"""Frozen Labyrinth (yol haritası Aşama 7b; veri data/event_gates.json "labirent" <- tools/event_gates.py).

Kış etkinliğinde (event_calendar.py 'labirent') X-1'deki portaldan rastgele ATLAS A, B ya da C'ye (430-432) girilir. 16 harita (430-445,
istemcide scaleFactor 2), her biri dört duvarlı bölge (TL 0, TR 1, BL 2, BR 3). Her bölgenin dört köşesinde başka haritanın bir
bölgesine giden portal (bir Labyrinth Key; wiki), ortasında X-1'e dönüş (ücretsiz). Kapı tablosu fandom'un 2019 tablosu: köşe ->
[hedef harita, hedef bölge, varılan köşe]. Duvarlar istemcinin; sunucu bölgeyi doğma yeri için kullanır.
  - Bölge nüfusu (Frozen Icy, Kristallin, Kristallon, patronlar, meteorlar) 'nufus'tan; ölünce aynı bölgede yeniden doğar.
  - Labyrinth Key: uzaylının 'anahtar' [olasılık, adet] (wiki: Icy %5 … Super Meteoroid %80 ve 2); profilde sayaç, istemciye
    FrozenLabyrinthKeyInfoCommand. Etkinlik bitince kalan anahtarlar silinir (wiki). Ice Box (ICY_BOX, events.json labirent
    harita_ek) her kutuda 1 anahtar verir: dunya.grant_loot -> add_keys.
  - Skoll: aralıkla bulunulan haritada (olasılıkla) belirir, labirente duyurulur; ölünce 3 anahtar, Indoctrine Oil ve Accelerator.
  - Synk: bütün labirentte bir tane; rastgele harita ve bölgede doğar, saldırmaz, kaçar; ölünce ödül kutusu, Synk avı sayılır
    (FrozenLabyrinthSynkInfoCommand: harita, bölge, yeniden doğmaya kalan; FrozenLabyrinthInfoCommand: avlar, anahtarlar, süreler).
Profilde: labirent {anahtar, synk: {harita, bolge, dogus}, avlar, son_av}.
Iceterion (öldürülemez, mayın bırakır) yok: değerleri bilinmiyor.
"""
import math, random, time

import settings as SET
import map_links as H
import galaxy_gates as KAPI
import event_calendar as CAL
import event_gate as EKP

L = EKP.LAB
MAPS = {int(k): v for k, v in L['maps'].items()}
NAMES = {v['name']: k for k, v in MAPS.items()}
ZONES = ['TL', 'TR', 'BL', 'BR']
PORTAL_BASE = 152900000               # + harita * 100 + bölge * 10 + köşe (0-3), merkez + 4
INSET = 1800                          # köşe portallarının bölge kenarından uzaklığı
FLB_KEY = 'resource_key_access-flb'   # Pass görevlerinin anahtar kimliği (anahtar profilde state['anahtar'] sayısı)
SKOLL, SYNK, ICETERION = 'lab_skoll', 'lab_synk', 'lab_iceterion'


def zone_rect(map_id, z):
    w, h = H.map_size(map_id)
    i = ZONES.index(z)
    x0, y0 = (i % 2) * w / 2.0, (i // 2) * h / 2.0
    return x0, y0, x0 + w / 2.0, y0 + h / 2.0


def zone_of(map_id, x, y):
    w, h = H.map_size(map_id)
    return ZONES[(1 if x >= w / 2.0 else 0) + (2 if y >= h / 2.0 else 0)]


def corner(map_id, z, c):
    x0, y0, x1, y1 = zone_rect(map_id, z)
    return (int(x0 + INSET if c in ('TL', 'BL') else x1 - INSET), int(y0 + INSET if c in ('TL', 'TR') else y1 - INSET))


def zone_center(map_id, z):
    x0, y0, x1, y1 = zone_rect(map_id, z)
    return int((x0 + x1) / 2), int((y0 + y1) / 2)


def arrival_spot(map_id, z=None):
    """Girişte varış: rastgele bölgenin ortasının yanı."""
    x, y = zone_center(map_id, z or random.choice(ZONES))
    return x + 500, y


def portals(map_id, home):
    """Haritanın labirent portalları: bölge başına dört köşe (anahtarla) ve ortada eve dönüş."""
    m = MAPS.get(int(map_id))
    if not m:
        return []
    out = []
    for zi, z in enumerate(ZONES):
        for ci, c in enumerate(ZONES):
            dest, dz, dc = m['zones'][z]['kapilar'][c]
            x, y = corner(map_id, z, c)
            ax, ay = corner(dest, dz, dc)
            cx, cy = zone_center(dest, dz)
            k = 600.0 / max(1.0, math.hypot(cx - ax, cy - ay))          # varış: hedef köşe portalının bölge ortasına doğru yanı
            out.append(dict(gateId=PORTAL_BASE + int(map_id) * 100 + zi * 10 + ci, x=x, y=y, target=dest, designId=L['portal'],
                            gate='labyrinth', paid=True, arrival=(int(ax + (cx - ax) * k), int(ay + (cy - ay) * k))))
        x, y = zone_center(map_id, z)
        out.append(dict(gateId=PORTAL_BASE + int(map_id) * 100 + zi * 10 + 4, x=x, y=y, target=home, designId=1, gate='labyrinth', arrival='station'))
    return out


def state(p):
    return p.d.setdefault('labyrinth', {'anahtar': 0, 'hunts': 0})


def keys(p):
    return int(state(p).get('anahtar', 0))


def key_cmd(p):
    return ('FrozenLabyrinthKeyInfoCommand', {'labyrinthKeys': keys(p)})


def add_keys(p, n):
    """Labyrinth Key ekle (uzaylının düşürdüğü ya da Ice Box'ın anahtarı) -> istemci mesajları."""
    with p.lock:
        state(p)['anahtar'] = keys(p) + n
        p.dirty = True
    p.ach('loot', loot=FLB_KEY, amount=n)                          # Frozen Labyrinth Pass: "Labyrinth Key topla" (savas_bileti.py)
    return [key_cmd(p), KAPI.screen('+%d Labyrinth Key (%d)' % (n, keys(p)))]


def expire_keys(p, now=None):
    """Etkinlik bittiyse kalan anahtarlar silinir (wiki)."""
    if keys(p) and not CAL.is_active(L['event'], now):
        with p.lock:
            state(p)['anahtar'] = 0
            p.dirty = True
        return True
    return False


class Labyrinth:
    """Bir labirent haritasının dünyası (dunya.World.labirent)."""

    def __init__(self, world, log=None):
        self.w, self.p = world, world.p
        self.map = int(world.map_id)
        self.log = log or world.log
        self.next_skoll = time.time() + L['skoll']['interval_sec']
        self.synk_id = None
        world.gate_fee = self.pay
        now = time.time()
        for z in ZONES:                       # bölge nüfusu (saklanan harita durumunda eksikleri: bekleyen doğmalar eski dünyada kaldı)
            for name, n in MAPS[self.map]['zones'][z]['population']:
                tip = self.type_of(name)
                have = sum(1 for x in world.npcs.values() if x.tip == tip and zone_of(self.map, *x.mover.pos(now)) == z)
                for _ in range(max(0, SET.count('npc_count', n) - have)):      # panel: uzaylı sayısı
                    self.spawn(tip, z)
        self.synk_id = next((x.id for x in world.npcs.values() if x.tip == SYNK), None)
        self.synk_check(time.time())
        world.send(self.info_msgs())

    @staticmethod
    def type_of(name):
        return 'lab_' + name.lower().replace(' ', '_')

    def spawn(self, tip, z, engaged=False):
        x0, y0, x1, y1 = zone_rect(self.map, z)
        for _ in range(20):
            x, y = random.uniform(x0 + 1200, x1 - 1200), random.uniform(y0 + 1200, y1 - 1200)
            if all(math.hypot(g['x'] - x, g['y'] - y) > H.GATE_PEACE_RADIUS + 400 for g in self.w.gates):
                break
        n = self.w.spawn_npc_at(tip, x, y)
        n.summoned = True                        # dünyanın yeniden doğurması değil: labirent kendi bölgesinde doğurur
        n.engaged = engaged
        return n

    # ------------------------------------------------------------ portal ücreti
    def pay(self, g):
        """Köşe portalı: bir Labyrinth Key -> (geçebilir mi, mesajlar)."""
        if not g.get('paid'):
            return True, []
        if not CAL.is_active(L['event']) or not self.open_hours(time.time()):    # etkinlik bitti ya da kapı saati değil
            return False, [KAPI.screen('key:log_msg_flb_not_running')]
        need = L.get('key_cost', 1)
        if keys(self.p) < need:
            self.log('   labirent: anahtar yok (%d gerekli)' % need)
            return False, [KAPI.screen('key:log_msg_flb_no_accesskey')]
        with self.p.lock:
            state(self.p)['anahtar'] = keys(self.p) - need
            self.p.dirty = True
        self.log('   labirent: %d anahtar harcandı (kalan %d) -> %s' % (need, keys(self.p), MAPS[g['target']]['name']))
        self.p.ach('spend', loot=FLB_KEY, count=need)                # Frozen Labyrinth Pass: "Labyrinth Key kullan" (savas_bileti.py)
        return True, [key_cmd(self.p)]

    # ------------------------------------------------------------ ölüm
    def on_kill(self, n, x, y):
        if not n.tip.startswith('lab_'):
            return []
        w, msgs = self.w, []
        a = n.d.get('anahtar')
        if a and random.random() < a[0]:
            msgs += add_keys(self.p, a[1])
            self.log('   labirent: +%d anahtar (%d)' % (a[1], keys(self.p)))
        for loot, amount, chance in n.d.get('drop', []):
            if random.random() < chance:
                msgs += w.grant_loot(loot, random.randint(*amount) if isinstance(amount, list) else amount, 'mod')
        if n.tip == SYNK:
            msgs += self.synk_killed(time.time())
        elif n.tip != SKOLL:
            z = zone_of(self.map, x, y)
            delay = (n.d.get('renew_sec') or random.uniform(45, 90)) * SET.multiplier('npc_respawn')      # panel
            w.later(delay, lambda: self.respawn(n.tip, z))
        return msgs

    def respawn(self, tip, z):
        with self.w.lock:
            if self.w.labyrinth is self:
                self.spawn(tip, z)

    # ------------------------------------------------------------ Skoll ve Synk
    def tick(self, now):
        self.iceterion_tick(now)
        if now >= self.next_skoll:
            self.next_skoll = now + L['skoll']['interval_sec']
            if not any(n.tip == SKOLL for n in self.w.npcs.values()) and random.random() < L['skoll']['probability']:
                z = random.choice(ZONES)
                for _ in range(L['skoll'].get('count', 1)):   # forum 158403: 5 dakikada üç Skoll
                    self.spawn(SKOLL, z)
                self.w.send([KAPI.screen('key:msg_npc_skoll-labyrinth_spawn_now', big=True, MAP=MAPS[self.map]['name'],
                                         ZONE=ZONES.index(z) + 1)])
                self.log('   labirent: Skoll doğdu (%s %s)' % (MAPS[self.map]['name'], z))
        self.synk_check(now)

    def iceterion_tick(self, now):
        """Iceterion (forum 158403): haritada bir tane; öldürülemez; oyuncu yakınındayken aralıkla çevresine IceMine bırakır."""
        cfg = (L.get('alien_spawns') or {}).get(ICETERION, {}).get('mine')
        if not cfg:
            return
        ice = next((n for n in self.w.npcs.values() if n.tip == ICETERION and n.alive), None)
        if not ice:
            ice = self.spawn(ICETERION, random.choice(ZONES))
            ice.invulnerable = lambda: True
            ice.next_mine = now + cfg['interval_sec']
            return
        if now < getattr(ice, 'next_mine', 0) or self.w.items is None:
            return
        ice.next_mine = now + cfg['interval_sec']
        hx, hy = self.w.hero_pos(now)
        if math.hypot(*(a - b for a, b in zip(ice.mover.pos(now), (hx, hy)))) > cfg['range']:
            return
        if sum(1 for k in self.w.items.mines.values() if k['owner'] == ice.id) >= cfg['max_count']:
            return
        a, r = random.uniform(0, 2 * math.pi), random.uniform(*cfg['radius'])
        self.w.items.alien_mine(cfg['type'], hx + math.cos(a) * r, hy + math.sin(a) * r, ice.id, now)

    def open_hours(self, now):
        """Labirent kapıları saatlerde açık (forum 158403; hafta içi / hafta sonu dilimleri); panelin 'seans_hep_acik' ayarıyla ya da
        etkinlik zorla açılmışsa (--event) hep."""
        import settings as SET
        if SET.get('session_always_open') or not L.get('hours') or CAL.forced(L['event']):
            return True
        t = time.localtime(now)
        h = t.tm_hour + t.tm_min / 60.0
        return any(a <= h < b for a, b in (L['hours_weekend'] if t.tm_wday >= 5 else L['hours']))

    def synk_state(self, now):
        s = state(self.p).get('synk')
        if not s:
            s = self.new_synk(now, now)
        return s

    def new_synk(self, now, when):
        s = {'map': random.choice(list(MAPS)), 'region': random.choice(ZONES), 'spawn': when}
        with self.p.lock:
            state(self.p)['synk'] = s
            self.p.dirty = True
        return s

    def synk_check(self, now):
        s = self.synk_state(now)
        alive = self.synk_id in self.w.npcs
        if s['map'] == self.map and now >= s['spawn'] and not alive:
            n = self.spawn(SYNK, s['region'])
            self.synk_id = n.id
            self.w.send([KAPI.screen('key:msg_npc_synk_spawn_now', big=True, MAP=MAPS[self.map]['name'], ZONE=ZONES.index(s['region']) + 1),
                         self.synk_cmd(now)])
            self.log('   labirent: Synk doğdu (%s %s)' % (MAPS[self.map]['name'], s['region']))

    def synk_killed(self, now):
        st = state(self.p)
        with self.p.lock:
            st['hunts'] = st.get('hunts', 0) + 1
            st['last_hunt'] = time.strftime('%Y-%m-%d %H:%M', time.localtime(now))
            self.p.dirty = True
        self.synk_id = None
        self.new_synk(now, now + random.uniform(*L['synk']['renew_sec']))
        self.p.ach('synk')
        self.log('   labirent: Synk avlandı (%d)' % st['hunts'])
        return [KAPI.screen('key:msg_npc_synk_killed', big=True, PLAYER=self.p.d['pilot'].get('userName', '')),
                self.synk_cmd(now)] + self.info_msgs(now)

    def synk_cmd(self, now=None):
        now = time.time() if now is None else now
        s = self.synk_state(now)
        return ('FrozenLabyrinthSynkInfoCommand', dict(zone=ZONES.index(s['region']) + 1, mapName=MAPS[s['map']]['name'],
                                                       isGateActive=now >= s['spawn'], respawnInSeconds=int(max(0, s['spawn'] - now))))

    def info_msgs(self, now=None):
        now = time.time() if now is None else now
        import community as TP                          # sunucudaki oyuncular (Synk avları)
        row = lambda r: dict(_='FrozenLabyrinthRankModule', kills=int(r[2]), name=r[1].d['pilot'].get('userName', ''), rank=r[0] or 1,
                             lastKillTime=(r[1].d.get('labyrinth') or {}).get('last_hunt', ''))
        top, me = TP.ranking(self.p, lambda x: int((x.d.get('labyrinth') or {}).get('hunts', 0)))
        rank = dict(_='FrozenLabyrinthRankInfoCommand', myRank=row(me), topRankers=[row(r) for r in top] or [row(me)])
        left = int(max(0, CAL.time_left(L['event'], now)))
        times = dict(_='FrozenLabyrinthTimeInfoCommand', timeToEndLabyrinth=left, timeToNextLabyrinth=0)
        return [('FrozenLabyrinthInfoCommand', dict(rankInfo=rank, labyrinthKeys=keys(self.p), timeInfo=times)), self.synk_cmd(now)]
