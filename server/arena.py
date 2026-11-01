"""Zorluk seçmeli arena kapıları (yol haritası Aşama 8; veri data/pve_modes.json <- tools/pve_modes.py): Voyagers' Ascent ve
Trinity Trials.

İkisinin ortak akışı: X-1 ve X-8'de portal; portala atlayınca (J) istemcinin kapı penceresi açılır (VoyagersGateWindowCommand /
TrinityTrialsGateWindowCommand: zorluklar, ücretsiz giriş, jeton); pencereden giriş isteği (VoyagersGateEnterRequest {isFree,
instanceLevel} / TrinityTrialsGateEnterRequest {attributeType, difficulty}) -> kapı haritasına atlanır; 20 dalga (pve_ortak.Kosu);
ölünce koşu biter (mod haritasında yeniden doğma yok). Günlük giriş haritaya göre (X-1 ve X-8 ayrı): 1 ücretsiz (VIP rozeti +1 / +2),
fazlası jetonla (Voyagers' Oath Token, Trinity Token). Geçiş (gecis.Gecis): bitişlerin puanıyla ücretsiz ve VIP ödülleri.
Voyagers' Ascent: 5 zorluk (bir öncekini 3 yıldızla bitirince açılır); süreye göre 1-3 yıldız (15/10/5 dk); yıldız ödülleri ve geçiş
puanı; 3 yıldız bir ek ücretsiz giriş verir; jeton yalnız bitirince düşer. Voidmare: 5 sn hasar almaz ve oyuncu 500 birim içindeyse
saniyede bir canın %5'i kadar füze.
Trinity Trials: Hellfire (ısıl, pazartesi/çarşamba/cuma) ve Genome (aşındırıcı, salı/perşembe/cumartesi), pazar ikisi; zorluk OS
modülünün seviyesiyle açılır (1/6/11/21/31); her 5 dalgada Quantum Prism, Xyralith ve geçiş puanı; bitince donanım (sayı ve olasılık
zorluğa göre, kayıttaki ödül açıklaması; %5 top, %95 kırıcı; nitelik OS seviyesinin tablosundan). OS modülü (Orbital Sweeper):
Quantum Prism'le yükseltilir, süre Xyralith'le atlanır (TrinityTrialsDropLevelCommand / OptionalRequest).
Not: bu istemci sürümünde parçacık silahı (top, kırıcı, mermi) sistemi protokolde yok (yol haritası Aşama 9): düşen donanım depoda
durur. Singularity Drive / Gravity Lens de yok: Voyagers'ın SD/CGL ödülleri depoda.
Profilde: pve {voyagers|trinity: {gun, girisler {X-1: n}, bonus, acik (Voyagers), os {seviye, bitis, hedef} (Trinity), en_iyi …}}.
"""
import datetime, json, math, os, random, time

import settings as SET
import mode_passes as GC
import map_links as H
import galaxy_gates as KAPI
import pve_common as PS

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'pve_modes.json'), encoding='utf8'))
PORTAL_BASE = 153900000


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def loot_prob(loot, a):
    lo, hi = (a[0], a[1]) if isinstance(a, list) else (a, a)
    return dict(_='LootProbabilityModule', lootId=loot, minLootAmount=int(lo), maxLootAmount=int(hi), probabilityPercentage=100.0)


class Arena:
    """Voyagers ve Trinity'nin ortağı. Alt sınıf: key, ad, D, window(), enter_map(), finish …"""
    key = name = ''
    slot = 0

    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                       # mağaza (ödüller)
        self.send = None                    # oturuma mesaj
        self.run = None                     # sürmekte olan koşu: {zorluk, giris (X-1/X-8), ucretsiz, bas}
        self.reward_pass = GC.Pass(profile, self.key, self.D['reward_pass'], badge=self.D.get('vip'))

    @property
    def st(self):
        s = self.p.d.setdefault('pve', {}).setdefault(self.key, {})
        if s.get('day') != today():
            s.update(day=today(), entries={})
            self.p.dirty = True
        return s

    def vip(self):
        return self.p.resource(self.D['vip']) > 0

    def free_max(self):
        return self.D['free'] + (self.D['vip_extra'] if self.vip() else 0)

    def free_used(self, where):
        if SET.get('no_entry_limit'):                  # panel: ücretsiz girişler tükenmez
            return 0
        return self.st['entries'].get(where, 0)

    def free_left(self, where):
        return max(0, self.free_max() - self.free_used(where)) + self.st.get('bonus', 0)

    def tokens(self):
        return self.p.resource(self.D['token'])

    # ------------------------------------------------------------ portal
    def portals(self, map_id, station):
        cls = H.map_class(map_id)
        if cls not in self.D['entry'] or H.company(map_id) != self.p.d['pilot'].get('factionId'):
            return []
        # haritanın üst ortasında yan yana (resmî sunucu kaydı: 2-1'de Trinity Trials portalı (10700, 3000)); üs üst ortadaysa (2-8)
        # alt ortada
        x, y = KAPI.MAP_W // 2 + 200 - (2 - self.slot) * 1400, 3000
        if station and math.hypot(x - station['posX'], y - station['posY']) < 2500:
            y = KAPI.MAP_H - y
        return [dict(gateId=PORTAL_BASE + self.slot, x=x, y=y, target=0,
                     designId=self.D['portal'], gate=self.key, windowed=self.key, entry=cls)]

    # ------------------------------------------------------------ koşu
    def start(self, difficulty, where, free, dest):
        self.run = dict(difficulty=difficulty, entry=where, free=free, start=None, map=dest, wave=0)
        self.log('   %s: zorluk %d (%s, %s)' % (self.name, difficulty, where, 'ücretsiz' if free else 'token'))

    def use_entry(self):
        """Girişin bedeli: ücretsizse günün hakkı (yoksa bonus), değilse bir jeton."""
        r = self.run
        with self.p.lock:
            if r['free']:
                if self.free_used(r['entry']) < self.free_max():
                    self.st['entries'][r['entry']] = self.free_used(r['entry']) + 1
                else:
                    self.st['bonus'] = max(0, self.st.get('bonus', 0) - 1)
            self.p.dirty = True
        if not r['free']:
            self.p.add_resource(self.D['token'], -1)

    def can_enter(self, where, free):
        return self.free_left(where) > 0 if free else self.tokens() > 0

    def waves(self):
        return self.wave_list(self.run['difficulty'])

    def wave_count(self):
        return len(self.waves())

    def scale(self, n, i, wave):
        return n

    def wave_started(self, i):
        if i == 0 and self.run and self.run['start'] is None:
            self.run['start'] = time.time()
        self.run['wave'] = i
        self.world.send([KAPI.screen('%s - Wave %d/%d' % (self.name, i + 1, self.wave_count()), big=True)])

    def on_death(self):
        """Mod haritasında ölüm: koşu biter (yeniden giriş gerekir)."""
        self.log('   %s: oyuncu yok edildi, koşu bitti (dalga %d)' % (self.name, (self.run or {}).get('wave', 0) + 1))
        self.failed()
        self.run = None
        return 0

    def failed(self):
        pass

    def revive(self):
        pass

    def exit_portal(self, world):
        x, y = world.map_w // 2, world.map_h // 2
        home = KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)
        return dict(gateId=PORTAL_BASE + 50 + self.slot, x=x, y=y, target=home, designId=1, gate=self.key, exit=True,
                    arrival='station')

    def attach(self, world):
        """Mod haritası açıldı: koşu varsa dalgalar, yoksa yalnız çıkış."""
        self.world = world
        if not self.run:
            world.add_gate(self.exit_portal(world))
            return None
        world.gate = PS.Run(world, self, break_sec=4)
        return world.gate

    def grant(self, loot, n):
        if loot.startswith('currency_') and self.world:
            kw = {'currency_uridium': 'uridium', 'currency_credits': 'credits', 'currency_experience': 'ep', 'currency_honour': 'honor'}
            return self.world.grant_loot(loot, n, 'mod')
        return self.m.reward(loot, n) if self.m else []

    def grant_rows(self, rows):
        msgs, got = [], []
        for loot, a in rows:
            n = random.randint(a[0], a[1]) if isinstance(a, list) else a
            msgs += self.grant(loot, n)
            got.append('%s x%d' % (loot, n))
        return msgs, got

    def pass_claim(self, f, cmd_name):
        out = self.reward_pass.claim(int(f.get('rewardLevel', 0)), bool(f.get('isVip')), self.reward)
        if out is None:
            self.log('   %s geçişi: alınamaz (seviye %s)' % (self.name, f.get('rewardLevel')))
            out = []
        return out + [self.reward_pass.cmd(cmd_name)]

    def reward(self, loot, n):
        return self.m.reward(loot, n) if self.m else []


# ====================================================================== Voyagers' Ascent
class Voyagers(Arena):
    key, name, D, slot = 'voyagers', "Voyagers' Ascent", D['voyagers'], 1

    def opened(self):
        return max(1, min(len(self.D['difficulties']), self.st.get('on', 1)))

    def wave_list(self, d):
        return self.D['difficulties'][d - 1]['waves']

    def window(self, where):
        s = self.D['star_sec']
        stars = [dict(_='VoyagersGateStarRewardCommand', instanceLevel=i + 1,
                      star1Loots=[loot_prob(l, a) for l, a in z['rewards']['1']],
                      star2Loots=[loot_prob(l, a) for l, a in z['rewards']['2']],
                      star3Loots=[loot_prob(l, a) for l, a in z['rewards']['3']]) for i, z in enumerate(self.D['difficulties'])]
        return ('VoyagersGateWindowCommand', dict(
            maxOpenLevel=self.opened(), Star1Seconds=s[2], Star2Seconds=s[1], Star3Seconds=s[0], curLootAmount=int(self.tokens()),
            lootId=self.D['token'], maxFreeNum=self.free_max() + self.st.get('bonus', 0),
            freeChallengedNum=self.free_used(where), starRewardLoots=stars))

    def enter(self, f, where):
        """VoyagersGateEnterRequest -> (hedef harita, varış) ya da (None, mesajlar)."""
        lvl, free = int(f.get('instanceLevel') or 1), bool(f.get('isFree'))
        if not 1 <= lvl <= self.opened() or not self.can_enter(where, free):
            self.log('   Voyagers: girilemez (zorluk %d / açık %d, %s)' % (lvl, self.opened(), 'ücretsiz' if free else 'token'))
            return None, [self.window(where), KAPI.screen('You cannot enter this difficulty right now.')]
        self.start(lvl, where, free, self.D['map'])
        return self.D['map'], None

    def wave_done(self, i, now):
        if i + 1 >= self.wave_count():
            self.complete(now)
            return 'halt'
        return 'ongoing'

    def complete(self, now):
        r, w = self.run, self.world
        secs = int(now - (r['start'] or now))
        lim = self.D['star_sec']
        stars = 3 if secs <= lim[0] else 2 if secs <= lim[1] else 1 if secs <= lim[2] else 0
        z = self.D['difficulties'][r['difficulty'] - 1]
        self.use_entry()
        msgs, got = [], []
        if stars:
            msgs, got = self.grant_rows(z['rewards'][str(stars)])
            self.reward_pass.add(z['points'][str(stars)])
        with self.p.lock:
            s = self.st
            best = s.setdefault('best', {})
            if stars > best.get(str(r['difficulty']), 0):
                best[str(r['difficulty'])] = stars
            if stars == 3:
                s['bonus'] = s.get('bonus', 0) + 1                  # 3 yıldız: bir ek ücretsiz giriş
                if r['difficulty'] == s.get('on', 1) and r['difficulty'] < len(self.D['difficulties']):
                    s['on'] = r['difficulty'] + 1
            self.p.dirty = True
        self.p.ach('gate', type='VOYAGERS_GATE')
        msgs += [KAPI.screen('key:log_msg_gg_completed_voyagersascentrial', big=True),          # istemcinin metni; süre ve yıldız
                 KAPI.screen("Voyagers' Ascent %s completed in %s: %d star%s" % (z['name'], fmt(secs), stars, '' if stars == 1 else 's'))]
        w.add_gate(self.exit_portal(w))
        w.send(msgs + [self.reward_pass.cmd('VoyagersPassCommand')])
        self.log('   Voyagers %s: %d sn, %d yıldız; %s' % (z['name'], secs, stars, ', '.join(got) or '-'))
        self.run = None

    def tick(self, now):
        """Voidmare: 5 sn vurulmaz ve oyuncu 500 birim içindeyse saniyede bir canın %5'i."""
        w = self.world
        if w.hero_dead:
            return
        hx, hy = w.hero_pos(now)
        for n in list(w.npcs.values()):
            v = n.d.get('behavior', {}).get('fuse_if_untouched')
            if not v or not n.alive or not n.engaged:
                continue
            nx, ny = n.mover.pos(now)
            if now - max(n.last_hit, getattr(n, 'born', now - 10)) < v['sn'] or math.hypot(hx - nx, hy - ny) > v['range']:
                continue
            if now < getattr(n, 'next_missile', 0):
                continue
            n.next_missile = now + 1.0
            dmg = int(self.p.d['ship'].get('hitMax', 0) * v['ratio'])
            w.send(w.hurt_hero(dmg, n, atype=2, now=now))


def fmt(secs):
    return '%d:%02d' % divmod(int(secs), 60)


# ====================================================================== Trinity Trials
RARITY_NAMES = ['Common', 'Uncommon', 'Rare', 'Epic', 'Masterpiece', 'Legendary', 'Ultimate']


class Trinity(Arena):
    key, name, D, slot = 'trinity', 'Trinity Trials', D['trinity'], 2

    def os_state(self, now=None):
        """OS modülü: süresi dolan yükseltme tamamlanır."""
        now = time.time() if now is None else now
        o = self.p.d.setdefault('pve', {}).setdefault(self.key + '_os', {'level': 1})
        if o.get('end_time') and now >= o['end_time']:
            with self.p.lock:
                o['level'] = o.pop('target', o['level'] + 1)
                o.pop('end_time', None)
                self.p.dirty = True
            self.log('   Trinity OS modülü: seviye %d' % o['level'])
        return o

    def os_level(self):
        return self.os_state()['level']

    def opened(self):
        lv = self.os_level()
        return max(i + 1 for i, z in enumerate(self.D['difficulties']) if lv >= z['os_level'])

    def arenas_today(self, now=None):
        wd = datetime.date.fromtimestamp(time.time() if now is None else now).weekday()
        return [int(a) for a, days in self.D['days'].items() if wd in days]

    def wave_list(self, d):
        return self.D['difficulties'][d - 1]['arenas'][str(self.run['arena'])]

    def window(self, where, now=None):
        today_ = self.arenas_today(now)
        free = self.free_left(where) > 0
        # openAttributes: yalnız bugün açık arenalar (istemci başlıkta hepsini "bugün açık" yazıyor ve seçim listesine koyuyor);
        # param1 o arenada ücretsiz giriş: "0" ve jeton yoksa Go Now mağazayı açıyor (istemci: UITrinityTrialsGateTipsSystem;
        # canlı test H51: kapalı arena seçili geliyordu, ücretsiz giriş varken mağazaya gidiyordu)
        return ('TrinityTrialsGateWindowCommand', dict(
            isFree=free, curLootAmount=int(self.tokens()), lootId=self.D['token'],
            attributeType=today_[0] if today_ else 1, openDifficulty=self.opened(),
            openAttributes=[dict(_='TupleTwoModule', param0=str(a), param1='1' if free else '0') for a in today_]))

    def enter(self, f, where, now=None):
        attr, lvl = int(f.get('attributeType') or 1), int(f.get('difficulty') or 1)
        free = self.free_left(where) > 0
        if attr not in self.arenas_today(now) or not 1 <= lvl <= self.opened() or not self.can_enter(where, free):
            self.log('   Trinity: girilemez (arena %d bugün %s, zorluk %d / %d)' % (attr, self.arenas_today(now), lvl, self.opened()))
            return None, [self.window(where, now), KAPI.screen('This arena or difficulty is not available right now.')]
        dest = self.D['maps'][str(attr)][lvl - 1]
        self.start(lvl, where, free, dest)
        self.run['arena'] = attr
        self.use_entry()                           # Trinity: giriş hakkı girerken düşer
        return dest, None

    def wave_done(self, i, now):
        n = i + 1
        z = self.D['difficulties'][self.run['difficulty'] - 1]
        msgs = []
        if str(n) in z['milestones']:                # her 5 dalgada Quantum Prism, Xyralith, geçiş puanı
            k = z['milestones'][str(n)]
            msgs += self.grant(self.D['kp'], k['qp']) + self.grant(self.D['xy'], k['xy'])
            if k['points']:
                self.reward_pass.add(k['points'])
            msgs.append(KAPI.screen('Wave %d reward: %d Quantum Prism, %d Xyralith, %d pass points' % (n, k['qp'], k['xy'], k['points'])))
        if n >= self.wave_count():
            msgs += self.complete(z)
            self.world.send(msgs)
            return 'halt'
        self.world.send(msgs)
        return 'pause' if n % 5 == 0 else 'ongoing'

    def roll_rarity(self):
        row = self.D['os'][self.os_level() - 1]['rarity']
        return random.choices(range(7), row)[0]

    def drop(self):
        """Bitiş donanımı: zorluğa göre adet (ödül açıklaması), her biri %5 top / %95 kırıcı, nitelik OS tablosundan."""
        z = self.D['difficulties'][self.run['difficulty'] - 1]
        counts, weights = zip(*z['drop'])
        n = random.choices(counts, weights)[0] if sum(weights) >= 100 else (counts[0] if random.random() * 100 < weights[0] else 0)
        eq = self.D['items'][str(self.run['arena'])]
        out = []
        for _ in range(n):
            r = self.roll_rarity()
            out.append(eq['top'][r] if random.random() < self.D['cannon_share'] else eq['breaker'][min(r, len(eq['breaker']) - 1)])
        return out

    def complete(self, z):
        w = self.world
        msgs = []
        got = self.drop()
        for loot in got:
            msgs += self.grant(loot, 1)
        self.p.ach('gate', type='TRINITY_GATE')
        msgs += [KAPI.screen('key:log_msg_gg_completed_trinitytrials', big=True),
                 KAPI.screen('Trinity Trials %s completed! Equipment: %d' % (z['name'], len(got)))]
        w.add_gate(self.exit_portal(w))
        self.log('   Trinity %s bitti: %s' % (z['name'], ', '.join(got) or 'donanım yok'))
        self.run = None
        return msgs + [self.reward_pass.cmd('TrinityTrialsPassCommand')]

    # ------------------------------------------------------------ OS modülü
    def drop_level_cmd(self, now=None):
        now = time.time() if now is None else now
        o = self.os_state(now)
        lv = o['level']
        rows = self.D['os']
        mx = lv >= len(rows)
        nxt = rows[min(lv, len(rows) - 1)]
        cur = rows[lv - 1]
        left = int(max(0, o['end_time'] - now)) if o.get('end_time') else 0
        building = bool(o.get('end_time'))          # yükseltme sürerken pencere atlama bedelini (Xyralith) gösterir; resmî ekran: "Xyralith 9/9"
        skip = self.skip_cost(left)
        cost_id = self.D['xy'] if building else self.D['kp']
        q = lambda r: [dict(_='TupleTwoModule', param0=str(i + 1), param1='%.1f' % v) for i, v in enumerate(r['rarity'])]
        return ('TrinityTrialsDropLevelCommand', dict(
            costLootAmount=skip if building else (0 if mx else nxt['cost']), currentLevel=lv, nextLevel=min(lv + 1, len(rows)), building=bool(o.get('end_time')),
            max=mx, skipConsume=skip, currentLevelQualityRandomList=q(cur), totalBuildSeconds=0 if mx else nxt['sure_sn'],
            lootAmount=int(self.p.resource(cost_id)), nextLevelQualityRandomList=q(nxt), buildSeconds=left, costLootId=cost_id))

    def skip_cost(self, left):
        return int(math.ceil(left / 1000.0)) * self.D['skip_per_minute'] if left else 0      # resmî ekran: kalan 2:29:50 -> 9 Xyralith (1000 sn'de 1)

    def drop_level_optional(self, f, now=None):
        """Yükselt (Quantum Prism) ya da süreyi atla (Xyralith) -> mesajlar."""
        from shop import stack_msg
        now = time.time() if now is None else now
        o = self.os_state(now)
        ok = False
        # eylemi pencerenin durumu belirler (istemcinin gönderdiği costLootId'ye bakılmaz): yükseltme sürmüyorsa yükselt, sürüyorsa atla
        if not o.get('end_time') and o['level'] < len(self.D['os']):
            row = self.D['os'][o['level']]
            if self.p.resource(self.D['kp']) >= row['cost']:
                self.p.add_resource(self.D['kp'], -row['cost'])
                with self.p.lock:
                    o.update(target=o['level'] + 1, end_time=now + row['sure_sn'])
                    self.p.dirty = True
                ok = True
                self.log('   Trinity OS: %d -> %d başladı (%d sn)' % (o['level'], o['target'], row['sure_sn']))
        elif o.get('end_time'):
            cost = self.skip_cost(o['end_time'] - now)
            if self.p.resource(self.D['xy']) >= cost:
                self.p.add_resource(self.D['xy'], -cost)
                with self.p.lock:
                    o['end_time'] = now
                    self.p.dirty = True
                self.os_state(now)
                ok = True
                self.log('   Trinity OS: %d Xyralith ile atlandı' % cost)
        stack = stack_msg('eqt_error_generic') if not ok else dict(_='BaseStackCommand', type=0, enumBaseKey=0, stringBasekey='',
                                                                    argsList=[])
        return [('TrinityTrialsDropLevelOptionalCommand', dict(success=ok, stack=stack)), self.drop_level_cmd(now)]

    def ui(self, f, now=None):
        """TrinityTrialsUIRequest {optionalType: 0 INIT, 1 PASS, 2 DROP_LEVEL} (kayıttaki yanıtlar)."""
        t = int(f.get('optionalType') or 0)
        if t == 1:
            return [self.reward_pass.cmd('TrinityTrialsPassCommand', now)]
        if t == 2:
            return [self.drop_level_cmd(now)]
        return [self.reward_pass.cmd('TrinityTrialsPassCommand', now),
                ('TrinityTrialsRewardDescriptionCommand', dict(rewardDescriptionList=[dict(x) for x in self.D['reward_description']])),
                self.drop_level_cmd(now)]

    def reward(self, loot, n):
        """Geçişin paketleri (package_trinity-*): içerikleri."""
        if loot in self.D['packages']:
            out = []
            for l, k in self.D['packages'][loot]:
                out += self.m.reward(l, k * n) if self.m else []
            return out
        return super().reward(loot, n)
