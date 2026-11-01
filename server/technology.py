"""Teknoloji eşyaları (kısayol çubuğunun tech_items kategorisi): Energy Leech, Chain Impulse, Precision Targeter, Backup Shield 1/2,
Battle Repair Bot 1/2, Explosive Charging Blob, Burning Trail, NPC Nuke, Anti-AI Emergency Reserves, Frost Field, Anti-Mine
Transmitter, Speed Burst, Versus Laser Overdrive. Veri items.json "teknoloji" (wiki: belgeler/wiki/extras_cpu_tech.md); adetler profilde
"teknoloji" (Assembly ile gelir: yol haritası Aşama 5), süre ve beklemeler "teknoloji_durum"da (harita değişince sürer).

İstemci (1.1.114, araştırma: istemcinin kodu):
  - tıklama MenuActionRequest {menuItemId tech_…, actionType 0 (zamanlayıcı öğesi)}; TechActivationRequest hiç gönderilmez,
    TechActivationCommand/TechStatusCommand işlenmez.
  - zamanlayıcı öğe başına MenuItemTimerCommand (bekleme grubu yok): READY 0, ACTIVE 1, COOLING_DOWN 2.
  - görseller: VisualModifierCommand {userId, modifier, activated} (ELA 59, BRB 60, BRB2 61, ECB 73: kapanınca patlama, SB 95,
    AMT 96, AAER 100, FRF 102); Backup Shield 0|n|A|S|SBU(2)|uid; Chain Impulse 0|n|ECI|1|saldıran|hedef…; Burning Trail
    0|n|BT|uid ve NPC Nuke 0|n|NNK|uid: o birimde şok dalgası.
"""
import json, math, os, time

from legacy_protocol import legacy, stm
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
T = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['teknoloji']
ITEMS = T['esyalar']
READY, ACTIVE, COOLING = 0, 1, 2
ATTACK_ROCKET, ATTACK_ECI = 0, 5            # istemcinin AttackType'ı


def mod(name, **f):
    f['_'] = name
    return f


def used_msg(code):
    """Kullanıldı bildirimi, ekranda ve günlükte (istemci resource.json tech_used_<KOD>, örn. "NPC Nuke used"). resource.json
    anahtarları yalnız eski protokolün 0|A|STM|anahtar iletisiyle çözülür: MessageCommand (tür 5 flashres, 3-7 eşya) bulamayıp
    hiçbir şey göstermiyor (canlı deneme 2026-10-26)."""
    return stm('tech_used_' + code)


def count(p, item):
    return p.d.get('teknoloji', {}).get(item, 0)


def add(p, item, n=1):
    """Assembly (Aşama 5) ve testler: adet ekle -> yeni adet."""
    with p.lock:
        d = p.d.setdefault('teknoloji', {})
        d[item] = max(0, d.get(item, 0) + n)
        p.dirty = True
        return d[item]


def state(p):
    return p.d.setdefault('technology_state', {})


def is_active(p, item, now=None):
    return (now or time.time()) < state(p).get(item, {}).get('bitis', 0)


def timer_fields(p, item, now=None):
    now = now or time.time()
    s = state(p).get(item, {})
    if now < s.get('bitis', 0):
        return dict(activatable=False, timerState=ACTIVE, maxTime=s.get('duration_ms', 0), time=int((s['bitis'] - now) * 1000))
    if now < s.get('hazir', 0):
        return dict(activatable=False, timerState=COOLING, maxTime=s.get('cooldown_ms', 0), time=int((s['hazir'] - now) * 1000))
    return dict(activatable=True, timerState=READY, maxTime=0, time=0)


def timer_msg(p, item, now=None):
    f = timer_fields(p, item, now)
    return ('MenuItemTimerCommand', dict(activatable=f['activatable'], timerState=mod('TimerStateModule', timerStateValue=f['timerState']),
                                         menuItemId=item, maxTime=f['maxTime'], time=f['time']))


def menu_status(p, item, st):
    """Elde varsa görünür, sayaçta adet (kayıtta yokken: ttip_visit_tech_factory / ttip_tech_not_owned)."""
    if item not in ITEMS:
        return None
    n = count(p, item)
    if n <= 0:
        st.update(visible=False, available=False, activatable=False, counterValue=0)
        return st
    maps = ITEMS[item].get('map_only')
    usable = not maps or str(p.d['position'].get('mapId', 0)) in map(str, maps)        # Versus Laser Overdrive: yalnız Vortex of Greed haritasında
    usable = usable and not echoes_map(p.d['position'].get('mapId', 0))              # forum 177095: Yankılar'da teknoloji yok
    lines = [{'_': 'MessageKeyListWildcardModule', 'baseKey': item, 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 3},
              'textStyle': 0, 'wildCardReplacements': []},
             {'_': 'MessageKeyListWildcardModule', 'baseKey': 'ttip_count', 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5},
              'textStyle': 0, 'wildCardReplacements': [
                  {'_': 'MessageWildcardReplacementModule', 'wildcard': '%COUNT%', 'replacement': str(n),
                   'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}}]}]
    for k in ('toolTipSlotBar', 'toolTipItemBar'):
        st[k] = {'_': 'MessageKeyListWildcardCommand', 'commandList': json.loads(json.dumps(lines))}
    st.update(visible=True, available=usable, activatable=usable and timer_fields(p, item)['activatable'], counterValue=n,
              counterStyle=0)
    return st


def echoes_map(map_id):
    """Uzayın Derinliklerindeki Yankılar haritaları ve salonu: teknoloji eşyaları kullanılamaz (resmî forum 177095)."""
    import echoes as EC
    return int(map_id or 0) in set(EC.D['haritalar']) | {EC.D['hall']}


class Technology:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.ending = {}           # süreli etkin eşya -> bitiş
        self.waiting = {}          # beklemesi süren -> hazır anı (READY bildirimi)
        self.next_tick = 0.0
        self.charges = []          # Burning Trail yükleri: {x, y, bitis}
        self.trail_n = 0           # Burning Trail'in geçen saniyeleri (aralik_sn'de bir yük)
        self.nuke = None           # NPC Nuke: {sonraki, kalan}
        self.started = False
        now = time.time()
        for item, s in state(self.p).items():
            maps = ITEMS.get(item, {}).get('map_only')
            if maps and now < s.get('bitis', 0) and str(world.map_id) not in map(str, maps):
                s['bitis'] = now                       # Versus Laser Overdrive: gemi Vortex of Greed'den ayrılınca etki silinir (bekleme sürer)
                self.p.dirty = True
            if now < s.get('bitis', 0):
                self.ending[item] = s['bitis']
                if item == 'tech_npc-nuke':            # harita değişince kalan vuruşlar sürer (vuruşlar başlangıçtan aralik_sn'de bir)
                    c = ITEMS[item]
                    start, total = s['bitis'] - c['sure_sn'], int(c['sure_sn'] // c['aralik_sn'])
                    done = min(total, max(0, int((now - start) // c['aralik_sn'])))
                    self.nuke = dict(next=start + (done + 1) * c['aralik_sn'], kalan=total - done)
            elif now < s.get('hazir', 0):
                self.waiting[item] = s['hazir']

    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def visual(self, item, on):
        g = ITEMS[item].get('gorsel')
        return [('VisualModifierCommand', dict(userId=self.w.hid, modifier=g, attribute=0, additionalAttribute='', count=0,
                                               activated=on))] if g else []

    def status(self, item):
        st = self.p.menu_status(item)
        return [('MenuItemStatusCommand', st)] if st else []

    # ------------------------------------------------------------ sorgular (dunya.py, savas_esya.py)
    def active(self, item, now=None):
        return item in self.ending and is_active(self.p, item, now)

    def full_rocket_hit(self, now=None):
        return self.active('tech_precision-targeter', now)

    def hp_floor(self, now=None):
        """Anti-AI Emergency Reserves: uzaylı hasarı canı bunun altına indiremez (yoksa 0)."""
        return ITEMS['tech_anti-ai-emergency-reserves']['en_az_can'] if self.active('tech_anti-ai-emergency-reserves', now) else 0

    def mine_protected(self, now=None):
        return self.active('tech_anti-mine-transmitter', now)

    def laser_bonus(self, now=None):
        """Versus Laser Overdrive: etkinken her lazerin taban hasarına eklenen düz hasar (yoksa 0)."""
        return ITEMS['tech_versus-laser-overdrive']['base_laser'] if self.active('tech_versus-laser-overdrive', now) else 0

    def leech(self, ammo, dmg):
        """Energy Leech: sıradan lazer cephanesiyle verilen hasarın %10'u cana."""
        if dmg <= 0 or ammo not in T['ammo_types'] or not self.active('tech_energy-leech'):
            return
        g = self.p.d['gemi']
        if g.get('hitPoints', 0) >= g.get('hitMax', 0):
            return
        self.p.set_hull(hp=g.get('hitPoints', 0) + dmg * ITEMS['tech_energy-leech']['laser_hp'])
        self.send([self.w.hp_msg()])

    # ------------------------------------------------------------ etkinleştirme
    def activate(self, item, now=None):
        """MenuActionRequest tech_…: elde varsa ve hazırsa -> True."""
        w, p = self.w, self.p
        now = now or time.time()
        c = ITEMS.get(item)
        if not c or count(p, item) <= 0 or w.hero_dead or w.jumping or echoes_map(w.map_id) or                 (c.get('map_only') and str(w.map_id) not in map(str, c['map_only'])):
            w.log('   teknoloji kullanılamaz: %s' % item)
            return False
        if is_active(p, item, now) or now < state(p).get(item, {}).get('hazir', 0):
            self.send([timer_msg(p, item, now)])
            return False
        msgs = self.start(item, c, now)
        if msgs is None:
            w.log('   teknoloji şimdi işe yaramaz: %s' % item)
            return False
        if not SET.get('sonsuz_teknoloji'):          # panel: infinite tech (not used up; at least one still needed)
            add(p, item, -1)
        p.ach('spend', loot=item, adet=1)           # Quests/Pass "use an item": counted with or without infinite tech
        sec, cd = c.get('sure_sn', 0), c.get('bekleme_sn', 0) * SET.multiplier('yetenek_bekleme', 'teknoloji')      # panel
        with p.lock:
            state(p)[item] = dict(bitis=now + sec, hazir=now + sec + cd, duration_ms=int(sec * 1000), cooldown_ms=int(cd * 1000))
            p.dirty = True
        if sec:
            self.ending[item] = now + sec
        else:
            self.waiting[item] = now + cd
        self.send(msgs + [timer_msg(p, item, now)] + self.status(item))
        w.log('   teknoloji: %s (kalan %d)' % (item, count(p, item)))
        return True

    def start(self, item, c, now):
        """Eşyanın başlangıç etkisi -> mesajlar, ya da None (şimdi kullanılamaz: hedef yok, kalkan dolu …)."""
        w, p = self.w, self.p
        g = p.d['gemi']
        hx, hy = w.hero_pos(now)
        if 'kalkan' in c:                                               # Backup Shield
            if g.get('shield', 0) >= g.get('shieldMax', 0):
                return None
            sh0 = g.get('shield', 0)
            p.set_hull(shield=sh0 + c['kalkan'])
            return [legacy('0|n|A|S|%s|%d' % (c['eski'], w.hid)),
                    ('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})] + w.heal_msgs(sh0=sh0)
        if item == 'tech_chain-impulse':
            near = sorted(((math.hypot(nx - hx, ny - hy), n) for n in w.npcs.values() if n.alive
                           for nx, ny in [n.mover.pos(now)]), key=lambda t: t[0])
            targets = [n for d, n in near if d <= c['yaricap']][:c['hedef']]
            if not targets:
                return None
            msg = legacy('0|n|ECI|1|%d|%s' % (w.hid, '|'.join(str(n.id) for n in targets)))
            def strike():
                for n in targets:
                    w.hit_npc(n.id, c['hasar'], ATTACK_ECI, shield_only=True)      # istemci: "chain reaction of shield damage"
                    if not n.alive:
                        p.ach('chain_kill')                 # başarım ChainImpulse
            w.later(0.3, strike)
            w.last_combat = now
            return [msg]
        if item == 'tech_npc-nuke':
            # istemci: "burst of damage to NPCs in an area around your ship once every 10 seconds": hedef gerekmez, gemi çevresindeki
            # bütün uzaylılara sure_sn / aralik_sn vuruş (nuke_tick)
            self.nuke = dict(next=now + c['aralik_sn'], kalan=int(c['sure_sn'] // c['aralik_sn']))
            return [used_msg('NNK')]
        if item == 'tech_speed-burst':
            w.hero_effect('hizlanma', c['sure_sn'], c['hiz'], source=item)
        if item == 'tech_burning-trail':
            self.charges, self.trail_n = [], 0
        return self.visual(item, True)

    # ------------------------------------------------------------ döngü
    def tick(self, now):
        w, p = self.w, self.p
        if not self.started:
            self.started = True                    # harita değişiminde süren görseller yeniden
            self.send(sum((self.visual(i, True) for i in self.ending), []))
        for item, until in list(self.waiting.items()):
            if now >= until:
                del self.waiting[item]
                self.send([timer_msg(p, item, now)] + self.status(item))
        self.trail_tick(now)
        if now >= self.next_tick:
            self.next_tick = now + 1.0
            for item in list(self.ending):
                if now < self.ending[item]:
                    self.second(item, ITEMS[item], now)
        self.nuke_tick(now)
        for item, until in list(self.ending.items()):
            if now >= until:
                self.finish(item, now)

    def second(self, item, c, now):
        """Saniyede bir süren etkiler: Battle Repair Bot, Frost Field, Burning Trail yükü."""
        w, p = self.w, self.p
        g = p.d['gemi']
        if 'can_sn' in c and not w.hero_dead:
            hp0, sh0 = g.get('hitPoints', 0), g.get('shield', 0)
            p.set_hull(hp=hp0 + c['can_sn'], shield=sh0 + c.get('shield_per_sec', 0))
            msgs = [w.hp_msg()]
            if c.get('shield_per_sec'):
                msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)}))
            self.send(msgs + w.heal_msgs(hp0, sh0 if c.get('shield_per_sec') else None))
        if item == 'tech_frost-field':
            hx, hy = w.hero_pos(now)
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - hx, ny - hy) <= c['yaricap']:
                    w.npc_effect(n, 'yavas', 1.5, c['yavas'], source=item)
                    w.hit_npc(n.id, c['hasar_sn'], 1)
        if item == 'tech_burning-trail':
            if self.trail_n % c['aralik_sn'] == 0:
                x, y = w.hero_pos(now)
                self.charges.append(dict(x=x, y=y, bitis=now + c['omur_sn']))
            self.trail_n += 1

    def trail_tick(self, now):
        if not self.charges:
            return
        w, c = self.w, ITEMS['tech_burning-trail']
        for ch in list(self.charges):
            if now >= ch['bitis']:
                self.charges.remove(ch)
                continue
            n = next((n for n in w.npcs.values() if n.alive
                      and math.hypot(n.mover.pos(now)[0] - ch['x'], n.mover.pos(now)[1] - ch['y']) <= c['trigger']), None)
            if n:
                self.charges.remove(ch)
                self.send([legacy('0|n|BT|%d' % n.id)])
                w.hit_npc(n.id, c['hasar'], ATTACK_ROCKET)

    def nuke_tick(self, now):
        """NPC Nuke: aralik_sn'de bir, gemi çevresindeki (yaricap) bütün uzaylılara hasar; şok dalgası geminin kimliğinde.
        Vuruşlar sayılır (6 x 100.000): son vuruş süre sonuyla aynı ana düşer, tick gecikmesi onu kaybettirmez."""
        nk = self.nuke
        if not nk:
            return
        w, c = self.w, ITEMS['tech_npc-nuke']
        while nk['kalan'] > 0 and now >= nk['next']:
            nk['next'] += c['aralik_sn']
            nk['kalan'] -= 1
            hx, hy = w.hero_pos(now)
            hits = [n.id for n in w.npcs.values()
                    if n.alive and math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= c['yaricap']]
            self.send([legacy('0|n|NNK|%d' % w.hid)])
            w.last_combat = now
            for uid in hits:
                w.hit_npc(uid, c['hasar'], ATTACK_ROCKET)
        if nk['kalan'] <= 0:
            self.nuke = None

    def finish(self, item, now, frac=1.0):
        """Süre bitti (ya da gemi yok oldu): görsel kalkar, bekleme başlar. Explosive Charging Blob patlar."""
        self.ending.pop(item, None)
        w, p, c = self.w, self.p, ITEMS[item]
        if item == 'tech_explosive-charging-blob':
            lo, hi = c['hasar']
            dmg = int(lo + (hi - lo) * max(0.0, min(1.0, frac)))
            hx, hy = w.hero_pos(now)
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - hx, ny - hy) <= c['yaricap']:
                    w.hit_npc(n.id, dmg, ATTACK_ROCKET)
            w.log('   Explosive Charging Blob patladı: %d' % dmg)
        if item == 'tech_npc-nuke':
            self.nuke = None
        s = state(p).get(item, {})
        self.waiting[item] = s.get('hazir', now)
        self.send(self.visual(item, False) + [timer_msg(p, item, now)])

    def on_death(self):
        """Gemi yok oldu: süren etkiler biter (blob o anki dolumla patlar), beklemeler kalır."""
        now = time.time()
        for item in list(self.ending):
            s = state(self.p).get(item, {})
            sec = s.get('duration_ms', 0) / 1000.0
            frac = 1 - (s.get('bitis', now) - now) / sec if sec else 1.0
            left = s.get('bitis', now) - now
            with self.p.lock:
                s['bitis'] = now
                s['hazir'] = s.get('hazir', now) - max(0.0, left)
            self.finish(item, now, frac)
        self.charges = []
