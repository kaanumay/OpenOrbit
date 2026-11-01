"""Plutus' Experiments (Plutus Experiment Event, Şubat 2019; yol haritası ETKINLIKLER-34, URETIM-8; veri data/event_gates.json 'deney'
<- tools/event_gates.py, kaynak belgeler/wiki/etkinlikler/plutus_deney.json).

Üç risk: Low (kendi X-1 haritaların), Medium (X-5), High (4-4; PvP yerine PvE). Etkinlik sürerken oyuncunun bulunduğu haritada, bekleme
(Low ve Medium 20 dk, High 30 dk; "atış dahil") dolmuşsa yakında bir işaret kulesi (Plutus Beacon) doğar. Kuleye ilk atış 35 sn'lik sayacı
başlatır (istemcinin Plutus metinleri: ilk atış, 10. sn "ne kadar çok hasar, o kadar iyi uzaylı", 35. sn); kulenin aldığı hasara göre risk
basamağının uzaylısı çıkar (Saimon Aberration … Devolarium Aberration; Kristallin Oddity … Uber Kristallon Oddity; Awakened Lordakium,
Overlord, Devourer). Atışa 2 dakikada başlanmazsa kule kaçar ("escaped"); bekleme yine işler. Uzaylı yok olunca ona verilen hasarın kademesine
göre kutu düşer (BEACON_LOW_RISK_BOX_0-11, MED_0-12, HIGH_1-8): ilerleme puanı, Tarnom (Low/Medium), Opitite (Medium/High) ve şanslı eşyalar
(BRB-2, Backup Shield 2, Hecate gemisi, Dusklight Hecate tasarımı; High'ın en üst kademesinde BRB-2 ve Backup Shield 2 kesin).
Tarnom ve Opitite Assembly'nin 13 tarifinin malzemesi (assembly.NO_SOURCE'tan çıktı). İlerleme puanı eşiklerinin ödülü (1.000 -> 15.000 CC-D,
5.000 -> 10.000 Seprom, 10.000 -> 15.000 CC-C, 20.000 -> 96 DMG-DLB + 96 SHD-DLB, 50.000 -> NPC Nuke): istemcinin ilerleme penceresi ölü
olduğundan eşiğe ulaşılınca bir kez, otomatik.
Takvimde Plutus' Experiments yok: Gauntlet of Plutus penceresinde çalışır (takvimde 'plutus_deney' etkinliği varsa o).
Profilde: plutus_deney {son: {risk: son işaretin zamanı}, pp, alinan: [verilen eşikler]}. ek_etkinlikler.EkEtkinlikler sistemi (attach, tick,
on_kill).
"""
import math, random, time

import settings as SET
import world as world_module
import event_gate as EKP
import map_links as H
import galaxy_gates as KAPI
import event_calendar as CAL

D = EKP.D.get('deney') or {}
EVENT = 'plutus_deney' if 'plutus_deney' in CAL.EVENTS else D.get('etkinlik', 'plutus')
BEACON = (D.get('isaret') or {}).get('tur', 'deney_isaret')
PREFIX = 'deney_'


def type_name(risk, i):
    return '%s%s_%d' % (PREFIX, risk, i)


def _register():
    if not D:
        return
    world_module.CFG['tipler'][BEACON] = {k: v for k, v in D['isaret'].items() if k != 'tur'}
    for key, r in D['riskler'].items():
        for i, a in enumerate(r['uzaylilar']):
            world_module.CFG['tipler'][type_name(key, i)] = EKP._tip(a)


_register()


def active(now=None):
    return EVENT in CAL.active(now)


def risk_of(world, faction):
    """Bu harita hangi riskin haritası (Low: kendi X-1'lerin, Medium: kendi X-5'lerin, High: 4-4); değilse None."""
    m = int(world.map_id)
    for key, r in D.get('riskler', {}).items():
        want = r['harita_sinifi']
        if (H.name(m) == want) if want == '4-4' else (H.map_class(m) == want and H.company(m) == faction):
            return key
    return None


def tier(risk, dealt):
    """Uzaylıya verilen hasarın kutu kademesi (alt sınırı geçilen en yüksek; alt sınırın altında kutu yok) ya da None."""
    got = [t for t in D['riskler'][risk]['kutular'] if dealt >= t['den']]
    return got[-1] if got else None


def stage(risk, dealt):
    """Kuleye verilen hasara göre çıkan uzaylının sırası (eşiği geçilen en güçlü)."""
    return max(i for i, a in enumerate(D['riskler'][risk]['uzaylilar']) if a['esik'] <= dealt)


class PlutusExperiment:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.enc = None                  # süren karşılaşma: {risk, kule, dogdu, ilk, ipucu, uyari, uzayli}

    @property
    def st(self):
        return self.p.d.setdefault('plutus_deney', dict(son={}, pp=0, alinan=[]))

    # ------------------------------------------------------------ bekleme
    def cooldown_left(self, risk, now):
        if SET.get('giris_siniri_yok'):                       # panel: günlük/yıllık/bir kez ve bekleme süresi yok
            return 0
        return max(0.0, self.st['son'].get(risk, 0) + D['riskler'][risk]['bekleme_sn'] - now)

    @staticmethod
    def cooldown_msg(left):
        if left >= 60:
            return KAPI.screen('key:msg_npc_spawning_beacon_cd_min', MINUTES=int(math.ceil(left / 60.0)))
        return KAPI.screen('key:msg_npc_spawning_beacon_cd_sec', SECONDS=int(math.ceil(left)))

    # ------------------------------------------------------------ harita ve zaman
    def attach(self, world):
        self.world, self.enc = world, None
        if not D or not active():
            return []
        risk = risk_of(world, self.p.d['pilot'].get('factionId'))
        left = self.cooldown_left(risk, time.time()) if risk else 0
        return [self.cooldown_msg(left)] if left > 0 else []

    def tick(self, now):
        w = self.world
        if not D or not w:
            return []
        if not active(now):
            return self.end(w) if self.enc else []
        risk = risk_of(w, self.p.d['pilot'].get('factionId'))
        if not risk or w.hero_dead:
            return []
        if self.enc is None:
            return self.spawn_beacon(w, risk, now) if self.cooldown_left(risk, now) <= 0 else []
        return self.step(w, now)

    def end(self, w):
        """Etkinlik bitti: kule ve süren uzaylı gider."""
        e, self.enc = self.enc, None
        msgs = []
        with w.lock:
            for i in (e['kule'], e.get('uzayli')):
                n = w.npcs.get(i) if i else None
                if n:
                    msgs += w.remove_npc(n)
        return msgs

    def spawn_beacon(self, w, risk, now):
        hx, hy = w.hero_pos(now)
        a, d = random.uniform(0, 2 * math.pi), random.uniform(500, 900)
        x = min(max(hx + math.cos(a) * d, 500), w.map_w - 500)
        y = min(max(hy + math.sin(a) * d, 500), w.map_h - 500)
        with w.lock:
            n = w.spawn_npc_at(BEACON, x, y)
            n.dealt = 0
            n.damage_hook = lambda dmg, n=n: self.beacon_hit(n, dmg)
        with self.p.lock:
            self.st['son'][risk] = now
            self.p.dirty = True
        self.enc = dict(risk=risk, kule=n.id, spawned=now, ilk=None, ipucu=False, uyari=False, uzayli=None)
        self.log('   Plutus’ Experiments: %s işaret kulesi doğdu (%d, %d)' % (D['riskler'][risk]['ad'], x, y))
        return [KAPI.screen('key:msg_npc_spawning_beacon_high_risk_spawn') if risk == 'high'
                else KAPI.screen('A %s beacon has spawned.' % D['riskler'][risk]['ad'])]

    @staticmethod
    def beacon_hit(n, dmg):
        """Kule yok olmaz: aldığı hasar sayılır, canı yenilenir (dunya.hit_npc'nin hasar kancası)."""
        n.dealt += dmg
        n.hp, n.shield = n.d['hp'], n.d['kalkan']

    def step(self, w, now):
        e, msgs = self.enc, []
        with w.lock:
            if e['uzayli']:                                  # uzaylı çıktı: yok olunca karşılaşma biter (kutu on_kill'de)
                n = w.npcs.get(e['uzayli'])
                if n is None or not n.alive:
                    self.enc = None
                return msgs
            b = w.npcs.get(e['kule'])
            if b is None:
                self.enc = None
                return msgs
            if e['ilk'] is None:
                if b.dealt > 0:
                    e['ilk'] = now
                    msgs.append(KAPI.screen('key:msg_npc_spawning_beacon_first_shot'))
                elif now >= e['spawned'] + D['atis_sn']:       # 2 dakikada atılmadı: kaçar
                    msgs += w.remove_npc(b) + [KAPI.screen('key:msg_npc_spawning_beacon_escaped')]
                    self.enc = None
                return msgs
            t = now - e['ilk']
            if not e['ipucu'] and t >= D['ipucu_sn']:
                e['ipucu'] = True
                msgs.append(KAPI.screen('key:msg_npc_spawning_beacon_10_sec'))
            if not e['uyari'] and t >= D['dalga_sn'] - 10:       # 45 sn'lik sayacın 35. saniyesi (forum 143093)
                e['uyari'] = True
                msgs.append(KAPI.screen('key:msg_npc_spawning_beacon_35_sec'))
            if t >= D['dalga_sn']:
                msgs += self.release(w, b, e)
        return msgs

    def release(self, w, b, e):
        """35 sn doldu: kulenin aldığı hasara göre uzaylı çıkar, kule gider."""
        risk = e['risk']
        i = stage(risk, b.dealt)
        x, y = b.mover.pos(time.time())
        msgs = w.remove_npc(b)
        n = w.spawn_npc_at(type_name(risk, i), x, y, wave=True)
        n.gate, n.hunt, n.dealt = True, True, 0
        n.damage_hook = lambda dmg, n=n: setattr(n, 'dealt', n.dealt + dmg)
        e['uzayli'] = n.id
        self.log('   Plutus’ Experiments: kule %d hasar aldı -> %s' % (b.dealt, D['riskler'][risk]['uzaylilar'][i]['ad']))
        return msgs

    # ------------------------------------------------------------ ödül
    def on_kill(self, w, npc, x, y):
        """Deney uzaylısı yok oldu: ona verilen hasarın kademesinin kutusu düşer (kutu toplanınca ödül: collect)."""
        if not npc.tip.startswith(PREFIX) or npc.tip == BEACON:
            return []
        risk = npc.tip[len(PREFIX):].rsplit('_', 1)[0]
        t = tier(risk, min(getattr(npc, 'dealt', 0), npc.d['hp'] + npc.d['kalkan']))
        if t:
            h = w.drop_box(t['tur'], x, y, None, 900)
            w.boxes[h]['al'] = lambda b, t=t: self.collect(w, t)
            self.log('   Plutus’ Experiments: %s düştü (%d hasar)' % (t['tur'], npc.dealt))
        return []

    def collect(self, w, t):
        """Kutu toplandı: kesin satırlar (Tarnom, Opitite, High'ın en üst kademesinde BRB-2 ve Backup Shield 2), şanslı eşyalar, ilerleme puanı."""
        msgs = []
        for loot, n in t['kesin']:
            msgs += w.grant_loot(loot, n)
        for loot, n, chance in t['sans']:
            if random.random() < SET.chance('dusme', chance, 'etkinlik'):
                msgs += w.grant_loot(loot, n)
        return msgs + self.add_points(w, t['pp'])

    def add_points(self, w, n):
        """İlerleme puanı: eklenir; eşiğe ulaşılan her satırın ödülü bir kez verilir."""
        st = self.st
        with self.p.lock:
            st['pp'] += n
            due = [r for r in D['puan_takasi'] if st['pp'] >= r['puan'] and r['puan'] not in st['alinan']]
            st['alinan'] += [r['puan'] for r in due]
            self.p.dirty = True
        msgs = [KAPI.screen('Progression points: +%d (%d)' % (n, st['pp']))]
        for r in due:
            for loot, k in r['odul']:
                msgs += w.grant_loot(loot, k)
            msgs.append(KAPI.screen('Progression reward (%d points) received.' % r['puan'], big=True))
            self.log('   Plutus’ Experiments: %d puan ödülü' % r['puan'])
        return msgs
