"""Bot yöneticisi: paketi yükler, botların çevrimiçi takvimini, kararlarını ve soyut benzetimini yürütür, durumu kaydeder.

Oyun sunucusunda tek örnek (BOT): game.py OO_BOT ortam değişkeniyle paketi verir, yönetici kendi iş parçacığında saniyede bir
tick() çalıştırır. Benzetim betiği (tools/bot_simulation.py) ve testler aynı sınıfı sahte saatle (now parametresi) sürer.

Her tick'te yalnız işi olan botlar işlenir: çevrimdışılar dakikada bir "girsem mi" der; çevrimiçiler kendi karar anlarında düşünür,
soyut etkiler SOYUT_SN'de bir toplu uygulanır. Dünyalar (ship.py) haritalarındaki botları kancalarla öğrenir.
"""
import json, os, random, threading, time, traceback

import map_links as H
from . import brain as B
from . import catalog as K
from . import personality as PS
from . import memories as MEM
from . import abstract_sim as S
from .state import Bot
from . import speech as SPC
from . import game_settings as GS
from .chat_engine import ChatEngine
from .goals import quest as QU
from .goals import shopping as SHOP

ABSTRACT_SEC = 5.0
PVP_SEC = 10.0
SIGNUP_SEC = 60.0
LOGIN_RETRY_SEC = 60.0
VERSION = 1
ACTIVE = None                   # oyun sunucusunun yöneticisi (game.py kurar; govde.py okur)
PRIME_POPULATION = 1.3              # yoğun saatte çevrimiçi olma eğilimi çarpanı
FRONTS = (16, 16, 29, 13, 14, 15)        # 4-4 iki kat, 4-5, 4-1, 4-2, 4-3

DEFAULTS = {                 # paketin ayarları (panel/botlar.py aynı anahtarları doğrular)
    'hiz': 1.0,                # ilerleme hızı çarpanı
    'online_ratio': 0.6,     # botların çevrimiçi olma eğilimi çarpanı
    'max_online': 0,     # aynı anda en çok çevrimiçi (0: sınırsız)
    'catchup_hours': 4,          # oyuncu yokken geçen süreden benzetilen en çok saat (0: telafi yok)
    'catch_up_rate': 0.35,       # telafide ilerleme oranı
    'signup_sec': 15,            # progressive: her firmaya ortalama bu kadar saniyede bir yeni pilot kayıt olur (0: hepsi baştan)
    'company_power': [1.0, 1.0, 1.0],        # firmaların gelişim çarpanı (MMO, EIC, VRU)
    'jumpstart_hours': 60,      # jumpstart: ortalama oyun saati (dağılım lognormal)
    'pvp_level': 6,
    'foreign_map': True,    # başka firmanın haritalarına girebilir
    'chat_min': 6,            # global/firma sohbetinde dakikada en çok bot satırı
    'help_max': 3,        # bir yardım çağrısına gelen en çok bot
    'max_concrete': 40,        # oyuncunun haritasında gemi olarak gösterilen en çok bot
    'bots_per_clan': 12,         # kaç bota bir bot klanı
    'rude_chat': 1,          # laf atma: 0 kapalı, 1 hafif, 2 sert, 3 çok sert (küfür ve gerçek tehdit hiçbirinde yok)
    'moderator': False,        # sohbet moderatörü botlar (bot/moderasyon.py)
    'mod_count': 2,
    'rule_caps': True, 'rule_flood': True, 'rule_insult': True, 'rule_ads': True,
    'mute_min': 10,           # susturma süresi
    'ban_threshold': 3,           # bu kadar susturmadan sonra yasak
    'ban_hours': 24,
    'prime_start': 19,     # akşam yoğun saatleri (yerel saat): çevrimiçi ve PvP artar, firmalar bir haritada toplanır
    'prime_end': 23,
    'prime_pvp': 2.0,          # yoğun saatte PvP isteği çarpanı (1: fark yok)
    'big_battle': True,       # yoğun saatte firmaların PvP botları ortak cephe haritasında toplanır
    'permissions': {'shop': True, 'gorev': True, 'pvp': True, 'sohbet': True, 'klan': True, 'clan_found': True, 'arkadas': True,
                'grup': True, 'auction': True, 'attack_player': True, 'yardim': True, 'box_stealing': True, 'kargo': True, 'roket': True, 'custom_ammunition': True, 'ekstra': True, 'mayin': True, 'lab': True, 'skylab': True, 'technology': True, 'booty': True, 'assembly': True, 'kapi': True, 'etkinlik': True, 'modes': True, 'clan_diplomacy': True, 'clan_order': True, 'gate_filler': True},
}


class Manager(ChatEngine):
    def __init__(self, package, state_path=None, log=print, now=None):
        self.package = package
        self.state_path = state_path
        self.log = log
        self.settings = dict(DEFAULTS, **(package.get('settings') or {}))
        self.settings['permissions'] = dict(DEFAULTS['permissions'], **(self.settings.get('permissions') or {}))
        self.mode = package.get('mode', 'normal')
        self.game_settings = GS.Profile(self.settings.get('game_settings'))      # botların oyun ayarı profili (oyuncununkinden ayrı)
        self.lock = threading.RLock()
        self.bots = []
        self.name_index = {}                  # ad küçük harf -> Bot
        self.on_map = {}             # harita -> {Bot}: çevrimiçi botlar
        self.worlds = []             # govde kancaları: harita_degisti(bot, eski), bot_cevrimici(bot, acik)
        self.humans = {}             # ad küçük harf -> (ad, harita, firma): sunucudaki gerçek oyuncular (dünyalar bildirir)
        self.last_pvp = self.last_save = self.now = now or time.time()   # now: benzetimin saati (sahte saatte de doğru)
        self.running = False
        self._thread = None
        self.society = False            # oyun sunucusunda topluluğa ve sohbete bağlı (toplum.kaydol)
        self.last_social = 0.0
        self.signup_queue = {}         # firma -> [Bot]: henüz kayıt olmamış pilotlar (progressive, sırayla katılır)
        self.next_signup = {}        # firma -> an
        self.prepare_chat()
        self.load(now)

    # ------------------------------------------------------------ ayarlar
    def setting(self, name, vars=None):
        return self.settings.get(name, vars)

    def permission(self, name):
        return bool(self.settings['permissions'].get(name, True))

    def speed(self, bot):
        """Botun ilerleme hızı: paketin hızı x firmasının gücü."""
        fg = self.settings.get('company_power') or [1, 1, 1]
        return float(self.settings.get('hiz', 1.0)) * float(fg[bot.firma - 1])

    # ------------------------------------------------------------ yükleme / kayıt
    def load(self, now=None):
        now = now or time.time()
        save = {}
        if self.state_path and os.path.exists(self.state_path):
            try:
                with open(self.state_path, encoding='utf8') as f:
                    save = json.load(f)
            except (OSError, ValueError) as e:
                self.log('   botlar: durum okunamadı (%s), baştan' % e)
        old = {str(k): v for k, v in (save.get('bots') or {}).items()}
        self.name_log_n = int(save.get('name_log') or 0)
        new_ = []
        # progressive yeni paket: pilotlar oyuna aynı anda değil, gerçek bir sunucuya kayıt olur gibi tek tek katılır (performans,
        # haritalara doğal dağılım); jumpstart kadrosu zaten oynamış sayılır
        ordered = self.mode != 'simple' and self.package.get('progression') != 'jumpstart' and self.setting('signup_sec', 15) > 0
        from . import llm_provider as PRV
        multilingual = PRV.multilingual()
        for roster_row in self.package.get('roster', []):
            k = old.get(str(roster_row['no']))
            if k is None:
                k = dict(no=roster_row['no'], ad=roster_row['ad'], firma=roster_row['firma'], personality=roster_row['personality'], registered=not ordered)
                new_.append(k)
            else:
                k.update(ad=roster_row['ad'], firma=roster_row['firma'], personality=roster_row['personality'])      # panelde ad değişmiş olabilir
            if self.mode == 'advanced' and not multilingual:
                k['personality'] = dict(k['personality'], dil='en')      # dahili dil modeli yalnız İngilizce (llm.py; başka sağlayıcıda serbest)
            b = Bot(k)
            b.permission = self.settings['permissions']
            b.rude = int(self.setting('rude_chat', 1))       # kaba sohbet düzeyi (llm.tarz, sohbet_motoru)
            b.hour = lambda: self.now
            b.game_settings = self.game_settings
            b.memory.listener = (lambda b: lambda name, kind, now: MEM.from_event(self, b, name, kind, now))(b)     # anı defteri (güçlü sağlayıcı)
            b.next_login = now + b.r.uniform(0, 20)
            self.bots.append(b)
            self.name_index[b.name.lower()] = b
        self.apply_name_log(loading=True)            # oyun kapalıyken panelde adı değişen ya da silinen botlar
        if self.mode == 'simple':
            from . import simple
            simple.prepare(self, now)
            return
        if new_ and self.package.get('progression') == 'jumpstart':
            self.jumpstart([b for b in self.bots if b.k in new_], now)
        for b in sorted(self.bots, key=lambda b: b.r.random()):
            if not b.saved:
                self.signup_queue.setdefault(b.firma, []).append(b)
        for f in self.signup_queue:
            self.next_signup[f] = now + self.setting('signup_sec', 15) * b.r.uniform(0.2, 1.0)
        t = save.get('t')
        if t and self.setting('catchup_hours', 0) > 0 and now - t > 600:
            self.catch_up(min(now - t, self.setting('catchup_hours') * 3600) * self.setting('catch_up_rate', 0.35), now)
        self.initial_population(now)
        from . import moderation as MOD
        MOD.sec(self)

    def apply_name_log(self, loading=False):
        """Panelde adı değişen ya da silinen botlar (name_log.py): çalışan botların adı, botların hafızası ve rehberleri; oyun
        açıkken (panel kanalı) klanlar ve bağlı oyuncuların rehberi de. -> uygulanan olay sayısı."""
        import name_log as NL
        new_ = NL.events_since(getattr(self, 'name_log_n', 0))
        if not new_:
            return 0
        from . import society
        lists = ('arkadas', 'incoming', 'outgoing', 'declined', 'blocked')
        with self.lock:
            if not loading:
                for e in new_:
                    if e['tur'] != 'ad':
                        continue
                    b = self.name_index.pop(NL._k(e['eski']), None)
                    if b is not None:
                        b.k['ad'] = e['yeni']
                        self.name_index[b.name.lower()] = b
                        for x in self.package.get('roster', []):
                            if x['no'] == b.k['no']:
                                x['ad'] = e['yeni']
                        if b.profile is not None:
                            society.update(b)          # oyundaki adı (gemisi bir sonraki görünüşte yeni adla)
            for b in self.bots:
                h = b.memory.d
                for e in new_:
                    if e['tur'] == 'ad' and NL._k(e['eski']) in h:
                        x = h.pop(NL._k(e['eski']))
                        x['ad'] = e['yeni']
                        h[NL._k(e['yeni'])] = x
                    elif e['tur'] == 'delete':
                        h.pop(NL._k(e['ad']), None)
                r = b.k.get('contacts') or {}
                for name in lists:
                    if isinstance(r.get(name), list):
                        x = NL.apply_list(r[name], new_)
                        if x is not None:
                            r[name] = x
            self.name_log_n = new_[-1]['n']
        society._PEOPLE['t'] = 0
        if not loading:
            import clan as KL
            import community as TP
            NL.apply_clans(KL)
            for k in list(TP.all_().values()):
                if k.name.lower() not in self.name_index:
                    NL.apply_profile(k.profile)           # bağlı oyuncuların rehberi ve klan kopyası
            self.log('   botlar: ad kaydı uygulandı (%d olay)' % len(new_))
        return len(new_)

    def save(self, now=None):
        if not self.state_path:
            return
        now = now or time.time()
        with self.lock:                                  # metin kilit içinde: dünya döngüsü sözlüklere eklerken yarım kalmasın
            d = dict(surum=VERSION, t=now, name_log=self.name_log_n, bots={str(b.k['no']): b.save() for b in self.bots})
            if self.llm is not None:
                d['llm'] = self.llm.summary()                    # panelin kullanım satırı (son bir saat: istek, token)
            text = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        tmp = self.state_path + '.tmp'
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        with open(tmp, 'w', encoding='utf8') as f:
            f.write(text)
        os.replace(tmp, self.state_path)
        self.last_save = now

    # ------------------------------------------------------------ çalıştırma
    def launch(self):
        if self._thread:
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, name='bots', daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False
        try:
            self.save()
        except Exception as e:                           # kapanışta öteki kayıtlar (misafirler, klan) atlanmasın
            self.log('   botlar: kaydedilemedi (%r)' % e)

    def _loop(self):
        while self.running:
            t0 = time.time()
            try:
                self.tick(t0)
            except Exception:
                self.log('   botlar: tick hatası\n' + traceback.format_exc())
            time.sleep(max(0.05, 1.0 - (time.time() - t0)))

    def tick(self, now=None):
        now = self.now = now or time.time()
        with self.lock:
            online = sum(1 for b in self.bots if b.online)
            limit = self.setting('max_online', 0) or len(self.bots)
            online += self.signup_tick(now, online, limit)
            for b in self.bots:
                if not b.saved:
                    continue
                try:                                     # bir botun hatası (bozuk ya da eski kayıt) ötekileri ve kaydı durdurmasın
                    if not b.online:
                        if now >= b.next_login:
                            b.next_login = now + LOGIN_RETRY_SEC * b.r.uniform(0.7, 1.3)
                            if online < limit and self._should_login(b, now):
                                self.entry(b, now)
                                online += 1
                        continue
                    self.bot_tick(b, now)
                    if not b.online:
                        online -= 1
                except Exception:
                    self.bot_error(b)
            if now - self.last_pvp >= PVP_SEC:
                self.last_pvp = now
                try:
                    self.pvp_tick(now)
                except Exception:
                    self.log_error('pvp')
            for name, fn in (('society', lambda: self._society_tick(now)),
                           ('sohbet', lambda: self.chat_tick(now)), ('llm', lambda: self.llm.tick(now) if self.llm else None)):
                try:
                    fn()
                except Exception:
                    self.log_error(name)
        if now - self.last_save >= SIGNUP_SEC:
            self.save(now)

    def _society_tick(self, now):
        if self.society and now - self.last_social >= ABSTRACT_SEC:
            self.last_social = now
            from . import society
            society.tick(self, now)

    def bot_error(self, b):
        """Bot başına bir kez günlüğe (her saniye aynı iz dökülmesin); 10 hatadan sonra bot bu oturumda dinlenir."""
        n = b.__dict__['_error'] = b.__dict__.get('_error', 0) + 1
        if n == 1:
            self.log('   botlar: %s hata verdi (atlandı)\n%s' % (b.name, traceback.format_exc()))
        if n >= 10:
            b.online = False
            b.next_login = self.now + 3600
            self.on_map.get(b.game_map, set()).discard(b)

    def log_error(self, name):
        c = self.__dict__.setdefault('_errors', {})
        c[name] = c.get(name, 0) + 1
        if c[name] in (1, 100, 10000):
            self.log('   botlar: %s hatası (%d. kez)\n%s' % (name, c[name], traceback.format_exc()))

    def bot_tick(self, b, now):
        self.now = now
        on_run = b.target is not None and b.target.name in ('kapi', 'mod') and not b.plan.get('finished')
        if now >= b.session_end and not b.en_route and b.dead_until <= now and not on_run:   # kapı/mod koşusu bitmeden çıkmaz
            if b.body is not None and b.body.alive and not b.__dict__.get('logout_ready'):
                # haritanda görünen bot olduğu yerde yok olmaz: istasyonuna ya da bir portala uçup orada çıkar (govde.cikisa_git)
                if not b.__dict__.get('exit_request'):
                    b.exit_request = now
                if now - b.exit_request < 90:
                    return
            b.exit_request = b.logout_ready = None
            self.exit(b, now)
            return
        if b.dead_until > now:
            return
        if now >= b.next_decision:
            B.decision(b, self, now)
            b.next_decision = now + B.next_decision_interval(b)
        dt = now - b.last_abstract
        if dt >= ABSTRACT_SEC:
            b.last_abstract = now
            # oturum uzadıkça yorulur (tutkunlar geç)
            b.mood.it(fatigue=dt / (3600.0 * (1.5 + 3 * (b.k['personality']['habit'] == 'devoted'))))
            b.ist('sure_sn', int(dt))
            from . import events as EV
            EV.battle_pass(b, min(dt, 60.0))             # pass görevleri ve Season Pass oynadıkça ilerler (uyku sonrası sınırlı)
            EV.season_pass(b, min(dt, 60.0))
            if b.body is None and b.target is not None:
                b.target.abstract(b, min(dt, 60.0), self)

    def signup_tick(self, now, online, limit):
        """Sıradaki pilotlar kayıt olur: her firmaya ayrı ayrı, ortalama kayit_sn'de (±%33) bir; yeni kayıt olan hemen oyuna girer
        (kendi üssünde, 1. seviye) -> giren sayısı."""
        n = 0
        avg = float(self.setting('signup_sec', 15) or 0)
        for f, order in self.signup_queue.items():
            if not order or now < self.next_signup.get(f, 0):
                continue
            b = order.pop(0)
            b.k['registered'] = True
            b.k['registered_at'] = now                         # rütbe puanı: kayıttan beri gün (toplum.puan)
            self.next_signup[f] = now + avg * b.r.uniform(0.67, 1.33)
            if online + n < limit:
                self.entry(b, now)
                n += 1
            else:
                b.next_login = now + LOGIN_RETRY_SEC
        return n

    def prime(self, now=None):
        """Akşamın yoğun saatleri mi (prime_baslangic-prime_bitis, yerel saat; gece yarısını geçebilir; eşitse yok)."""
        h = time.localtime(now or self.now).tm_hour
        a, b = int(self.setting('prime_start', 19)), int(self.setting('prime_end', 23))
        return a < b and a <= h < b or a > b and (h >= a or h < b)

    def front(self, now=None):
        """Yoğun saatin büyük savaş haritası: saat saat değişir, üç firmanın PvP botları aynı yerde buluşur (4-4, 4-5, 4-1/2/3)."""
        return FRONTS[int((now or self.now) // 3600) % len(FRONTS)]

    def _should_login(self, b, now):
        hour = time.localtime(now).tm_hour
        p = PS.online_tendency(b.k['personality'], hour) * self.setting('online_ratio', 0.6) * (PRIME_POPULATION if self.prime(now) else 1)
        # dakikalık deneme: saatlik eğilimi dakikaya böl (ortalama oturum ~1-3 saat; denge çevrimiçi payını eğilime yaklaştırır)
        return b.r.random() < p / 45.0

    def initial_population(self, now):
        """Sunucu açılınca o saatin dengedeki çevrimiçi nüfusu hemen kurulur (gerçek sunucuya giren oyuncu boş bir evren görmez):
        bot, dakikalık giriş olasılığı ve oturum uzunluğundan çıkan payla çevrimiçidir; oturumunun rastgele bir yerinde, sessizce."""
        hour = time.localtime(now).tm_hour
        limit = self.setting('max_online', 0) or len(self.bots)
        n = 0
        for b in sorted(self.bots, key=lambda b: b.r.random()):
            if n >= limit:
                break
            if not b.saved:
                continue
            p = PS.online_tendency(b.k['personality'], hour) * self.setting('online_ratio', 0.6) * (PRIME_POPULATION if self.prime(now) else 1)
            avg = sum(PS.HABITS[b.k['personality']['habit']][2]) / 2.0
            pay = (p / 45.0 * avg) / (1 + p / 45.0 * avg)
            if b.r.random() < pay:
                self.entry(b, now, silent=True)
                b.last_abstract = now - random.uniform(0, ABSTRACT_SEC)    # soyut adımlar aynı tickte toplanmasın (5 sn de bir kilitte 100+ ms); botun kendi dizisi (b.r) kaymasın
                b.session_end = now + (b.session_end - now) * b.r.uniform(0.1, 1.0)
                b.next_decision = now + b.r.uniform(1, 15)
                n += 1
        self.log('   botlar: %d bot çevrimiçi başladı' % n)

    def entry(self, b, now, silent=False):
        if b.game_map not in K.MAPS:                  # kapıda (ya da kapanmış bir haritada) çıkmıştı: üste döner
            b.k['harita'] = K.ev(b.firma)
            b.plan = {}
        b.online = True
        b.session_end = now + PS.session_min(b.k['personality'], b.r) * 60
        b.mood.update(now)
        b.mood.d['fatigue'] = 0.0
        b.last_abstract = now
        b.next_decision = now + b.r.uniform(2, 10)
        b.target = None
        b.__dict__.pop('_error', None)                    # hata sayacı oturumluk (ömürlük sayınca her tek hata botu 1 saat düşürüyordu)
        self.on_map.setdefault(b.game_map, set()).add(b)
        b._event_time = now
        if not silent and self.mode != 'simple' and b.r.random() < 0.25 * b.o('talkativeness'):
            self.speak(b, b.r.choice(('global', 'firma')), SPC.template(b, 'selam'), now=now + b.r.uniform(5, 40))
        for d in list(self.worlds):
            d.bot_online(b, True)

    def exit(self, b, now):
        if b.r.random() < 0.15 * b.o('talkativeness'):
            self.speak(b, 'global', SPC.template(b, 'cikis'), now=now, immediate=True)
            self.chat_tick(now)
        b.online = False
        b.next_login = now + b.r.uniform(15, 120) * 60          # çıkınca bir süre girmez
        b.target = None
        b.k['hedef'] = None
        b.body = None
        self.on_map.get(b.game_map, set()).discard(b)
        for d in list(self.worlds):
            d.bot_online(b, False)

    # ------------------------------------------------------------ kancalar (soyut.py, govde.py)
    def map_changed(self, b, old):
        if b.online:
            self.on_map.get(old, set()).discard(b)
            self.on_map.setdefault(b.game_map, set()).add(b)
        QU.advance(b, QU.VISIT_MAP, game_map=b.game_map, y=self)
        if b.game_map == K.ev(b.firma):
            QU.advance(b, QU.HOME, game_map=b.game_map, y=self)
        for d in list(self.worlds):
            d.map_changed(b, old)

    def npc_killed(self, b, tip, n=1):
        uid = K.NPC['types'].get(tip, {}).get('npc_kimlik')
        if uid is not None and b.k.get('gorev'):
            QU.advance(b, QU.KILL_NPC, n=n, npc_id=uid, game_map=b.game_map, y=self)

    def bot_died(self, b, killer):
        pass

    # ------------------------------------------------------------ sorgular
    def online_name(self, names):
        """Adlardan çevrimiçi ilk kişi (bot) ya da None."""
        for a in names:
            b = self.name_index.get(str(a).lower())
            if b is not None and b.online:
                return b
        return None

    def enemy_population(self, bot):
        """harita -> [çevrimiçi düşman firma botları]."""
        return {m: [x for x in s if x.firma != bot.firma and x.dead_until <= self.now] for m, s in self.on_map.items()}

    def state(self):
        with self.lock:
            return [b.summary() for b in self.bots]

    # ------------------------------------------------------------ bot-bot PvP (soyut)
    def pvp_tick(self, now):
        """Her haritada düşman botlar arası karşılaşma: avdaki (pvp hedefi) ya da saldırgan bot, haritadaki düşmanlardan birini
        bulur (olasılık nüfusla artar). Somut botlar (oyuncunun haritası) burada değil, gerçekten savaşır (govde)."""
        if not self.permission('pvp'):
            return
        for m, s in list(self.on_map.items()):
            if m not in K.MAPS:
                continue                                 # kapı haritaları: her botun kendi kopyası
            live = [b for b in s if b.dead_until <= now and b.body is None and not b.en_route]
            if len(live) < 2 or not K.pvp_map(m, live[0].firma) and len({b.firma for b in live}) < 2:
                continue
            companies = {}
            for b in live:
                companies.setdefault(b.firma, []).append(b)
            for a in live:
                if a.dead_until > now:
                    continue
                hunt = a.target is not None and a.target.name == 'pvp'
                enemy_count = len(live) - len(companies[a.firma])     # her bot için düşman listesi kurmak yerine sayı (büyük paketlerde O(n²))
                if not enemy_count:
                    continue
                # X-1/X-2'de kendi firmasının haritasında başka firmaya saldırmak serbest; karşılaşma olasılığı
                p = (0.12 if hunt else 0.006 * a.o('aggression')) * min(1.0, enemy_count / 3.0)
                if a.r.random() >= p:
                    continue
                f = a.r.choice([f for f in companies if f != a.firma])
                target = a.r.choice(companies[f])
                if a.k.get('klan'):
                    from . import society as TP
                    combat = [h for h in companies[f] if TP.clan_relation(a, h) == 3]
                    if combat:
                        target = a.r.choice(combat)        # klan savaşı: haritadaki düşman klanın üyesi önce
                if target.dead_until > now or a.k.get('klan') and TP.clan_relation(a, target) in (1, 2):
                    continue
                ratio = target.value()['power'] / max(0.5, a.value()['power'])
                if not hunt and ratio > 0.9 + 0.6 * a.o('risk'):
                    continue                     # avda değilken güçlüye saldırmaz
                if ratio > 1.6 + a.o('risk') + a.mood['anger']:
                    continue                     # avda bile çok güçlüye saldırmaz
                result = S.encounter(a, target, self, now)
                if result and result[0] == 'won' and result[1].k.get('gorev'):
                    QU.advance(result[1], QU.KILL_PLAYERS, game_map=result[1].game_map, y=self)

    # ------------------------------------------------------------ hızlı ilerletme
    def fast(self, b, seconds, now, step=900.0, pvp=False):
        """Botu saniye kadar oynamış gibi ilerletir (jumpstart, telafi): büyük adımlar, kararlar adım başına."""
        t = now - seconds
        b.online = True
        b.target = None
        while t < now:
            dt = min(step, now - t)
            t += dt
            self.now = t
            b.dead_until = 0
            b.en_route = None
            B.decision(b, self, t)
            if b.target is not None:
                if b.en_route:
                    while b.en_route:
                        S.jump_to(b, b.en_route.pop(0), None)
                b.target.abstract(b, dt, self)
            if self.permission('shop'):
                for _ in range(8):           # büyük adımda biriken parayı harcar (gerçek zamanda ayrı kararlar)
                    c = SHOP.candidate(b)[0]
                    if c is None or not b.pay(c[1], c[2]):
                        break
                    b.add(c[3])
            b.mood.d['fatigue'] = 0.0
        b.online = False
        b.target = None
        b.dead_until = 0
        self.now = now

    def jumpstart(self, bots, now):
        """Yeni kadro gerçekçi bir dağılımla başlar: her bota lognormal "oynadığı saat" (çok acemi, çok orta, az güçlü), firma
        gücüyle çarpılır; bot o kadar oynamış gibi hızlı ilerletilir (donanımı, seviyesi, parası birbiriyle tutarlı)."""
        import math
        avg = max(1.0, float(self.setting('jumpstart_hours', 60)))
        fg = self.setting('company_power', [1, 1, 1])
        t0 = time.time()
        for b in bots:
            hour = b.r.lognormvariate(math.log(avg) - 0.5, 1.0) * float(fg[b.firma - 1]) * (0.6 + 0.8 * b.o('ambition'))
            hour = min(hour, avg * 8)
            self.fast(b, hour * 3600, now, step=max(1800.0, hour * 3600 / 60))
        self.log('   botlar: jumpstart %d bot, %.1f sn' % (len(bots), time.time() - t0))

    def catch_up(self, seconds, now):
        """Oyuncu yokken geçen sürenin bir kısmı: çevrimiçi olma eğilimi kadar bot ilerler."""
        t0 = time.time()
        for b in self.bots:
            if not b.saved:
                continue
            pay = sum(PS.HABITS[b.k['personality']['habit']][1]) / 24.0 * self.setting('online_ratio', 0.6)
            s = seconds * pay * b.r.uniform(0.5, 1.5)
            if s > 300:
                self.fast(b, s, now, step=900.0)
        self.log('   botlar: çevrimdışı telafi %.0f dk, %.1f sn' % (seconds / 60, time.time() - t0))


def server(route, log=print):
    """Oyun sunucusu açılırken (game.main, OO_BOT): paketi okur, yöneticiyi arka planda kurar (jumpstart ve çevrimdışı telafi
    saniyeler sürebilir; oyun beklemez) ve çalıştırır. Paketin durumu paket dosyasının yanındaki <kimlik>/durum.json."""
    global ACTIVE
    try:
        with open(route, encoding='utf8') as f:
            package = json.load(f)
    except (OSError, ValueError) as e:
        log('   botlar: paket okunamadı (%s): %s' % (route, e))
        return

    def rate():
        global ACTIVE
        uid = os.path.splitext(os.path.basename(route))[0]
        state = os.path.join(os.path.dirname(route), uid, 'state.json')
        t0 = time.time()
        y = Manager(package, state, log)
        import clan as KL
        import community as TP
        from . import society
        if not KL.FILE:                                  # bot klanları kalıcı (arkadaş sunucusunda ortak klan dosyası zaten var)
            KL.configure(os.path.join(os.path.dirname(state), 'clans.json'))
        society.register(y, getattr(TP.GAME, 'CHAT', None))
        y.society = True
        if y.mode == 'advanced':
            from . import llm, llm_provider, llm_server
            if llm_provider.multilingual() or llm_server.setup() is not None:   # kullanıcının sağlayıcısı ya da kurulu dahili model
                y.llm = llm.Brain(y, log)                  # model arka planda açılır; hazır olana dek kalıplar
                y.llm.launch()
            else:
                log('   botlar: Gelişmiş kip ama dil modeli kurulu değil (Botlar > Gelişmiş kip): Normal kip gibi sürüyor')
        ACTIVE = y
        y.launch()
        log('botlar: "%s" (%s, %d bot) %.1f sn' % (package.get('ad', uid), package.get('mode', 'normal'), len(y.bots), time.time() - t0))

    threading.Thread(target=rate, name='bots-setup', daemon=True).start()


def close():
    """Sunucu kapanıyor (game.stop_gracefully): durum kaydedilir."""
    if ACTIVE is not None:
        ACTIVE.stop()
        if ACTIVE.llm is not None:
            ACTIVE.llm.stop()
