"""Uzaylı yetenekleri (yol haritası Aşama 4): data/uzayli_yetenekleri.json'da istemcinin npcId'siyle tanımlı, haritadaki ve Galaksi
Kapısı'ndaki aynı uzaylıya birlikte uygulanır. dunya.py çağırır: vuruşta (on_hit), her adımda (tick), uzaylının lazer atışında
(laser_factor, after_shot, extra_target), ölümde (on_kill).

Yetenekler (veri alanları uzayli_yetenekleri.json'un açıklamasında):
  çağırma, yenilenme, ölünce doğurma, çağırdıkları yaşarken dokunulmazlık   dunya.py'deki kancalar (Aşama 1); burada öfkeli çağrı
  çağırdıkları yaşarken onarım ve öfke (Battleray)     son sure_sn içinde iki ya da daha çok saldıran (oyuncu + P.E.T.)
  can eşiğinde çağırma (Invoke XVI: 8 Impulse II)      bir kez
  gizlenme bozma (Mindfire Behemoth)                  yakındaki gizli oyuncu görünür olur
  yavaşlatan atış (Barb, Stinger, Saboteur, Behemoth)  isabet eden lazer: hız sınırı (küre, 120) ya da oranla yavaşlatma
  birden çok hedef (Behemoth)                          kritik canda P.E.T.'e de ateş eder
  roket (StreuneR) ve roket fırlatıcı (Annihilator)    ayrı beklemeyle oyuncuya roket
  tekillik (The Stinger, Reflector Mimesis)            saniyede hasar, toplam sınırlı, menzil içinde (Reflector'da girdap yok)
  temasla patlama (Kamikaze Mimesis)                   lazer atmaz; yaklaşınca patlar (bomba hasarı), ödülsüz kalkar
  kaybolma (Emperor Lordakium)                         belli hasardan sonra uzağa ışınlanır, iki sahte belirir (vurulunca patlar);
                                                       gizliyken can ve kalkan doldurur
  can eşiğinde kamikaze (Barracuda)                    canı azalınca kırmızı parlar, yerinde bekler, sonra yaklaşır ve patlar
  ters kontrol (Boss StreuneR, Boss Saimon)            kalkanı bitince / canı azalınca oyuncunun hareketi bir süre ters
  ölünce çağırdıkları dağılır (Cubikon)                Protegit'ler kimseyi kovalamadan dolaşır, sonra kaybolur
  yapışkan bomba (Emperor Kristallon)                  aralıkla gecikmeli büyük hasar (tek oyunculu: grup boyuna bölünür)
  hız becerisi ve kapsüller (Emperor Sibelon)          kalkanı biterken hızlanır; haritada kapsüller belirir, Emperor toplarsa
                                                       güçlenir (can, kalkan, hasar), oyuncu yakınından geçerse kapsül yok olur
  iyileştirme (Streuner Specialist, Aider, Medic Mimesis)  aralıkla yakındaki sınıf uzaylılarının gövdesini onarır (kendini değil)
  izleme (Aider Streuner)                              Recruit Streuner'in çevresinde dolaşır (koruyucu düzeni: dunya.think)
  periyodik çağırma (Rocketeer, Strokelight Barrage)   savaşırken vurulmasa da aralıkla çağırır (en çok kadar yaşarken)
  mayın bırakma (Agatus, Strokelight Barrage)         canı eşiğin altına inince aralıkla ACM-1 mayını bırakır (savas_esya.alien_mine)
  ölüm ışını (Gygerim Overlord)                       oyuncu uzaktayken (haritanın dışından) aralıkla büyük hasar
  oyuncunun hızı (Seeker Rocket, Hooligan)             hızı oyuncununkine eşitlenir (+ek; Hooligan'da yalnız kritik canda)
  ters atış (Streuner Turret)                          isabet eden lazer oyuncunun kontrollerini bir süre ters çevirir
  EMP darbesi (Obscured Mimesis, Hitac Underboss, Spookfish)  oyuncunun hedefi sıfırlanır, gizlenme biter, mini harita parazitlenir
  düşük can (dusuk_can; harita başıboşları)            %20'nin altında oyuncunun tersindeki kenar noktasına kaçar (menzildeyse
                                                       ateş eder), orada durup yenilenir, vurulunca karşılık vermez (fandom Low health, Parking)
"""
import json, math, os, random, time

import ayar as AY
import harita as H
import harita_duzeni as HD
from eski_protokol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
Y = json.load(open(os.path.join(HERE, 'data', 'uzayli_yetenekleri.json'), encoding='utf8'))
ABILITIES = {int(k): v for k, v in Y['yetenekler'].items()}
LOW = Y['dusuk_can']               # düşük canda kaçış ve park (fandom Low health, Parking)
CAPSULES = Y['kapsul_turleri']
BUFF_CAPSULE = 45                  # AssetTypeModule.AssetType (istemci): BUFF_CAPSULE
RING_RADIUS = 300                  # kapsül toplanınca Emperor'un çevresindeki halka (birim; uyarlama, canlıda ayarlanacak)
EMP_NOISE_SN = 5                   # Behemoth'un gizlenme bozan EMP'sinde mini harita paraziti (saniye; uyarlama)
SINGULARITY_TARGET = 21            # VisualModifierCommand.VisualModifier (istemci): tekilliğin hedefindeki altın girdap
MIRRORED_CONTROLS = 27             # VisualModifier: istemci oyuncunun hareketini ters çevirir (ters kontrol)
RED_GLOW = 30                      # VisualModifier: kırmızı parıltı (Barracuda'nın kamikaze beklemesi)
CAPSULE_BASE = 152000000           # kapsül varlık kimlikleri


def mod(name, **f):
    f['_'] = name
    return f


def of(d):
    """NPC türünün yetenekleri: npcId'nin yetenekleri + türün kendi "davranis"ı (ikincisi öncelikli; None o yeteneği kapatır: Kappa
    Annihilator'ın fırlatıcısı); not alanları ('_') atılır."""
    out = {k: v for k, v in ABILITIES.get(d.get('npc_kimlik'), {}).items() if not k.startswith('_')}
    out.update(d.get('davranis') or {})
    return {k: v for k, v in out.items() if v is not None}


def asset_create(aid, kind, x, y, name='', design=0):
    """Haritaya varlık (kapsül): kayıttaki AssetCreateCommand biçimi (2-1 istasyon taretleri)."""
    return ('AssetCreateCommand', dict(designId=design, clanId=0, showBubble=True, userName=name, assetId=aid, expansionStage=0,
                                       modifier=[], type=mod('AssetTypeModule', typeValue=kind), detectedByWarnRadar=True,
                                       invisible=False, posY=int(y), clanRelation=mod('ClanRelationModule', type=0), clanTag='',
                                       factionId=0, posX=int(x), visibleOnWarnRadar=False))


def asset_remove(aid, kind):
    return ('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=kind), 'uid': aid})


class Yetenekler:
    """Bir dünyanın uzaylı yetenekleri (dunya.World.alien)."""

    def __init__(self, world):
        import dunya                # dunya bu modülü içe aktarır; değerleri dünya kurulurken alınır
        self.w = world
        self.S, self.CFG, self.Mover = dunya.SAVAS, dunya.CFG, dunya.Mover
        self.capsules = {}          # kapsül kimliği -> {x, y, tur, sahip}
        self.next_capsule = CAPSULE_BASE
        self.hero_dots = []         # oyuncunun üzerindeki tekillikler: {npc, bitis, kalan, sn_hasar, sonraki}
        self.mirror_end = 0.0       # ters kontrolün bitişi (üst üste gelen ters atışlar süreyi uzatır, görsel erken kapanmaz)
        self.mirror_gen = 0         # son süre uzatan ters atışın sırası: yalnız onun zamanlayıcısı görseli kapatır

    # ------------------------------------------------------------ yardımcılar
    def dist(self, n, now):
        hx, hy = self.w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        return math.hypot(nx - hx, ny - hy)

    def hero_open(self, now, n=None):
        """NPC abilities share laser retaliation rules, with portal/spawn/cloak protection."""
        w = self.w
        if w.hero_dead or w.jumping or now < w.invuln_until:
            return False
        if (w.abilities.cloaked(now) or w.items.cloaked()) and not (n is not None and n.engaged):      # saldıran uzaylı gizlenmeye aldırmaz
            return False
        return not w.in_peace(*w.hero_pos(now)) or bool(n is not None and w.npc_retaliating(n))

    def adopt(self, parent, child):
        """Uzaylının doğurduğu/çağırdığı: yeniden doğmaz; kapıda dalganın uzaylısı sayılır (dalga o ölmeden bitmez)."""
        child.summoned, child.gate = True, parent.gate
        k = self.w.kapi
        if k and parent.id in k.npcs:
            k.npcs.add(child.id)

    def attacked(self, n, attacker, now):
        n.attackers[attacker or self.w.hid] = now

    def cagiran_bot(self, n):
        """Uzaylıyı son vuran bot gemisi (oyuncu onunla savaşmıyorsa): çağırdıkları ona saldırır (dunya.npc_summon vuran)."""
        uid = n.ab.get('cagiran')
        t = self.w.npcs.get(uid) if uid is not None else None
        return t if t is not None and t.alive and t.bot is not None and not n.engaged else None

    def saldirt(self, c, bot, now):
        """Çağrılan yardımcı hemen saldırır: bot çağırttıysa bota, yoksa oyuncuya."""
        if bot is not None:
            c.engaged, c.bot_hedef = False, bot.id
        else:
            c.engaged = True
        c.next_think = now

    def enraged(self, n, now):
        """Öfke (Battleray): son sure_sn içinde en az "saldiran" kadar farklı saldıran (oyuncu ve P.E.T. ayrı sayılır)."""
        o = n.davranis.get('ofke')
        if not o:
            return False
        return sum(1 for t in n.attackers.values() if now - t <= o.get('sure_sn', 10)) >= o.get('saldiran', 2)

    def extra_summons(self, n, now):
        """Öfkeliyken çağırma sınırına eklenen."""
        return n.davranis['ofke'].get('ek_cagri', 0) if self.enraged(n, now) else 0

    # ------------------------------------------------------------ vuruş
    def on_hit(self, n, dmg, attacker, now, oyuncuya=True):
        """Uzaylı vuruldu (hasar uygulandıktan sonra): saldıran, can eşiğinde çağırma, kaybolma. oyuncuya: oyuncuya yönelik etkiler (ters
        kontrol, EMP) uygulanır mı (bot vurduysa yalnız oyuncu yakındaysa: bot/govde.npc_vur)."""
        self.attacked(n, attacker, now)
        n.ab.pop('gizli', None)                                  # Emperor Lordakium bulundu: dolum durur
        for i, c in enumerate(n.davranis.get('can_esiginde_cagir', [])):
            key = 'esik_%d' % i
            if key not in n.ab and n.hp <= n.d['hp'] * c['oran']:
                n.ab[key] = now
                self.summon(n, c['tur'], c['adet'], now)
        t = n.davranis.get('ters_kontrol') if oyuncuya else None
        if t and 'ters' not in n.ab and n.hp > 0 and (n.shield <= n.d['kalkan'] * t['kalkan_orani'] if 'kalkan_orani' in t
                                                      else n.hp <= n.d['hp'] * t['can_orani']):
            n.ab['ters'] = now                                   # bir kez
            self.reverse_controls(n, t['sn'])
        if 'kalkan_bitince_emp' in n.davranis and oyuncuya:      # Obscured Mimesis: kalkanı her bitişinde bir EMP darbesi
            if n.shield > 0:
                n.ab.pop('emp_kalkan', None)
            elif 'emp_kalkan' not in n.ab and n.hp > 0:
                n.ab['emp_kalkan'] = now
                self.emp(n, now)
        c = n.davranis.get('kritik_emp') if oyuncuya else None
        if c and 'emp_kritik' not in n.ab and 0 < n.hp <= n.d['hp'] * c['can_orani']:
            n.ab['emp_kritik'] = now                             # Spookfish: kritik canda EMP (bir kez)
            self.emp(n, now)
        k = n.davranis.get('kaybolma')
        if k and dmg > 0 and n.alive and n.hp > 0:
            # yalnız gövdenin kaybı (darkorbitwiki: "after losing ~1.280.000 HP"); kalkan hasarı da sayılıyordu, 6,8 M kalkanlı patron
            # neredeyse tam canda kayboluyordu (oyuncu bildirimi 2026-10-30). Gizliyken dolan can sayılmaz
            prev = n.ab.get('son_can', n.d['hp'])
            n.ab['son_can'] = n.hp
            n.ab['kayip'] = n.ab.get('kayip', 0) + max(0, prev - n.hp)
            if n.ab['kayip'] >= k['hasar']:
                n.ab['kayip'] = 0
                self.vanish(n, k, now)

    def visual(self, uid, modifier, on):
        return ('VisualModifierCommand', dict(userId=uid, modifier=modifier, attribute=0, additionalAttribute='', count=0,
                                              activated=on))

    def reverse_controls(self, n, sec):
        """Ters kontrol (Boss StreuneR, Boss Saimon, Streuner Turret): oyuncunun hareketi sec saniye ters (istemci çevirir:
        MIRRORED_CONTROLS). Zaten ters ise süre uzar; görsel son bitişte kapanır."""
        w, now = self.w, time.time()
        if now >= self.mirror_end:
            w.send([self.visual(w.hid, MIRRORED_CONTROLS, True)])
        if now + sec > self.mirror_end:                              # süreyi uzatan atış: eski kapatma zamanlayıcıları etkisiz kalır
            self.mirror_end = now + sec
            self.mirror_gen += 1
            gen = self.mirror_gen

            def off():
                if gen == self.mirror_gen:
                    self.mirror_end = 0.0
                    w.send([self.visual(w.hid, MIRRORED_CONTROLS, False)])
            w.later(sec, off)
        w.log('   %s kontrolleri ters çevirdi (%d sn)' % (n.d['ad'], sec))

    def summon(self, n, tur, count, now):
        w = self.w
        x, y = n.mover.pos(now)
        for i in range(count):
            a = 2 * math.pi * i / max(1, count)
            c = w.spawn_npc_at(tur, x + math.cos(a) * 300, y + math.sin(a) * 300)
            self.adopt(n, c)
            self.saldirt(c, self.cagiran_bot(n), now)
            n.children.add(c.id)
        w.log('   %s %d %s çağırdı (can %%%d)' % (n.d['ad'], count, self.CFG['tipler'][tur]['ad'], 100 * n.hp // max(1, n.d['hp'])))

    def far_spot(self, near, far):
        """Oyuncudan en az "far" uzakta (yoksa en uzak deneme) bir nokta; near: (x, y) yakınında arar (None: haritanın her yeri)."""
        w = self.w
        hx, hy = w.hero_pos()
        best, bd = None, -1
        for _ in range(40):
            if near:
                a, r = random.uniform(0, 2 * math.pi), random.uniform(far * 0.3, far)
                x, y = near[0] + math.cos(a) * r, near[1] + math.sin(a) * r
            else:
                x, y = random.uniform(600, w.map_w - 600), random.uniform(600, w.map_h - 600)
            x, y = min(max(x, 500), w.map_w - 500), min(max(y, 500), w.map_h - 500)
            d = math.hypot(x - hx, y - hy)
            if d >= far:
                return int(x), int(y)
            if d > bd:
                best, bd = (int(x), int(y)), d
        return best

    def vanish(self, n, k, now):
        """Emperor Lordakium: uzağa ışınlanır, iki sahtesi başka yerlerde belirir; oyuncunun seçimi bırakılır."""
        w = self.w
        # gerçeği ve sahteleri oyuncunun görüşü içinde, ayrı yönlerde (wiki: "reappears together with two fake Lordakiums"; görüşün
        # dışına, 2.500 birim öteye gidiyorlardı, haritada görünmüyor, bulunamıyordu: oyuncu bildirimi 2026-10-30)
        hx, hy = w.hero_pos(now)
        spots = self.ring_spots(hx, hy, k.get('uzaklik', 1500), k.get('sahte', 2) + 1)
        x, y = spots.pop(0)
        n.mover = self.Mover(x, y)
        n.engaged = False
        n.next_think = now + 2
        n.ab['gizli'] = now
        msgs = []
        if w.target == n.id:
            w.target, w.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if n.id in w.visible:
            w.visible.discard(n.id)
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        w.send(msgs)
        fake = self.fake_type(n, k)
        for fx, fy in spots:
            f = w.spawn_npc_at(fake, fx, fy)
            f.summoned, f.gate = True, n.gate
            f.ab['omur'] = now + k.get('sahte_omur_sn', 90)
        w.log('   %s kayboldu: (%d,%d), %d sahte' % (n.d['ad'], x, y, k.get('sahte', 2)))

    def ring_spots(self, hx, hy, r, count):
        """Oyuncunun çevresinde r uzaklıkta, eşit açılarla (rastgele sırayla) count nokta; harita içinde."""
        w, a0 = self.w, random.uniform(0, 2 * math.pi)
        out = [(int(min(max(hx + math.cos(a0 + 2 * math.pi * i / count) * r, 500), w.map_w - 500)),
                int(min(max(hy + math.sin(a0 + 2 * math.pi * i / count) * r, 500), w.map_h - 500))) for i in range(count)]
        random.shuffle(out)
        return out

    def fake_type(self, n, k):
        """Sahte Emperor türü (görünüşü gerçeğinin aynısı; 1 can, ateş etmez, ödülsüz, vurulunca patlar)."""
        key = 'sahte_' + n.tip
        if key not in self.CFG['tipler']:
            self.CFG['tipler'][key] = dict(ad=n.d['ad'], model=n.model, hp=1, kalkan=0, hasar=0, hiz=n.d['hiz'], saldirgan=False,
                                      odul=dict(ep=0, onur=0, kredi=0, uridyum=0), kargo={}, sayilmaz=True,
                                      davranis={'olunce_patla': {'hasar': k.get('patlama', 60000),
                                                                 'yaricap': k.get('patlama_yaricap', 500)}})
        return key

    # ------------------------------------------------------------ uzaylının atışı
    def laser_factor(self, n, now):
        """Uzaylının lazer hasarı çarpanı: öfke (Battleray: RSB-75), Emperor Sibelon'un hasar kapsülleri."""
        f = 1 + n.ab.get('hasar_bonus', 0)
        if self.enraged(n, now):
            f *= n.davranis['ofke'].get('hasar_carpani', 1)
        return f

    def laser_color(self, n, now):
        """Uzaylının lazer görseli (AttackLaserRunCommand.laserColor): öfkeli Battleray RSB-75 atar (wiki: "uses RSB-75 instead of
        UCB-100"; ofke.lazer_renk, RSB-75 = 6 gibi). Görsel yokken öfke yalnız hasarda kalıyor, oyunda fark edilmiyordu (bildirim
        2026-10-28)"""
        if self.enraged(n, now):
            return n.davranis['ofke'].get('lazer_renk', 0)
        return 0

    def after_shot(self, n, now, hit):
        """Uzaylının lazeri oyuncuya isabet etti: ters atış (Streuner Turret), yavaşlatan atış."""
        t = n.davranis.get('ters_atis')
        if t and hit and not self.w.hero_dead and now >= n.ab.get('ters_sonraki', 0):
            n.ab['ters_sonraki'] = now + t['bekleme_sn']
            self.reverse_controls(n, t['sn'])
        s = n.davranis.get('yavaslatan_atis')
        if not s or not hit or self.w.hero_dead or not AY.get('yavaslatan_atis'):          # panel: kapatılabilir
            return
        if s.get('menzil') and self.dist(n, now) > s['menzil']:
            return
        w = self.w
        src = 'yavaslatma_%s' % n.tip
        if 'hiz' in s:
            w.hero_etki.remove('hiz_siniri', source=src)          # yenilenir, birikmez
            w.hero_effect('hiz_siniri', s['sn'], s['hiz'], source=src)
        else:
            w.hero_etki.remove('yavas', source=src)
            w.hero_effect('yavas', s['sn'], s['oran'], source=src)

    def extra_target(self, n, now):
        """Birden çok hedef (Mindfire Behemoth): kritik canda P.E.T.'e de ateş eder."""
        c = n.davranis.get('coklu_hedef')
        return bool(c) and n.hp <= n.d['hp'] * c.get('can_orani', 0.25)

    # ------------------------------------------------------------ her adım
    def tick(self, now):
        w = self.w
        for n in list(w.npcs.values()):
            if not n.alive or not n.davranis and not n.ab or not w.sahibi(n, now):     # ortak haritada uzaylının sahibi işler
                continue
            if 'omur' in n.ab and now >= n.ab['omur']:
                self.expire(n)
                continue
            d = n.davranis
            if 'cagrilar_yasarken_onarim' in d:
                self.summon_repair(n, now)
            if 'gizlenme_bozar' in d:
                self.uncloak(n, now)
            if 'roket' in d:
                self.rocket(n, now)
            if 'tekillik' in d:
                self.singularity(n, now)
            if 'yapiskan_bomba' in d:
                self.bomb(n, now)
            if 'temasla_patla' in d:
                self.kamikaze(n, now)
            if 'kamikaze_esik' in d:
                self.threshold_kamikaze(n, now)
            if 'hiz_becerisi' in d:
                self.speed_skill(n, now)
            if 'kaybolma' in d and n.ab.get('gizli'):
                self.hidden_regen(n, now)
            if 'iyilestirme' in d:
                self.heal(n, now)
            if 'izle' in d:
                self.follow(n, now)
            if 'periyodik_cagir' in d:
                self.periodic_summon(n, now)
            if 'mayin_birak' in d:
                self.drop_mines(n, now)
            if 'olum_isini' in d:
                self.death_ray(n, now)
            if 'periyodik_emp' in d:
                self.periodic_emp(n, now)
            if 'hiz_oyuncu' in d:
                self.match_speed(n, now)
            if n.bot_hedef is not None and not n.engaged:
                self.bota_yetenekler(n, now)
        self.dot_tick(now)          # tik başına bir kez (bota_yetenekler'in sonunda kalınca Singularity hasarı ve kapsüller hiç işlemiyordu)
        self.capsule_tick(now)

    # ------------------------------------------------------------ bota karşı (uzaylı bir botla savaşırken)
    def bota_yetenekler(self, n, now):
        """Uzaylı bir bot gemisiyle savaşırken saldırı yetenekleri bota: roket, yapışkan bomba, temasla patlama, kamikaze, tekillik,
        ölüm ışını, periyodik çağırma (yardımcılar bota). Oyuncuya özgü etkiler (EMP, gizlenme bozma, yavaşlatma, oyuncunun çevresine
        mayın, hız eşleme) bota uygulanmaz. Önceden yetenekler yalnız oyuncuyla savaşırken çalışıyordu (kullanıcı bildirimi 2026-10-30)."""
        from bot import govde as BG
        w, d = self.w, n.davranis
        t = w.npcs.get(n.bot_hedef)
        if t is None or not t.alive or t.bot is None or n.etki.frozen(now):
            return
        nx, ny = n.mover.pos(now)
        tx, ty = t.mover.pos(now)
        uz = math.hypot(tx - nx, ty - ny)

        def vur(dmg, gecikme=0.0):
            uid, hid = n.id, t.id

            def at():
                h = w.npcs.get(hid)
                if h is not None and h.alive and h.bot is not None:
                    BG.bot_hasar(w, h, int(dmg), uid, time.time(), npc=w.npcs.get(uid) or n)
            w.later(gecikme, at) if gecikme else at()
        r = d.get('roket')
        if r and now >= n.ab.get('roket', 0) and uz <= w.npc_range(n):
            n.ab['roket'] = now + r.get('bekleme_sn', 8)
            if random.random() < self.S['roket_isabet']:
                from eski_protokol import legacy
                BG._yayin(w, [legacy('0|v|%d|%d|H|%d|0|0' % (n.id, t.id, r.get('tur', 1)))], n.id, t.id)
                vur(r['hasar'] * random.uniform(0.85, 1.0), self.S['roket_ucus_sn'])
        b = d.get('yapiskan_bomba')
        if b and uz <= w.npc_range(n) * 2:
            if 'bomba' not in n.ab:
                n.ab['bomba'] = now + b['aralik_sn']
            elif now >= n.ab['bomba']:
                n.ab['bomba'] = now + b['aralik_sn']
                dmg = random.randint(*b['hasar']) if isinstance(b['hasar'], list) else b['hasar']
                vur(dmg / max(1, b.get('grup', 1)), b.get('gecikme_sn', 2))
        k = d.get('temasla_patla')
        if k and uz <= k['yaricap']:
            dmg = k['hasar'] * ((1 - (1 - k['kenarda']) * min(1.0, uz / k['yaricap'])) if 'kenarda' in k else 1)
            vur(dmg)
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(boom + w.remove_npc(n))
            return
        k = d.get('kamikaze_esik')
        if k and n.hp <= n.d['hp'] * k['oran'] and n.hp > 0 and uz <= k['yaricap']:
            vur(n.hp * k['hasar_can_orani'])
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(boom + w.remove_npc(n))
            if not n.gate and not n.summoned:
                w.schedule(random.uniform(*w.respawn_range(n)), 'npc', n.tip)
            return
        s = d.get('tekillik')
        if s and now >= n.ab.get('tekillik', 0) and uz <= s['menzil'] * AY.carpan('npc_menzil'):
            n.ab['tekillik'] = now + s['bekleme_sn']
            for i in range(int(min(s['sure_sn'], s['azami'] / max(1, s['sn_hasar'])))):
                vur(s['sn_hasar'], i + 1.0)
        o = d.get('olum_isini')
        if o and now >= n.ab.get('isin', 0) and uz > o['uzaklik']:
            n.ab['isin'] = now + o['aralik_sn']
            vur(o['hasar'] * random.uniform(0.8, 1.2))
        p = d.get('periyodik_cagir')
        if p and now >= n.ab.get('periyodik', 0):
            n.ab['periyodik'] = now + p['bekleme_sn']
            n.ab['cagiran'] = t.id
            n.children = {c for c in n.children if c in w.npcs and w.npcs[c].alive}
            for e in p['cagrilar']:
                room = e['en_cok'] - sum(1 for c in n.children if w.npcs[c].tip == e['tur'])
                if room > 0:
                    self.summon(n, e['tur'], min(e['adet'], room), now)

    def expire(self, n):
        """Ömrü biten (sahte Emperor): sessizce kalkar."""
        w = self.w
        n.alive = False
        w.npcs.pop(n.id, None)
        msgs = []
        if w.target == n.id:
            w.target, w.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if n.id in w.visible:
            w.visible.discard(n.id)
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        w.send(msgs)

    def summon_repair(self, n, now):
        """Çağırdıkları yaşarken saniyede onarım (Battleray: 600, öfkeliyken 30.000)."""
        if now < n.ab.get('onarim', 0):
            return
        n.ab['onarim'] = now + 1.0
        n.children = {c for c in n.children if c in self.w.npcs and self.w.npcs[c].alive}
        if not n.children or n.hp >= n.d['hp']:
            return
        r = n.davranis['cagrilar_yasarken_onarim']
        amount = n.davranis['ofke'].get('onarim_can_sn', r['can_sn']) if self.enraged(n, now) else r['can_sn']
        n.hp = min(n.d['hp'], n.hp + amount)
        if self.w.target == n.id:
            self.w.send([self.w.selection(n)])

    def uncloak(self, n, now):
        w = self.w
        if not (w.abilities.cloaked(now) or w.items.cloaked()) or w.hero_dead:
            return
        if self.dist(n, now) <= n.davranis['gizlenme_bozar'].get('menzil', 1500):
            w.abilities.reveal()
            w.items.reveal()
            # EMP darbesi (Ö1): istemcinin "EMP Malus Bolt"u mini haritayı parazitler (MapEventsAssemblyHelper.AssembleEmpMalusBolt,
            # 0|n|EMAL|<saniye>; süre uyarlama)
            from eski_protokol import legacy
            w.send([legacy('0|n|EMAL|%d' % EMP_NOISE_SN)])
            w.log('   %s gizlenmeyi bozdu' % n.d['ad'])

    def rocket(self, n, now):
        """Uzaylının roketi ya da roket fırlatıcı salvosu: kendi beklemesiyle, ateş menzilinde."""
        w, r = self.w, n.davranis['roket']
        if (not n.engaged or now < n.ab.get('roket', 0) or n.etki.frozen(now) or not self.hero_open(now, n)
                or self.dist(n, now) > w.npc_range(n)):
            return
        n.ab['roket'] = now + r.get('bekleme_sn', 8)
        m = w.p.mods()
        hit = random.random() < self.S['roket_isabet'] * (1 - m.get('kacinma', 0)) * (1 - n.etki.accuracy_loss(now))
        flight = self.S['roket_ucus_sn']
        if r.get('firlatici'):
            import savas_esya as SE
            tur = SE.LAUNCHER_AMMO.get('ammunition_rocketlauncher_eco-10', {}).get('tur', 1)
            cnt = r.get('adet', 5)
            flight = SE.salvo_time(self.dist(n, now), cnt)        # yerel eğri salvo: hasar son roket varınca
            w.send([SE.salvo(n.id, w.hid, hit, cnt, tur)])
        else:
            from eski_protokol import legacy
            w.send([legacy('0|v|%d|%d|%s|%d|0|0' % (n.id, w.hid, 'H' if hit else 'M', r.get('tur', 1)))])
        dmg = int(r['hasar'] * random.uniform(0.85, 1.0))
        uid = n.id

        def land():
            if w.hero_dead or w.jumping:
                return
            if not hit:
                w.send([('AttackMissedCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=0), targetUserId=w.hid,
                                                     skillColorId=0))])
                return
            w.send(w.hurt_hero(dmg, w.npcs.get(uid) or n, atype=0))
        w.later(flight, land)

    def singularity(self, n, now):
        """The Stinger'ın tekilliği başlar: oyuncunun üzerinde saniyede hasar (dot_tick)."""
        t = n.davranis['tekillik']
        rng = t['menzil'] * AY.carpan('npc_menzil')       # panel: alien firing range
        if not n.engaged or now < n.ab.get('tekillik', 0) or not self.hero_open(now, n) or self.dist(n, now) > rng:
            return
        n.ab['tekillik'] = now + t['bekleme_sn']
        gorsel = t.get('gorsel', True)                     # Reflector Mimesis'in radyasyonu: girdap yok
        if gorsel and not any(d_.get('gorsel') for d_ in self.hero_dots):
            self.w.send([self.singularity_visual(True)])    # canlı test H30: hasar vardı, görsel yoktu
        self.hero_dots.append(dict(npc=n.id, bitis=now + t['sure_sn'], kalan=t['azami'], sn_hasar=t['sn_hasar'], sonraki=now + 1.0,
                                   menzil=rng, gorsel=gorsel))
        self.w.log('   %s tekilliği başladı' % n.d['ad'])

    def kamikaze(self, n, now):
        """Kamikaze Mimesis: oyuncuya yaricap kadar yaklaşınca patlar (bomba hasarı) ve ödülsüz kalkar."""
        t, w = n.davranis['temasla_patla'], self.w
        if not n.engaged or not self.hero_open(now, n) or self.dist(n, now) > t['yaricap']:
            return
        dmg = t['hasar']
        if 'kenarda' in t:         # Seeker Rocket: hasar patlama anındaki uzaklığa göre (temasta tam, yaricap kenarında "kenarda" kadarı)
            dmg = int(dmg * (1 - (1 - t['kenarda']) * min(1.0, self.dist(n, now) / t['yaricap'])))
        boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
        w.send(w.hurt_hero(dmg, n, atype=0) + boom + w.remove_npc(n))
        w.log('   %s patladı: %d hasar' % (n.d['ad'], dmg))

    def threshold_kamikaze(self, n, now):
        """Barracuda: canı oran'a inince kırmızı parlar ve bekle_sn yerinde durur (donuk: ateş etmez), sonra oyuncuya yaklaşır;
        yaricap içindeyse kalan canına göre alan hasarıyla patlar (ödülsüz; haritadaysa yeniden doğar), yaklas_sn içinde
        ulaşamazsa yeniden parlar (fandom: Barracuda, Kamikaze)."""
        t, w = n.davranis['kamikaze_esik'], self.w
        until = n.ab.get('kamikaze')
        if until is None:
            if n.hp <= 0 or n.hp > n.d['hp'] * t['oran']:
                return
            self.glow(n, t, now)
            return
        if now < until:
            if now >= n.ab.get('parilti', 0):          # parıltı bir anlık (istemci ShipGlowEffect3D): beklerken saniyede bir yanıp söner
                n.ab['parilti'] = now + 1.0
                w.send([self.visual(n.id, RED_GLOW, True)])
            return
        if 'yaklas' not in n.ab:
            n.ab['yaklas'] = now + t['yaklas_sn']
            n.engaged, n.next_think = True, now
            w.send([self.visual(n.id, RED_GLOW, False)])
        if self.hero_open(now, n) and self.dist(n, now) <= t['yaricap']:
            dmg = int(n.hp * t['hasar_can_orani'])
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(w.hurt_hero(dmg, n, atype=0) + boom + w.remove_npc(n))
            if not n.gate and not n.summoned:
                w.schedule(random.uniform(*w.respawn_range(n)), 'npc', n.tip)
            w.log('   %s kendini patlattı: %d hasar' % (n.d['ad'], dmg))
        elif now >= n.ab['yaklas']:
            self.glow(n, t, now)                            # ulaşamadı: yeniden parlar ve bekler

    def glow(self, n, t, now):
        n.ab['kamikaze'], n.ab['parilti'] = now + t['bekle_sn'], now + 1.0
        n.ab.pop('yaklas', None)
        self.w.npc_effect(n, 'donuk', t['bekle_sn'], source='kamikaze')
        self.w.send([self.visual(n.id, RED_GLOW, True)])
        self.w.log('   %s kamikazeye hazırlanıyor (can %%%d)' % (n.d['ad'], 100 * n.hp // max(1, n.d['hp'])))

    def singularity_visual(self, on):
        return self.visual(self.w.hid, SINGULARITY_TARGET, on)

    def dot_tick(self, now):
        w = self.w
        keep = []
        for dot in self.hero_dots:
            n = w.npcs.get(dot['npc'])
            if not n or not n.alive or now >= dot['bitis'] or dot['kalan'] <= 0 or w.hero_dead:
                continue
            keep.append(dot)
            if now < dot['sonraki']:
                continue
            dot['sonraki'] += 1.0
            if self.dist(n, now) > dot['menzil'] or not self.hero_open(now, n):
                continue
            dmg = min(dot['sn_hasar'], dot['kalan'])
            dot['kalan'] -= dmg
            w.send(w.hurt_hero(dmg, n))
        if any(d_.get('gorsel') for d_ in self.hero_dots) and not any(d_.get('gorsel') for d_ in keep):
            w.send([self.singularity_visual(False)])
        self.hero_dots = keep

    def bomb(self, n, now):
        """Emperor Kristallon'un yapışkan bombası: aralıkla, gecikmeli; tek oyunculu: hasar grup boyuna bölünür."""
        b, w = n.davranis['yapiskan_bomba'], self.w
        if not n.engaged or not self.hero_open(now, n) or self.dist(n, now) > w.npc_range(n) * 2:
            return
        if 'bomba' not in n.ab:
            n.ab['bomba'] = now + b['aralik_sn']           # ilk bomba savaş başladıktan aralik_sn sonra
            return
        if now < n.ab['bomba']:
            return
        n.ab['bomba'] = now + b['aralik_sn']
        dmg = random.randint(*b['hasar']) if isinstance(b['hasar'], list) else b['hasar']      # Marker Mimesis: 100-300 bin
        dmg = int(dmg / max(1, b.get('grup', 1)))
        from eski_protokol import legacy
        w.send([legacy('0|v|%d|%d|H|1|0|0' % (n.id, w.hid))])
        uid = n.id

        def boom():
            if not w.hero_dead and not w.jumping:
                w.send(w.hurt_hero(dmg, w.npcs.get(uid) or n, atype=0))
        w.later(b.get('gecikme_sn', 2), boom)
        w.log('   %s yapışkan bomba (%d hasar)' % (n.d['ad'], dmg))

    def hidden_regen(self, n, now):
        """Gizli Emperor Lordakium saniyede can ve kalkan doldurur."""
        if now < n.ab.get('dolum', 0):
            return
        n.ab['dolum'] = now + 1.0
        k = n.davranis['kaybolma']
        n.hp = min(n.d['hp'], n.hp + k.get('can_sn', 0))
        n.shield = min(n.d['kalkan'], n.shield + k.get('kalkan_sn', 0))

    # ------------------------------------------------------------ iyileştirme, izleme, periyodik çağırma, EMP, oyuncunun hızı
    def heal(self, n, now):
        """İyileştirme {can_sn | can_orani, bekleme_sn, menzil, hedef [ad parçaları; yoksa her uzaylı]}: bekleme_sn'de bir menzildeki
        hedef adlı uzaylıların gövdesini onarır; kendini onarmaz (Streuner Specialist: 3 sn'de 6.000; öteki Specialist onu onarır)."""
        h = n.davranis['iyilestirme']
        if now < n.ab.get('iyilestirme', 0):
            return
        n.ab['iyilestirme'] = now + h['bekleme_sn']
        w = self.w
        nx, ny = n.mover.pos(now)
        for m in list(w.npcs.values()):
            if m is n or not m.alive or m.hp <= 0 or m.hp >= m.d['hp'] or (h.get('hedef')
                                                                           and not any(s in m.d['ad'].lower() for s in h['hedef'])):
                continue
            mx, my = m.mover.pos(now)
            if math.hypot(mx - nx, my - ny) > h['menzil']:
                continue
            amount = int(min(m.d['hp'] - m.hp, h['can_sn'] if 'can_sn' in h else m.d['hp'] * h['can_orani']))
            m.hp += amount
            msgs = [legacy('0|A|HL|%d|%d|HPT|%d|%d' % (n.id, m.id, int(m.hp), amount))] if m.id in w.visible else []
            if w.target == m.id:
                msgs.append(w.selection(m))
            w.send(msgs)

    def follow(self, n, now):
        """İzleme {hedef (ad parçası), yaricap}: koruyucusu yoksa en yakın hedef adlı uzaylının çevresinde dolaşır (Aider Streuner,
        Recruit Streuner'i izler); dolaşma dunya.think'in koruyucu düzeni (NPC.guard)."""
        if now < n.ab.get('izle', 0) or self.w.ward_of(n):
            return
        n.ab['izle'] = now + 5.0
        f, nx, ny = n.davranis['izle'], *n.mover.pos(now)
        near = [(math.hypot(m.mover.pos(now)[0] - nx, m.mover.pos(now)[1] - ny), m.id) for m in self.w.npcs.values()
                if m is not n and m.alive and f['hedef'] in m.d['ad'].lower()]
        if near:
            n.guard = (min(near)[1], {'yaricap': f['yaricap']})

    def periodic_summon(self, n, now):
        """Periyodik çağırma {bekleme_sn, cagrilar [{tur, adet, en_cok}]}: savaşırken, vurulmasa da bekleme_sn'de bir çağırır; her tür
        en_cok kadar yaşarken yenisini çağırmaz (Rocketeer -> Seeker Rocket; Strokelight Barrage -> Abide I ve Steadfast III)."""
        p, w = n.davranis['periyodik_cagir'], self.w
        if not n.engaged or n.etki.frozen(now) or now < n.ab.get('periyodik', 0) or not self.hero_open(now, n):
            return
        n.ab['periyodik'] = now + p['bekleme_sn']
        n.children = {c for c in n.children if c in w.npcs and w.npcs[c].alive}
        for e in p['cagrilar']:
            room = e['en_cok'] - sum(1 for c in n.children if w.npcs[c].tip == e['tur'])
            if room > 0:
                self.summon(n, e['tur'], min(e['adet'], room), now)

    def drop_mines(self, n, now):
        """Mayın bırakma {mayin, can_orani, bekleme_sn, en_cok, hedef, yaricap}: canı can_orani'nın altındayken savaşırken bekleme_sn'de bir
        mayın bırakır (uzaylının konumuna; hedef: oyuncunun çevresine, yaricap [en az, en çok] uzaklıkta); aynı uzaylının en_cok mayını
        yaşarken yenisini bırakmaz. Mayın savas_esya.alien_mine'ın uzaylı mayınıdır (kurulunca oyuncu yakındaysa patlar)."""
        m, w = n.davranis['mayin_birak'], self.w
        if (w.items is None or not n.engaged or n.etki.frozen(now) or n.hp > n.d['hp'] * m['can_orani']
                or now < n.ab.get('mayin', 0) or not self.hero_open(now, n)):
            return
        n.ab['mayin'] = now + m['bekleme_sn']
        if sum(1 for k in w.items.mines.values() if k['sahip'] == n.id) >= m['en_cok']:
            return
        x, y = w.hero_pos(now) if m.get('hedef') else n.mover.pos(now)
        if m.get('hedef'):
            a, r = random.uniform(0, 2 * math.pi), random.uniform(*m['yaricap'])
            x, y = x + math.cos(a) * r, y + math.sin(a) * r
        w.items.alien_mine(m['mayin'], min(max(0, x), w.map_w), min(max(0, y), w.map_h), n.id, now)
        w.log('   %s mayın bıraktı (%s)' % (n.d['ad'], m['mayin']))

    def death_ray(self, n, now):
        """Ölüm ışını {hasar, aralik_sn, uzaklik} (Gygerim Overlord): oyuncu uzaklik'tan uzaktayken (ışınlar haritanın dışından gelir) savaşırken
        aralik_sn'de bir ortalama hasar (%80-120); menzile bağlı değil, yakındaki oyuncuya ışın düşmez."""
        r, w = n.davranis['olum_isini'], self.w
        if (not n.engaged or n.etki.frozen(now) or now < n.ab.get('isin', 0) or self.dist(n, now) <= r['uzaklik']
                or not self.hero_open(now, n)):
            return
        n.ab['isin'] = now + r['aralik_sn']
        dmg = int(r['hasar'] * random.uniform(0.8, 1.2))
        w.send(w.hurt_hero(dmg, n, atype=0))
        w.log('   %s ölüm ışını (%d hasar)' % (n.d['ad'], dmg))

    def periodic_emp(self, n, now):
        """Periyodik EMP {bekleme_sn, menzil}: savaşırken, menzildeyse bekleme_sn'de bir (Hitac Underboss'un EMP Impulse'u)."""
        e = n.davranis['periyodik_emp']
        if not n.engaged or n.etki.frozen(now) or now < n.ab.get('emp_sonraki', 0) or self.dist(n, now) > e['menzil'] \
                or not self.hero_open(now, n):
            return
        n.ab['emp_sonraki'] = now + e['bekleme_sn']
        self.emp(n, now)

    def emp(self, n, now):
        """Uzaylının EMP darbesi (Obscured Mimesis, Hitac Underboss, Spookfish): oyuncunun hedefi sıfırlanır, gizlenme biter (EMP-01'in
        oyuncuya etkisi gibi: hedefleme cihazları kapanır, gizlenme bozulur) ve mini harita parazitlenir."""
        w = self.w
        if w.hero_dead or w.jumping:
            return
        if w.attacking:
            w.laser_stop()
        w.abilities.reveal()
        w.items.reveal()
        msgs = [legacy('0|n|EMP|%d' % w.hid), legacy('0|n|EMAL|%d' % EMP_NOISE_SN)]
        if w.target is not None:
            w.target = None
            msgs.append(('ShipDeselectionCommand', {}))
        w.send(msgs)
        w.log('   %s EMP darbesi savurdu' % n.d['ad'])

    def match_speed(self, n, now):
        """Oyuncunun hızı {ek, can_orani}: hızı oyuncununkine eşitlenir (+ek). can_orani varsa yalnız canı o orana inince (Hooligan:
        kritik canda); Seeker Rocket hep (oyuncu + 20)."""
        h = n.davranis['hiz_oyuncu']
        if 'can_orani' in h and n.hp > n.d['hp'] * h['can_orani']:
            n.ab.pop('hiz', None)
        else:
            n.ab['hiz'] = max(1, int(self.w.p.d['gemi'].get('speed', 300)) + h.get('ek', 0))

    # ------------------------------------------------------------ düşük can: kaçış ve park (fandom Low health, Parking)
    def flees(self, n):
        """Bu uzaylı düşük canda kaçar mı: yalnız haritanın kendi nüfusundaki başıboşlar. Kapı, mod, etkinlik ve çağrılanlar, hareketsizler,
        mothership ve özel patronlar (yeniden_dogma_ozel), korsan haritaları (5-X), duvarlı haritalar, Barracuda (kamikaze) ve hızı
        oyuncununkine eşitlenen Hooligan kaçmaz (fandom: mothership ve korsanlar kaçmaz)."""
        w = self.w
        if (n.gate or n.summoned or n.hunt or getattr(n, 'pasif', False) or n.d['hiz'] <= 0 or w.kapi or w.low or w.labirent
                or n.tip in self.S.get('yeniden_dogma_ozel', {}) or 'kamikaze_esik' in n.davranis or 'hiz_oyuncu' in n.davranis
                or H.map_class(w.map_id).startswith('5-') or HD.navigates(w.map_id)):
            return False
        return any(e['tip'] == n.tip for e in w.rules.get('npc', []))

    def flee_range(self, n):
        """Kaçarken ateş menzili: bazı uzaylılarda (Kristallon, Kristallin) düşük canda artar (fandom Low health)."""
        m, r = LOW['menzil_artisi'], self.w.npc_range(n)
        return r * m['carpan'] if any(s in n.d['ad'].lower() for s in m['ad']) else r

    def flee_spot(self, n, now):
        """Oyuncudan en uzak kenar/köşe noktası (güvenli bölgeye ve onun yoluna girmeden); yoksa bulunduğu yer."""
        w, m = self.w, LOW['kenar_payi']
        hx, hy = w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        spots = [(x, y) for x in (m, w.map_w // 2, w.map_w - m) for y in (m, w.map_h // 2, w.map_h - m) if (x, y) != (w.map_w // 2, w.map_h // 2)]
        spots = [s for s in spots if not w.near_zone(s[0], s[1], 600) and not w.path_near_zone(nx, ny, s[0], s[1])]
        return max(spots, key=lambda s: math.hypot(s[0] - hx, s[1] - hy)) if spots else (int(nx), int(ny))

    def flee_move(self, n, st, now):
        tx, ty = st['hedef']
        ms = n.mover.go(tx, ty, n.speed() * n.etki.speed_factor(now), now)
        self.w.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])

    def low_health(self, n, now):
        """Düşük can (canı dusuk_can.oran'ın altına inen harita uzaylısı): oyuncunun tersindeki kenar noktasına kaçar ('kac'; menzildeyse
        hâlâ ateş eder), varınca durur ve kalkanını/canını yeniler ('park'; ateş etmez, vurulunca karşılık vermez, vurulmadıkça
        yenilenir); donus_orani'na yenilenince normal yapay zekâ. -> 'kac' | 'park' | None (dunya.think)."""
        st = n.ab.get('kac')
        if n.etki.frozen(now):
            return st['durum'] if st else None
        if st is None:
            if not (0 < n.hp < n.d['hp'] * LOW['oran']) or not self.flees(n):
                return None
            st = n.ab['kac'] = dict(durum='kac', hedef=self.flee_spot(n, now), dolum=0.0)
            self.flee_move(n, st, now)
            self.w.log('   %s düşük canda kaçıyor (can %%%d)' % (n.d['ad'], 100 * n.hp // max(1, n.d['hp'])))
        if n.hp >= n.d['hp'] * LOW['donus_orani'] and n.shield >= n.d['kalkan'] * LOW['donus_orani']:
            del n.ab['kac']                                       # tamamen yenilendi: normal yapay zekâ
            n.next_think = now
            return None
        if st['durum'] == 'kac':
            if n.mover.t1 > now:
                return 'kac'
            x, y = n.mover.pos(now)
            if math.hypot(x - st['hedef'][0], y - st['hedef'][1]) > 150:
                self.flee_move(n, st, now)                         # yolu kesildi (yavaşlatma, donma): yeniden
                return 'kac'
            st['durum'] = 'park'
            self.w.log('   %s köşeye park etti: (%d,%d)' % (n.d['ad'], x, y))
        n.engaged = False                                          # park: karşılık vermez
        if now >= st['dolum']:
            st['dolum'] = now + 1.0
            r = LOW['yenilenme']
            if now - n.last_hit >= r['bekleme_sn']:
                n.hp = min(n.d['hp'], n.hp + int(n.d['hp'] * r['can_orani_sn']))
                n.shield = min(n.d['kalkan'], n.shield + int(n.d['kalkan'] * r['kalkan_orani_sn']))
                if self.w.target == n.id:
                    self.w.send([self.w.selection(n)])
        return 'park'

    # ------------------------------------------------------------ Emperor Sibelon: hız ve kapsüller
    def speed_skill(self, n, now):
        h = n.davranis['hiz_becerisi']
        if 'hiz' not in n.ab and n.shield <= n.d['kalkan'] * h.get('kalkan_orani', 0.1):
            n.ab['hiz'] = h['hiz']
            n.ab['kapsul'] = now
            self.w.log('   %s hızlandı (%d)' % (n.d['ad'], h['hiz']))
        k = n.davranis.get('kapsuller')
        if 'hiz' not in n.ab or not k:
            return
        mine = [a for a, c in self.capsules.items() if c['sahip'] == n.id]
        if len(mine) < k['adet'] and now >= n.ab['kapsul']:
            n.ab['kapsul'] = now + k['aralik_sn']
            self.spawn_capsule(n)
            mine = [a for a, c in self.capsules.items() if c['sahip'] == n.id]
        if not mine or n.etki.frozen(now):
            return
        nx, ny = n.mover.pos(now)
        aid = min(mine, key=lambda a: math.hypot(self.capsules[a]['x'] - nx, self.capsules[a]['y'] - ny))
        c = self.capsules[aid]
        d = math.hypot(c['x'] - nx, c['y'] - ny)
        if d <= k.get('toplama_mesafe', 150):
            if 'toplama' not in c:
                c['toplama'] = now + k['toplama_ms'] / 1000.0
                self.w.send([('StartCapsuleCollectCommand', {'collectorId': n.id, 'assetId': aid, 'timer': k['toplama_ms']})])
            elif now >= c['toplama']:
                self.collect_capsule(n, aid, k)
            return
        if n.ab.get('kapsula') != aid or n.mover.t1 <= now:
            n.ab['kapsula'] = aid
            ms = n.mover.go(c['x'], c['y'], n.ab['hiz'] * n.etki.speed_factor(now), now)
            n.next_think = now + ms / 1000.0 + 0.5          # kovalamayı bırakıp kapsüle gider
            self.w.send([('MoveCommand', dict(userId=n.id, x=int(c['x']), y=int(c['y']), timeToTarget=ms))])

    def spawn_capsule(self, n):
        w = self.w
        self.next_capsule += 1
        aid = self.next_capsule
        x, y = self.far_spot(n.mover.pos(time.time()), 2500)
        kind = random.choice(CAPSULES)
        self.capsules[aid] = dict(x=x, y=y, tur=kind, sahip=n.id)
        w.send([asset_create(aid, BUFF_CAPSULE, x, y, name='%s-Buff' % {'can': 'HP', 'kalkan': 'SHD', 'hasar': 'DMG'}[kind],
                             design=CAPSULES.index(kind))])
        w.log('   kapsül belirdi: %s (%d,%d)' % (kind, x, y))

    def drop_capsule(self, aid, why):
        c = self.capsules.pop(aid, None)
        if not c:
            return
        msgs = [asset_remove(aid, BUFF_CAPSULE)]
        if 'toplama' in c:
            msgs.insert(0, ('StopCapsuleCollectCommand', {'collectorId': c['sahip']}))
        self.w.send(msgs)
        self.w.log('   kapsül %s: %s' % (why, c['tur']))

    def collect_capsule(self, n, aid, k):
        """Emperor kapsülü topladı: can/kalkan %10 dolar ya da hasarı artar ve oyuncununki düşer (Emperor ölünce kalkar)."""
        w = self.w
        kind = self.capsules[aid]['tur']
        if kind == 'can':
            n.hp = min(n.d['hp'], n.hp + n.d['hp'] * k['can'])
        elif kind == 'kalkan':
            n.shield = min(n.d['kalkan'], n.shield + n.d['kalkan'] * k['kalkan'])
        else:
            n.ab['hasar_bonus'] = n.ab.get('hasar_bonus', 0) + k['hasar']
            w.hero_effect('zayiflik', 3600, k['hasar'], source='kapsul_%d' % n.id)
        self.drop_capsule(aid, 'toplandı')
        # toplama görseli (Ö1): Emperor'un çevresinde 4 sn'lik parlayan halka; tür 0 hasar (kırmızı), 1 kalkan, 2 can (istemci:
        # EmperorSibelonBuffRingCommandHandler, çap radius x 2; yarıçap uyarlama)
        x, y = n.mover.pos(time.time())
        w.send([('EmperorSibelonBuffRingCommand', dict(avatarId=n.id, type={'hasar': 0, 'kalkan': 1, 'can': 2}[kind], radius=RING_RADIUS,
                                                       x=int(x), y=int(y)))])
        if w.target == n.id:
            w.send([w.selection(n)])

    def capsule_tick(self, now):
        """Oyuncu kapsülün yakınından geçerse kapsül yok olur; sahibi ölen kapsüller kalkar."""
        if not self.capsules:
            return
        w = self.w
        hx, hy = w.hero_pos(now)
        for aid, c in list(self.capsules.items()):
            owner = w.npcs.get(c['sahip'])
            if not owner or not owner.alive:
                self.drop_capsule(aid, 'sahipsiz kaldı')
            elif not w.hero_dead and math.hypot(c['x'] - hx, c['y'] - hy) <= owner.davranis['kapsuller'].get('toplama_mesafe', 150):
                self.drop_capsule(aid, 'oyuncu yok etti')

    def capsule_msgs(self):
        """Harita yeniden yüklenince kapsüller yeniden bildirilir."""
        return [asset_create(aid, BUFF_CAPSULE, c['x'], c['y'], design=CAPSULES.index(c['tur'])) for aid, c in self.capsules.items()]

    # ------------------------------------------------------------ ölüm
    def on_kill(self, n, x, y):
        """Uzaylı öldü: patlayan (sahte Emperor) yakındaki oyuncuyu vurur; çağırdıkları dağılır (Cubikon); DMG kapsülünün oyuncudaki
        etkisi kalkar."""
        w = self.w
        p = n.davranis.get('olunce_patla')
        msgs = []
        if p and not w.hero_dead:
            hx, hy = w.hero_pos()
            if math.hypot(x - hx, y - hy) <= p['yaricap']:
                msgs += w.hurt_hero(p['hasar'], n, atype=0)
                w.log('   %s patladı: %d hasar' % (n.d['ad'], p['hasar']))
        g = n.davranis.get('olunce_cagrilar_dagilir')
        if g:
            end = time.time()
            for cid in n.children:
                c = w.npcs.get(cid)
                if c and c.alive:
                    c.pasif, c.engaged = True, False                    # kimseyi kovalamadan dolaşır (dunya.think)
                    c.ab['omur'] = end + random.uniform(*g['omur_sn'])
        if w.hero_etki.get('zayiflik'):
            w.hero_etki.remove('zayiflik', source='kapsul_%d' % n.id)
        left = [d for d in self.hero_dots if d['npc'] != n.id]
        if any(d.get('gorsel') for d in self.hero_dots) and not any(d.get('gorsel') for d in left):
            msgs.append(self.singularity_visual(False))                 # tekilliğin sahibi öldü: girdap kalkar
        self.hero_dots = left
        return msgs
