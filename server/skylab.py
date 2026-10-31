"""Skylab (yol haritası Aşama 5): toplayıcılar, rafineriler, Xeno modülü, enerji, yükseltmeler, robotlar ve gemiye taşıma.

Veri: data/skylab.json (tools/skylab.py <- wiki tabloları + kayıttaki başlangıç durumu). İstekler istemcinin kodundan
(UISkylabSystem: SendActionRequest(construction, subaction, transportMode, sayılar), SendBuyRobot(robotType 1|2)):
  SkylabActionRequest {subaction}      '' pencere/yenile; 'upgrade' süreli yükseltme (kredi + depodan Prometium/Endurium/Terbium);
                                       'instantUpgrade' yalnız uridyumla anında; 'instantFinishUpgrade' süren yükseltmeyi kalan
                                       süre oranında uridyumla bitirir; 'abortUpgrade' iptal (istemcinin uyarısı: harcananlar geri
                                       gelmez); 'setActive' / 'setInactive'; 'startTransport' {transportMode '' normal, 'fast' anında
                                       gönderme, 'instantFinish' yoldakini bitir; count<Cevher>}
     -> SkylabMainViewCommand {listModule, oreList} + SkylabUnifiedReceiptCommand {construction, subaction, transportPrice,
        robotsLeftTimeList, errorId / sucessId: BaseStackCommand (BaseKey 22, 30-53)}
  SkylabViewModuleRequest {moduleName} -> SkylabViewModuleBackCommand (üretim, yükseltme bedeli, robotlar, Xeno, depo bilgisi)
  SkylabPurchaseRobotRequest {construction, robotType}: 1 = 250 kredi (+%1), 2 = 50 uridyum (+%4); toplayıcı başına 12 etkin,
                                       fazlası depoda bekler ve süresi (48 saat) dolanın yerine geçer
Kurallar (wiki ve istemci metinleri): toplayıcı/rafineri/güneş/depo seviyesi ana modülü geçemez; aynı anda bir yükseltme; etkin
modüllerin enerjisi güneş modülünün verdiğini geçemez; yükseltmedeki modül çalışmaz ve enerji harcamaz. Üretim saat başına,
verimle (robot bonusu) ve depo sınırıyla; rafineriler girdileri depodan harcar (Prometid / Duranium -> Promerium -> Seprom).
Süreler oyun kapalıyken de işler (girişte ve saniyede bir kaldığı yerden hesaplanır).
Uyarlamalar: süreli yükseltmede harcanan kaynaklar Skylab deposundan; Xeno modülü Xenomit sağlar (data/skylab.json _xeno);
anında gönderme / bitirme kayıttaki transportPrice (1.250 U). Normal taşıma cevher başına 7,2 sn, Premium 3,6 sn (wikiwiki).
Profilde: skylab {moduller: {tür: {seviye, etkin, yukseltme: bitiş | yok}}, depo: {cevher kimliği: miktar}, robotlar: {tür: [[tip,
bitiş]]}, yedek: {tür: [tip]}, tasima: {bitis, yuk} | yok, son}.
"""
import json, math, os, time

import envanter as INV
import ayar as AY

HERE = os.path.dirname(os.path.abspath(__file__))
S = json.load(open(os.path.join(HERE, 'data', 'skylab.json'), encoding='utf8'))
LEVELS, COSTS, MODULES, ORES = S['seviyeler'], S['maliyetler'], S['moduller'], S['cevherler']
COLLECTORS, REFINERIES, XENO = S['toplayicilar'], S['rafineriler'], S['xeno']
ROBOTS, TRANSPORT = S['robotlar'], S['tasima']
ORDER = ['DURANIUM_REFINERY', 'BASE_MODULE', 'ENDURIUM_COLLECTOR', 'SOLAR_MODULE', 'XENO_MODULE', 'PROMETID_REFINERY',
         'STORAGE_MODULE', 'TRANSPORT_MODULE', 'SEPROM_REFINERY', 'PROMETIUM_COLLECTOR', 'TERBIUM_COLLECTOR', 'PROMERIUM_REFINERY']
ORE_ORDER = ['1', '2', '3', '11', '12', '4', '13', '14']           # kayıttaki depo listesi sırası
COUNT_FIELDS = {'count' + v[0]: k for k, v in ORES.items()}         # SkylabActionRequest.countPrometium … -> cevher kimliği
ALWAYS_ON = ('BASE_MODULE', 'SOLAR_MODULE', 'STORAGE_MODULE')     # istemci bunlarda aç/kapa düğmesi göstermez
UPGRADE_RES = (('1', 33), ('2', 34), ('3', 35))                     # Prometium, Endurium, Terbium yetmezse BaseKey
REFINE_ORDER = ['PROMETID_REFINERY', 'DURANIUM_REFINERY', 'PROMERIUM_REFINERY', 'SEPROM_REFINERY']
CARGO = {k: v[2] for k, v in ORES.items()}                          # Skylab cevheri -> geminin OreType'ı
STEP_SN = 600                                                       # çevrimdışı birikimin hesap adımı


def mod(name, **f):
    f['_'] = name
    return f


def row(level):
    return LEVELS[max(1, min(level, len(LEVELS))) - 1]


def stack(code):
    return mod('BaseStackCommand', type=0, enumBaseKey=code, stringBasekey='', argsList=[])


class Skylab:
    def __init__(self, profil, log=print):
        self.p, self.log = profil, log
        self.m = None                 # mağaza (para ve kargo güncellemeleri; oturum bağlar)
        self.send = None              # zamanla biten işler (yükseltme, taşıma) için bildirim (oturum bağlar)
        self.quest = None             # görev olayı (UPDATE_SKYLAB_TO_LEVEL; oturum bağlar) -> mesajlar
        self.bekleyen_gorev = []      # (modül, seviye): görev olayı profil kilidi bırakılınca (gorev_takip de o kilidi alır)
        self.next_tick = 0.0

    # ------------------------------------------------------------ durum
    @property
    def st(self):
        d = self.p.d.get('skylab')
        if not d:
            d = self.p.d['skylab'] = {
                'moduller': {k: {'seviye': v[0], 'etkin': v[1], 'yukseltme': None} for k, v in S['baslangic']['moduller'].items()},
                'depo': {k: float(v) for k, v in S['baslangic']['depo'].items()},
                'robotlar': {}, 'yedek': {}, 'tasima': None, 'son': time.time()}
            self.p.dirty = True
        return d

    def module(self, key):
        return self.st['moduller'].setdefault(key, {'seviye': 0, 'etkin': False, 'yukseltme': None})

    def level(self, key):
        return self.module(key)['seviye']

    def levels(self):
        """Modül -> seviye (görev kabulünde şimdiki durum; Ö1)."""
        return {k: m['seviye'] for k, m in self.st['moduller'].items()}

    def state(self, key):
        m = self.module(key)
        if m.get('yukseltme'):
            return 'UPGRADE'
        return 'ACTIVE' if m['etkin'] and m['seviye'] > 0 else 'INACTIVE'

    def working(self, key):
        return self.state(key) == 'ACTIVE'

    def energy(self, key, level=None):
        lv = self.level(key) if level is None else level
        return row(lv)['enerji'] if lv > 0 and key != 'SOLAR_MODULE' else 0

    def consumption(self):
        return sum(self.energy(k) for k in MODULES if k != 'SOLAR_MODULE' and self.working(k))

    def solar(self):
        return row(self.level('SOLAR_MODULE'))['gunes']

    def capacity(self, ore):
        v = row(self.level('STORAGE_MODULE'))['depo'][ORES[ore][1]]
        return v if AY.carpan('skylab_depo') == 1.0 else min(AY.I32, int(v * AY.carpan('skylab_depo')))    # panel: depo

    def amount(self, ore):
        return int(self.st['depo'].get(ore, 0))

    def bonus(self, key):
        return sum(ROBOTS[str(t)]['bonus'] for t, _ in self.st['robotlar'].get(key, []))

    def efficiency(self, key):
        return 100 + self.bonus(key)

    def production(self, key):
        """Saatlik üretim (verimle)."""
        lv = self.level(key)
        if lv <= 0:
            return 0
        k = AY.carpan('skylab_uretim')                     # panel: Skylab üretimi
        if key in COLLECTORS:
            return int(row(lv)['uretim']['ham'] * self.efficiency(key) / 100 * k)
        if key in REFINERIES:
            return int(row(lv)['uretim'][REFINERIES[key][2]] * k)
        if key == 'XENO_MODULE':
            return int(row(lv)['uretim'][XENO['sutun']] * k)
        return 0

    # ------------------------------------------------------------ zaman
    def events(self, after):
        ev = [m['yukseltme'] for m in self.st['moduller'].values() if m.get('yukseltme')]
        ev += [b for rs in self.st['robotlar'].values() for _, b in rs]
        if self.st.get('tasima'):
            ev.append(self.st['tasima']['bitis'])
        return [e for e in ev if e > after]

    def advance(self, now=None):
        """Son hesaptan bu yana üretim; araya giren olaylar (yükseltme bitişi, robot süresi, taşıma) sırayla -> bildirimler."""
        now = now or time.time()
        st, out = self.st, []
        t = min(st.get('son', now), now)
        with self.p.lock:
            while True:
                ev = self.events(t)
                nxt = min([now, t + STEP_SN] + [e for e in ev if e <= now])     # uzun aralık adım adım (üretim/tüketim sırası)
                if nxt > t:
                    self.produce((nxt - t) / 3600.0)
                t = nxt
                out += self.fire(t)
                if t >= now:
                    break
            st['son'] = now
            self.p.dirty = True
        self.gorev_bildir()
        return out

    def gorev_bildir(self):
        """Biten yükseltmelerin görev olayı: kilit dışında (kilit altında çağrılınca threading.Lock kendini bekliyordu)."""
        while self.bekleyen_gorev:
            key, lv = self.bekleyen_gorev.pop(0)
            if self.quest and self.send:                     # görev: "Prometium collector'ı 1. seviyeye yükselt" (Ö1)
                msgs = self.quest(modul=key, seviye=lv)
                if msgs:
                    self.send(msgs)

    def produce(self, hours):
        dep = self.st['depo']

        def add(ore, n):
            dep[ore] = min(self.capacity(ore), dep.get(ore, 0) + n) if n > 0 else dep.get(ore, 0)
        for key, ore in COLLECTORS.items():
            if self.working(key):
                add(ore, self.production(key) * hours)
        if self.working('XENO_MODULE'):
            add(XENO['cevher'], self.production('XENO_MODULE') * hours)
        for key in REFINE_ORDER:
            if not self.working(key):
                continue
            out, inputs, _ = REFINERIES[key]
            n = self.production(key) * hours
            n = min([n, self.capacity(out) - dep.get(out, 0)] + [dep.get(o, 0) / k for o, k in inputs.items()])
            if n <= 0:
                continue
            for o, k in inputs.items():
                dep[o] = max(0.0, dep.get(o, 0) - n * k)
            add(out, n)

    def fire(self, t):
        """t anında dolan olaylar -> istemci bildirimleri."""
        st, out = self.st, []
        for key, m in st['moduller'].items():
            if m.get('yukseltme') and m['yukseltme'] <= t:
                out += self.finish_upgrade(key, code=46)
        for key, rs in list(st['robotlar'].items()):
            alive = [r for r in rs if r[1] > t]
            for _ in range(len(rs) - len(alive)):
                spare = st['yedek'].get(key) or []
                if spare:
                    alive.append([spare.pop(0), t + ROBOTS['omur_sn']])
            st['robotlar'][key] = alive
        tr = st.get('tasima')
        if tr and tr['bitis'] <= t:
            out += self.deliver(tr['yuk'])
            st['tasima'] = None
        return out

    def finish_upgrade(self, key, code):
        m = self.module(key)
        m['seviye'] += 1
        m['yukseltme'] = None
        self.bekleyen_gorev.append((key, m['seviye']))      # gorev_bildir: kilit bırakılınca
        others = self.consumption() - (self.energy(key) if self.working(key) else 0)
        if key not in ALWAYS_ON and others + self.energy(key) > self.solar():
            m['etkin'] = False                              # enerji yetmiyor: kapalı kalır
        self.p.dirty = True
        self.log('   Skylab: %s seviye %d' % (key, m['seviye']))
        return [('_receipt', key, '', [], [code])]

    def deliver(self, load):
        """Taşıma vardı: kargoya sığan kısmı gemiye ('_ores', render kilit dışında ekler), kalanı Skylab deposuna geri.
        Profil kilidi tutulurken çağrılabilir (yalnız sözlük değişir)."""
        free, got, back = self.p.cargo_free(), {}, {}
        for ore, n in sorted(load.items(), key=lambda kv: ORE_ORDER.index(kv[0])):
            take = min(int(n), free)
            if take > 0:
                got[CARGO[ore]] = got.get(CARGO[ore], 0) + take
                free -= take
            if n - take > 0:
                back[ore] = n - take
        for ore, n in back.items():
            self.st['depo'][ore] = min(self.capacity(ore), self.st['depo'].get(ore, 0) + n)
        self.log('   Skylab: taşıma geldi %s%s' % (got, ' (sığmayan depoya döndü %s)' % back if back else ''))
        return ([('_ores', got)] if got else []) + [('_receipt', 'TRANSPORT_MODULE', 'startTransport', [], [53])]

    # ------------------------------------------------------------ mesajlar
    def main_view(self):
        mods = []
        for key in ORDER:
            m = self.module(key)
            power = self.consumption() if key == 'SOLAR_MODULE' else (self.energy(key) if self.working(key) else 0)
            mods.append(mod('SkylabMainViewModuleCommand', maxLevel=MODULES[key]['azami'], state=self.state(key), moduleType=key,
                            efficiency=self.bonus(key) if key in COLLECTORS else 0, currentPower=power,
                            maxPower=self.solar() if key == 'SOLAR_MODULE' else -1, level=m['seviye']))
        ores = [mod('SkylabStorageOreCommand', current=self.amount(o), oreId=int(o), capacity=self.capacity(o), oreName=ORES[o][0])
                for o in ORE_ORDER]
        return ('SkylabMainViewCommand', {'listModule': mods, 'oreList': ores})

    def robots_left(self, key, now=None):
        now = now or time.time()
        return [mod('SkylabActiveRobotsLeftTimeCommand', uridium=1 if t == 2 else 0, leftTime=max(0, int(b - now)))
                for t, b in self.st['robotlar'].get(key, [])]

    def robot_price(self, kind):
        """Robotun para birimi ve alınan fiyatı (panelin hizmet ücreti çarpanıyla; pencerede de bu görünür)."""
        cur, price = ROBOTS[kind]['fiyat']
        return cur, AY.fiyat('hizmet_fiyat', price, 'skylab')

    def productivity(self, key, now=None):
        """Toplayıcının Productivity sekmesi (robotlar, verim, fiyatlar)."""
        price = lambda kind: mod('SkylabRobotPriceCommand', priceType=ROBOTS[kind]['fiyat'][0], value=self.robot_price(kind)[1])
        return mod('SkylabModuleProductivityCommand', type1Price=price('1'), efficienty=self.efficiency(key),
                   active=len(self.st['robotlar'].get(key, [])), robotsLeftTimeList=self.robots_left(key, now), type2Price=price('2'),
                   bonus=self.bonus(key), maxActive=ROBOTS['azami'], inStorage=len(self.st['yedek'].get(key, [])))

    def receipt(self, construction='', subaction='', errors=(), success=()):
        """İstemci (UISkylabSystem.ShowTips) yalnız errorId'yi açılır pencerede gösterir; sucessId gelince pencere boş açılıyordu.
        Başarı metinleri de errorId'de; %module% / %level% / %date% yer tutucuları ArgStackCommand ile (canlı test H37).
        İstemci (SetSkylabActionHandler.Run) construction boş değilse pencereyi açar: metin yoksa construction boş gider (robot
        alımında, kapanmayan modülü aç/kapada metinsiz "Ok" penceresi çıkıyordu; kullanıcı 2026-10-24). Kod yerine hazır metin de
        verilebilir (BaseStackCommand)."""
        texts = [c if isinstance(c, dict) else self.stack_args(c, construction) for c in list(errors) + list(success)]
        return ('SkylabUnifiedReceiptCommand', dict(
            construction=construction if texts else '', resultId=0, transportPrice=TRANSPORT['hizli_uridyum'],
            robotsLeftTimeList=self.robots_left(construction) if construction in COLLECTORS else [], subaction=subaction,
            errorId=texts, sucessId=[]))

    def stack_args(self, code, key):
        import magaza as MG
        st = stack(code)
        if key in MODULES:
            lv = self.level(key)
            args = dict(_module_=MG.res('skylab_' + key.lower()), _level_=lv + (1 if code in (40, 43) else 0),
                        _date_=time.strftime('%d.%m.%Y'))      # ':' olmamalı: istemci ':' içereni 'res' biçimi sanıp atlar
            st['argsList'] = [mod('ArgStackCommand', type=0, value2=None, key=MG.ARG_KEYS[k], value=str(v)) for k, v in args.items()]
        return st

    def window(self, construction='', subaction='', errors=(), success=()):
        return [self.main_view(), self.receipt(construction, subaction, errors, success)]

    def upgrade_cost(self, key):
        g, lv = MODULES[key]['grup'], self.level(key)
        if not g or lv >= MODULES[key]['azami']:
            return None
        c = COSTS[g][lv]
        f = lambda n: AY.fiyat('hizmet_fiyat', n, 'skylab')  # panel: hizmet ücretleri (kredi ve uridyum; kaynaklar aynı)
        return dict(c, kredi=f(c['kredi']), uridyum=f(c['uridyum']))

    def ore_info(self, ore, n, cap=None):
        return mod('SkylabStorageOreCommand', current=int(n), oreId=int(ore), capacity=int(self.capacity(ore) if cap is None else cap),
                   oreName=ORES[ore][0])

    def view(self, key, now=None):
        now = now or time.time()
        if key not in MODULES:
            return None
        m, c = self.module(key), self.upgrade_cost(key)
        left = max(0, int(m['yukseltme'] - now)) if m.get('yukseltme') else 0
        upgrade = mod('SkylabModuleUpgradeCommand', timeLeft=left, credits=c['kredi'] if c else 0, terbium=c['kaynak'] if c else 0,
                      uridiumInstant=self.finish_price(key, now) if left else (c['uridyum'] if c else 0),
                      endurium=c['kaynak'] if c else 0, prometium=c['kaynak'] if c else 0, timeNormal=AY.sure(c['sure_sn'], 'skylab') // 60 if c else 0)
        info = mod('SkylabCollectorInfoCommand', production=self.production(key), maxTime=0, leftTime=0)
        prod, xeno, ores = None, mod('SkylabXenoInfoCommand', activeEfficiency=0, activeConsumption=0, inactiveConsumption=0,
                                     activeEnergy=0), []
        if key in COLLECTORS:
            prod = self.productivity(key, now)
            ores = [self.ore_info(COLLECTORS[key], self.production(key))]
        elif key in REFINERIES:
            out, inputs, _ = REFINERIES[key]
            n = self.production(key)
            ores = [self.ore_info(o, -n * k) for o, k in inputs.items()] + [self.ore_info(out, n)]
        elif key == 'XENO_MODULE':
            use = self.production('PROMERIUM_REFINERY') * REFINERIES['PROMERIUM_REFINERY'][1].get(XENO['cevher'], 0) \
                if self.working('PROMERIUM_REFINERY') else 0
            xeno = mod('SkylabXenoInfoCommand', activeEfficiency=self.production(key), activeConsumption=use, inactiveConsumption=0,
                       activeEnergy=self.energy(key))
            ores = [self.ore_info(XENO['cevher'], self.production(key))]
        elif key == 'STORAGE_MODULE':
            nxt = row(self.level(key) + 1)['depo'] if self.level(key) < MODULES[key]['azami'] else None
            ores = [self.ore_info(o, (nxt[ORES[o][1]] - self.capacity(o)) if nxt else 0, nxt[ORES[o][1]] if nxt else None)
                    for o in ORE_ORDER]
        elif key == 'TRANSPORT_MODULE':
            tr = self.st.get('tasima')
            if tr:
                info = mod('SkylabCollectorInfoCommand', production=int(sum(tr['yuk'].values())), maxTime=self.transport_time(tr['yuk']),
                           leftTime=max(0, int(tr['bitis'] - now)))
                ores = [self.ore_info(o, n) for o, n in sorted(tr['yuk'].items(), key=lambda kv: ORE_ORDER.index(kv[0]))]
        return ('SkylabViewModuleBackCommand', dict(collectorInfo=info, upgrade=upgrade, productivity=prod, xenoInfo=xeno,
                                                    strorageInfo=mod('SkylabStorageInfoCommand', efficiency=self.efficiency(key)
                                                                     if key in COLLECTORS else 0, infoOreList=ores),
                                                    moduleName=key))

    # ------------------------------------------------------------ yükseltme
    def finish_price(self, key, now=None):
        """Süren yükseltmeyi bitirme: anında yükseltme fiyatının kalan süre oranı (en az 1)."""
        m, now = self.module(key), now or time.time()
        if not m.get('yukseltme'):
            return 0
        c = COSTS[MODULES[key]['grup']][m['seviye']]
        u = AY.fiyat('hizmet_fiyat', c['uridyum'], 'skylab')
        return max(1 if u else 0, int(math.ceil(u * (m['yukseltme'] - now) / max(1, AY.sure(c['sure_sn'], 'skylab')))))

    def check_upgrade(self, key):
        """Yükseltilebilir mi -> hata kodu ya da None."""
        if key not in MODULES or not MODULES[key]['grup'] or self.level(key) >= MODULES[key]['azami']:
            return 30
        if self.module(key).get('yukseltme'):        # aynı anda birden çok modül yükseltilebilir (oyuncu bildirimi 2026-10-30); aynı modül bir kez
            return 42
        if key != 'BASE_MODULE' and self.level(key) + 1 > self.level('BASE_MODULE'):
            return 31
        if key == 'PROMERIUM_REFINERY' and self.level(key) + 1 > self.level('XENO_MODULE'):     # resmî forum: Xeno-Modül sınırı
            return self.raw('skylab_message_upgrade_xenomoduleLevel')
        if key != 'SOLAR_MODULE' and self.module(key)['etkin'] and \
                self.consumption() - (self.energy(key) if self.working(key) else 0) + self.energy(key, self.level(key) + 1) > self.solar():
            return 41
        return None

    def upgrade(self, key, now):
        err = self.check_upgrade(key)
        if err:
            return [err], []
        c = self.upgrade_cost(key)
        if INV.count(self.p, 'currency_credits') < c['kredi']:
            return [32], []
        for ore, code in UPGRADE_RES:
            if self.amount(ore) < c['kaynak']:
                return [code], []
        INV.spend(self.p, {'currency_credits': c['kredi']}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            for ore, _ in UPGRADE_RES:
                self.st['depo'][ore] -= c['kaynak']
            m = self.module(key)
            m['yukseltme'] = now + AY.sure(c['sure_sn'], 'skylab')       # panel: bekleme
            if m['seviye'] == 0:
                m['etkin'] = True                          # yeni kurulan modül bitince çalışır (enerji yetiyorsa)
            self.p.dirty = True
        self.log('   Skylab: %s -> %d yükseltmesi başladı (%d sn, %d C, %d x3 kaynak)' % (key, m['seviye'] + 1, c['sure_sn'], c['kredi'],
                                                                                        c['kaynak']))
        return [], [40]

    def instant_upgrade(self, key, now):
        err = self.check_upgrade(key)
        if err:
            return [err], []
        c = self.upgrade_cost(key)
        if INV.missing(self.p, {'currency_uridium': c['uridyum']}):
            return [44], []
        INV.spend(self.p, {'currency_uridium': c['uridyum']}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            if self.level(key) == 0:
                self.module(key)['etkin'] = True
            self.finish_upgrade(key, 45)
        self.gorev_bildir()
        self.log('   Skylab: %s anında yükseltildi (%d U)' % (key, c['uridyum']))
        return [], [45]

    def instant_finish(self, key, now):
        m = self.module(key)
        if not m.get('yukseltme'):
            return [30 if self.level(key) >= MODULES.get(key, {}).get('azami', 0) else 42], []
        price = self.finish_price(key, now)
        if INV.missing(self.p, {'currency_uridium': price}):
            return [44], []
        INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_' + key.lower())
        with self.p.lock:
            self.finish_upgrade(key, 46)
        self.gorev_bildir()
        self.log('   Skylab: %s yükseltmesi bitirildi (%d U)' % (key, price))
        return [], [45, 46]

    def abort(self, key):
        m = self.module(key)
        if not m.get('yukseltme'):
            return [], []
        with self.p.lock:
            m['yukseltme'] = None
            if m['seviye'] == 0:
                m['etkin'] = False
            self.p.dirty = True
        self.log('   Skylab: %s yükseltmesi iptal (harcananlar geri gelmez)' % key)
        return [], [43]

    def toggle(self, key, on):
        m = self.module(key)
        if key not in MODULES or key in ALWAYS_ON:
            return [], []
        if on:
            if m['seviye'] <= 0:
                return [36], []
            if m.get('yukseltme'):
                return [42], []
            if not m['etkin'] and self.consumption() + self.energy(key) > self.solar():
                return [39], []
        with self.p.lock:
            m['etkin'] = on
            self.p.dirty = True
        return [], [38 if on else 37]

    # ------------------------------------------------------------ taşıma
    def transport_time(self, load):
        """Normal taşımanın süresi: cevher başına birim_sn (Premium premium_birim_sn)."""
        per = TRANSPORT['premium_birim_sn' if self.p.premium else 'birim_sn']
        return AY.sure(int(math.ceil(sum(load.values()) * per)), 'skylab')

    def transport(self, f, now):
        mode, st = f.get('transportMode') or '', self.st
        price = AY.fiyat('hizmet_fiyat', TRANSPORT['hizli_uridyum'], 'skylab')      # panel
        if mode == 'instantFinish':
            if not st.get('tasima'):
                return [22], [], []
            if INV.missing(self.p, {'currency_uridium': price}):
                return [47], [], []
            INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_transport')
            with self.p.lock:
                load, st['tasima'] = st['tasima']['yuk'], None
                msgs = [x for x in self.deliver(load) if x[0] != '_receipt']
            return [], [53], msgs
        if not self.working('TRANSPORT_MODULE'):
            return [22], [], []
        if st.get('tasima'):
            return [48], [], []
        load = {}
        for field, ore in COUNT_FIELDS.items():
            n = min(max(0, int(f.get(field) or 0)), self.amount(ore))
            if n > 0:
                load[ore] = n
        total = sum(load.values())
        if not any(int(f.get(k) or 0) > 0 for k in COUNT_FIELDS):
            return [49], [], []
        if total <= 0:
            return [51], [], []
        if total > self.p.cargo_free():
            return [50], [], []
        if mode == 'fast' and INV.missing(self.p, {'currency_uridium': price}):
            return [47], [], []
        if mode == 'fast':
            INV.spend(self.p, {'currency_uridium': price}, reason='buy_SPECIAL', detail='skylab_transport')
        with self.p.lock:
            for ore, n in load.items():
                st['depo'][ore] -= n
            if mode == 'fast':
                msgs = [x for x in self.deliver(load) if x[0] != '_receipt']
            else:
                st['tasima'] = {'bitis': now + self.transport_time(load), 'yuk': load}
                msgs = []
            self.p.dirty = True
        self.log('   Skylab: taşıma %s %s' % ('anında' if mode == 'fast' else 'başladı', load))
        return [], [52, 53] if mode == 'fast' else [52], msgs

    # ------------------------------------------------------------ robotlar
    def raw(self, key):
        """BaseKey'lerde olmayan istemci metni: ham "XXX" + çevrilen değeri (magaza.RES_YERINE gibi)."""
        import magaza as MG
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=[
            mod('ArgStackCommand', type=0, value2=None, key=MG.ARG_KEYS['XXX'], value=MG.res(key))])

    def robots_bought(self):
        """"Skylab robots bought" (istemcinin metni; BaseKey'lerde yok: ham "XXX" + çevrilen değeri, magaza.RES_YERINE gibi)."""
        import magaza as MG
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=[
            mod('ArgStackCommand', type=0, value2=None, key=MG.ARG_KEYS['XXX'], value=MG.res('skylab_history_robots_bought'))])

    def productivity_msg(self, key, now):
        f = dict(self.productivity(key, now))
        f.pop('_')
        return ('SkylabModuleProductivityCommand', f)

    def buy_robot(self, f, now):
        """Robot alımı. Yanıtta modül sayfası (SkylabViewModuleBackCommand) yok: istemci sayfayı açarken (ShowSecondPage) sekmeyi
        Info'ya döndürüyordu, Productivity'de kalınamıyordu (kullanıcı 2026-10-24). Sekme SkylabModuleProductivityCommand'la yenilenir
        (RefreshSkyInfoRobotEvent -> UISkylabSystem.WriteProductivity)."""
        key, kind = f.get('construction', ''), str(f.get('robotType') or 1)
        if key not in COLLECTORS or kind not in ('1', '2'):
            return []
        cur, price = self.robot_price(kind)                                       # panel
        loot = 'currency_' + cur
        if INV.missing(self.p, {loot: price}):
            self.log('   Skylab: robot için %s yetmiyor' % cur)
            self.son_islem = ([32 if cur == 'credits' else 44], [])
            return self.out(key, 'purchase', [32 if cur == 'credits' else 44], [], [], now) + [self.productivity_msg(key, now)]
        INV.spend(self.p, {loot: price}, reason='buy_SPECIAL', detail='skylab_robot')
        with self.p.lock:
            rs = self.st['robotlar'].setdefault(key, [])
            if len(rs) < ROBOTS['azami']:
                rs.append([int(kind), now + ROBOTS['omur_sn']])
            else:
                self.st['yedek'].setdefault(key, []).append(int(kind))
            self.p.dirty = True
        self.log('   Skylab: %s robotu (%s) alındı, etkin %d, depoda %d' % (key, cur, len(rs), len(self.st['yedek'].get(key, []))))
        self.son_islem = ([], [self.robots_bought()])
        return self.out(key, 'purchase', [], [self.robots_bought()], [loot], now) + [self.productivity_msg(key, now)]

    # ------------------------------------------------------------ istekler
    def out(self, key, sub, errors, success, spent, now, extra=()):
        msgs = INV.update_msgs(self.m, self.p, spent) if spent else []
        return msgs + list(extra) + self.window(key, sub, errors, success)

    def action(self, f, now=None):
        now = now or time.time()
        key, sub = f.get('construction') or '', f.get('subaction') or ''
        pending = self.render(self.advance(now))
        before = (INV.count(self.p, 'currency_credits'), INV.count(self.p, 'currency_uridium'))
        extra = []
        if sub == '':
            err, ok = [], []
        elif sub == 'upgrade':
            err, ok = self.upgrade(key, now)
        elif sub == 'instantUpgrade':
            err, ok = self.instant_upgrade(key, now)
        elif sub == 'instantFinishUpgrade':
            err, ok = self.instant_finish(key, now)
        elif sub == 'abortUpgrade':
            err, ok = self.abort(key)
        elif sub in ('setActive', 'setInactive'):
            err, ok = self.toggle(key, sub == 'setActive')
        elif sub == 'startTransport':
            err, ok, extra = self.transport(f, now)
            extra = self.render(extra)
        else:
            self.log('   Skylab: bilinmeyen işlem %r' % sub)
            err, ok = [], []
        self.son_islem = (err, ok)          # panelin Skylab sayfası (panel_kanali.py): hata mı başarı mı
        if err:
            self.log('   Skylab: %s %s -> hata %s' % (sub, key, err))
        after = (INV.count(self.p, 'currency_credits'), INV.count(self.p, 'currency_uridium'))
        spent = ['currency_credits'] if after != before else []
        # modül sayfası (SkylabViewModuleBackCommand) gönderilmez: istemci işlem isteğiyle sayfayı kapatıp ana sayfaya dönüyor
        # (UISkylabSystem.SendActionRequest) ve sayfanın "yükseltiliyor" görünümünü modüle tıklandığı andaki durumdan okuyor
        # (UISkylab.Module.state); gönderilen sayfa eski durumla yeniden açılıyordu, kapatıp açınca düzeliyordu (kullanıcı 2026-10-18)
        return pending + self.out(key, sub, err, ok, spent, now, extra)

    def render(self, items):
        """advance/deliver çıktısı (profil kilidi dışında): ('_ores', {OreType: adet}) kargoya eklenir; ('_receipt', modül, alt
        işlem, hatalar, başarılar) -> pencere mesajları; ötekiler aynen."""
        out = []
        for it in items:
            if it[0] == '_receipt':
                out += self.window(it[1], it[2], it[3], it[4])
            elif it[0] == '_ores':
                out.append(('AttributeOreCountUpdateCommand', {'oreCountList': self.p.add_ores(it[1])}))
                if self.m:
                    out.append(self.m.ore_pack(sorted(it[1])))
            else:
                out.append(it)
        return out

    def handle(self, name, f):
        now = time.time()
        if name == 'SkylabActionRequest':
            return self.action(f, now)
        if name == 'SkylabViewModuleRequest':
            msgs = self.render(self.advance(now))
            v = self.view(f.get('moduleName', ''), now)
            return msgs + ([v] if v else [])
        if name == 'SkylabPurchaseRobotRequest':
            return self.render(self.advance(now)) + self.buy_robot(f, now)
        return None

    def tick(self, now):
        """Saniyede bir: dolan yükseltme ve taşımalar istemciye bildirilir (pencere açık değilse de zararsız)."""
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        if not any(e <= now for e in self.events(0)):
            return
        msgs = self.render(self.advance(now))
        if msgs and self.send:
            self.send(msgs)
