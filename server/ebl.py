"""Eternal Black Light (yol haritası Aşama 8; istemcinin EternalBlacklight* komutları; veri data/pve_modes.json "ebl").

Eternal CPU (kısayol çubuğundan) şirketinin X-BL haritasında kapıyı açar (seviye 17). Sonsuz dalga: bir tur 51 dalga, 6 oda
(460-465; beşi 10'ar dalga, altıncısı Strokelight Barrage); tur bitince baştan, uzaylıların değerleri ve ödülleri x1,8. Tek can:
ölünce koşu biter, son tamamlanan dalganın kademesinin Blacklight Shard ödülü (ve 26. dalgadan Indoctrine Accelerator olasılığı)
verilir. Kontrol noktaları (10, 20, 30, 40, 50 ve 51. dalgalardan sonra): booster puanı (1; 51'de 2), devam ve çıkış portalı; çıkıp
sonra kaldığın yerden sürdürebilirsin (yeni CPU gerekmez). Boosterlar (istemcinin BoosterType'ı: 0 bekleme, 1 hasar, 2 lazer hasarı,
3 roket hasarı, 4 lazer isabeti, 5 can, 6 kalkan, 7 hız): pencerede üç seçenek (EternalBlacklightBoosterInfoCommand), seçim bir puan
(EternalBlacklightChooseOptionRequest {choosenOption}); seçilen türün yeniden çıkma olasılığı azalır; yalnız bu modun haritalarında
etkin, koşu bitince sıfırlanır. Uridyum koşu başına en çok 75.000 (sonra uzaylılar uridyum vermez). Sıralama: en ileri dalga (tek
oyunculu: yalnız oyuncu; Hall of Fame'in EternalGate listesi).
Profilde: pve.ebl {kapi, kosu {dalga, puan, secenek [3], agirlik {type: çarpan}, aktif {type: %}, uridyum, bas}, en_iyi, en_iyi_an}.
"""
import json, math, os, random, time

import settings as SET
import galaxy_gates as KAPI
import rankings as RK
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8')).get('ebl')
PORTAL = 156900000           # + 0 X-BL kapısı, + 1 devam, + 2 çıkış


def mod(_cls, **f):
    f['_'] = _cls
    return f


class Ebl:
    key, name = 'ebl', 'Eternal Black Light'

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.D = D
        self.world = None

    @staticmethod
    def maps():
        return D['maps'] if D else []

    @property
    def st(self):
        return self.p.d.setdefault('pve', {}).setdefault('ebl', {})

    @property
    def run(self):
        return self.st.get('run')

    # ------------------------------------------------------------ CPU ve kapı
    def own_bl(self, map_id):
        import map_links as H
        name = H.name(map_id)                      # sunucunun adı BL-1/2/3 (istemcide 1-BL …)
        return name == 'BL-%s' % self.p.d['pilot'].get('factionId')

    def use_cpu(self, map_id):
        if not self.own_bl(map_id) or self.st.get('gate') or self.run or self.p.d['pilot'].get('level', 1) < D['level']:
            return None
        if self.p.use_ammo(D['cpu']) is None:
            return None
        with self.p.lock:
            self.st['gate'] = True
            self.p.dirty = True
        self.log('   Eternal CPU: X-BL\'de kapı')
        return [KAPI.screen('The Eternal Black Light gate has opened.', big=True), self.info_cmd()]

    def portals(self, map_id):
        import map_links as H
        if not self.own_bl(map_id) or not (self.st.get('gate') or self.run):
            return []
        w, h = H.map_size(map_id)
        return [dict(gateId=PORTAL, x=w // 2, y=h // 2 - 1500, target=0, designId=D['portal'], gate='ebl', windowed='ebl')]

    def gate_jump(self):
        """X-BL kapısına atlandı: koşu yoksa başlar, varsa kaldığı odaya -> (hedef, mesajlar)."""
        if not self.run:
            with self.p.lock:
                self.st['run'] = dict(wave=0, points=0, option=[], weight={}, active={}, uridium=0, start=time.time())
                self.st['gate'] = False
                self.p.dirty = True
            self.log('   Eternal Black Light: koşu başladı')
        return self.room_map(), []

    # ------------------------------------------------------------ dalgalar
    def wave_in_lap(self, done=None):
        """Sıradaki dalga (1-51) ve tur (1…): tamamlanan dalga sayısından."""
        done = self.run['wave'] if done is None else done
        return done % D['type'] + 1, done // D['type'] + 1

    def room_map(self):
        w, lap = self.wave_in_lap()
        room = D['waves'][w - 1]['room']
        return D['maps'][room - 1]

    def waves(self):
        """Bu odanın kalan dalgaları (koşu sırası: tamamlanan sayısından)."""
        w, lap = self.wave_in_lap(self.start_done)
        room = D['waves'][w - 1]['room']
        return [x for x in D['waves'] if x['room'] == room and int(x['name']) >= w]

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        w, lap = self.wave_in_lap(self.start_done + i)
        f = D['kind_multiplier'] ** (lap - 1)
        k = wave.get('multiplier', 1.0)
        PS.scale_npc(n, f * k, f * k, f * k)
        r = self.run
        if r['uridium'] >= D['uridium_limit']:
            n.d['reward']['uridium'] = 0                  # koşunun uridyum sınırı
        else:
            r['uridium'] += n.d['reward']['uridium']
        return n

    def attach(self, world):
        self.world = world
        if not self.run:
            world.add_gate(self.exit_portal(world))
            return None
        if int(world.map_id) != int(self.room_map()):
            # odanın son dalgası bitmiş (oda geçişleri kontrol noktalarında): kontrol noktasında çıkış yapılıp girilmiş. Portallar
            # dünyayla gidiyordu; koşu eski odada 11. dalgayla çıkışsız sürüyordu (canlı test H77). Portallar yeniden, dalga yok
            self.checkpoint_gates(world)
            world.send([self.info_cmd(), self.booster_cmd(), self.rank_cmd()])
            return None
        self.start_done = self.run['wave']
        world.gate = PS.Run(world, self, break_sec=2)
        world.send([self.info_cmd(), self.booster_cmd()])
        return world.gate

    def wave_started(self, i):
        w, lap = self.wave_in_lap(self.start_done + i)
        self.world.send([KAPI.screen('Eternal Black Light - Wave %d (lap %d)' % ((lap - 1) * D['type'] + w, lap), big=True)])

    def wave_done(self, i, now):
        r = self.run
        with self.p.lock:
            r['wave'] += 1
            done = r['wave']
            record = done > self.st.get('best', 0)
            if record:
                self.st['best'] = done
                self.st['best_at'] = int(time.time() * 1000)
            self.p.dirty = True
        self.p.ach('gate_wave', type='ETERNAL_GATE', wave=done)       # başarım: "Eternal Gate'te N. dalgaya ulaş"
        if record:
            self.p.ach('record_ebl')                  # şampiyon başarımı: sıralamada tek oyuncu, kişisel rekor birinci
        w = (done - 1) % D['type'] + 1
        pts = D['control'].get(str(w))
        self.world.send([('EternalBlacklightWaveInfoCommand', self.wave_info())])
        if not pts:
            return 'ongoing'
        with self.p.lock:
            r['points'] += pts
            self.p.dirty = True
        if not r['option']:
            self.roll()
        self.checkpoint(done, pts)
        return 'halt'

    def checkpoint_gates(self, w):
        x, y = w.map_w // 2, w.map_h // 2
        w.add_gate(dict(gateId=PORTAL + 1, x=x - 1200, y=y, target=self.room_map(), designId=D['portal'], gate='ebl', arrival=(10500, 6550)))
        w.add_gate(self.exit_portal(w, side=True))

    def checkpoint(self, done, pts):
        w = self.world
        self.checkpoint_gates(w)
        w.send([KAPI.screen('Checkpoint! +%d booster point%s. Continue or leave (your progress is kept).' % (pts, 's' if pts > 1 else ''),
                            big=True), self.booster_cmd(), self.info_cmd(), self.rank_cmd()])
        self.log('   EBL kontrol noktası: dalga %d, +%d puan' % (done, pts))

    def exit_portal(self, world, side=False):
        bl = {1: 306, 2: 307, 3: 308}.get(self.p.d['pilot'].get('factionId'), 306)
        return dict(gateId=PORTAL + 2, x=world.map_w // 2 + (1200 if side else 0), y=world.map_h // 2, target=bl, designId=1, gate='ebl',
                    exit=True)

    def on_death(self):
        """Tek can: koşu biter, son tamamlanan dalganın kademesinin ödülü."""
        r = self.run
        if not r:
            return 0
        done = r['wave']
        tier = next((t for t in D['death_reward'] if t['en_az'] <= done <= t['max_count']), None)
        msgs = []
        if tier and done:
            msgs += self.m.prize(D['part'], tier['part'])
            if tier['iac'] and random.random() < SET.chance('drop', D['iac'][2], 'mod'):
                msgs += self.m.prize(D['iac'][0], D['iac'][1])
        with self.p.lock:
            self.st['run'] = None
            self.p.dirty = True
        self.log('   EBL bitti: %d dalga; %s' % (done, '%d Blacklight Shard' % tier['part'] if tier and done else 'ödül yok'))
        if self.m:
            msgs += self.m.apply_stats()             # boosterlar kalktı
        self.world.send(msgs + [KAPI.screen('Eternal Black Light ended at wave %d.' % done, big=True), self.info_cmd(), self.rank_cmd()])
        return 0

    def revive(self):
        pass

    # ------------------------------------------------------------ boosterlar
    def roll(self):
        """Üç seçenek: tür ağırlıkla (seçilenlerin ağırlığı azalır), kademe 60/30/10."""
        r = self.run
        pool = list(D['boosters'])
        out = []
        for _ in range(3):
            weights = [r['weight'].get(str(b['type']), 1.0) for b in pool]
            b = random.choices(pool, weights)[0]
            pool.remove(b)
            vals = b['values']
            tier = random.choices(range(len(vals)), D['booster_tier'][:len(vals)])[0]
            out.append([b['type'], vals[tier]])
        r['option'] = out

    def choose(self, f):
        """EternalBlacklightChooseOptionRequest {choosenOption} -> mesajlar."""
        r = self.run
        if not r or r['points'] <= 0 or not r['option']:
            return [self.booster_cmd()]
        i = int(f.get('choosenOption') or 0)
        i = i - 1 if 1 <= i <= 3 else i               # istemci 0-2 ya da 1-3 gönderebilir
        if not 0 <= i < len(r['option']):
            return [self.booster_cmd()]
        t, v = r['option'][i]
        with self.p.lock:
            r['active'][str(t)] = r['active'].get(str(t), 0) + v
            r['weight'][str(t)] = r['weight'].get(str(t), 1.0) * D['booster_decay']
            r['points'] -= 1
            self.roll()
            self.p.dirty = True
        self.log('   EBL booster: tür %d +%d%% (toplam %d%%)' % (t, v, r['active'][str(t)]))
        return (self.m.apply_stats() if self.m else []) + [self.booster_cmd()]

    def mods(self, map_id):
        """Bu modun haritasındayken boosterların bonusları (profil.mods'a)."""
        r = self.run
        if not r or int(map_id) not in D['maps']:
            return {}
        keys = {b['type']: b['anahtar'] for b in D['boosters']}
        return {keys[int(t)]: v / 100.0 for t, v in r['active'].items() if int(t) in keys}

    # ------------------------------------------------------------ göstergeler
    def wave_info(self):
        r = self.run or {}
        return dict(furthestWave=int(self.st.get('best', 0)), currentWave=int(r.get('wave', 0)))

    def booster_cmd(self):
        r = self.run or {}
        opts = (r.get('option') or []) + [[0, 0]] * 3
        b = lambda t, v: mod('EternalBlacklightBoosterCommand', value=int(v), boosterType=int(t))
        return ('EternalBlacklightBoosterInfoCommand', dict(
            option1=b(*opts[0]), option2=b(*opts[1]), option3=b(*opts[2]),
            skillPointInfo=mod('EternalBlacklightSkillPointInfoCommand', skillPoint=int(r.get('points', 0))),
            currentBooster=[b(int(t), v) for t, v in sorted((r.get('active') or {}).items())]))

    def info_cmd(self):
        return ('EternalBlacklightInfoCommand', dict(
            waveInfo=mod('EternalBlacklightWaveInfoCommand', **self.wave_info()),
            cpuInfoCommand=mod('EternalBlacklightCpuInfoCommand', cpuCount=int(self.p.ammo(D['cpu']))),
            boosterInfoCommand=mod('EternalBlacklightBoosterInfoCommand', **self.booster_cmd()[1])))

    def when(self):
        """Rank sekmesinin TIME sütunu: istemci metni olduğu gibi yazıyor; ham ms damgası "1792220704339" görünüyordu (H76).
        Biçim kayıttaki seyir defteri tarihleri gibi."""
        t = self.st.get('best_at')
        if not t:
            return ''
        return time.strftime('%Y-%m-%d %H:%M', time.localtime(float(t) / (1000.0 if float(t) > 1e11 else 1.0)))

    def rank_cmd(self):
        """Rank sekmesi: sunucudaki oyuncular (en ileri dalga)."""
        import community as TP
        row = lambda r: mod('EternalBlacklightRankModule', waves=int(r[2]), name=r[1].d['pilot'].get('userName', ''), rank=r[0],
                            lastUpdateTime=self.when() if r[1] is self.p else '')
        top, me = TP.ranking(self.p, lambda x: int(((x.d.get('pve') or {}).get('ebl') or {}).get('best', 0)))
        info = mod('EternalBlacklightRankInfoCommand', topRankers=[row(r) for r in top], myRank=row(me))
        # Rank sekmesi yalnız etkinlik sarmalını tanıyor (Astral'ın RogueLiteRankEventInfoCommand'ı gibi); isEventEnabled olmadan
        # "No ranking boards are available at the moment." (canlı test H76)
        return ('EternalBlacklightRankingEventInfoCommand', dict(playerRankRanges=RK.ranges(RK.EBL), rankInfoCommand=info,
                                                                isEventEnabled=True))
