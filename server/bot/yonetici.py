"""Bot yöneticisi: paketi yükler, botların çevrimiçi takvimini, kararlarını ve soyut benzetimini yürütür, durumu kaydeder.

Oyun sunucusunda tek örnek (BOT): game.py DO_BOT ortam değişkeniyle paketi verir, yönetici kendi iş parçacığında saniyede bir
tick() çalıştırır. Benzetim betiği (tools/bot_benzetim.py) ve testler aynı sınıfı sahte saatle (now parametresi) sürer.

Her tick'te yalnız işi olan botlar işlenir: çevrimdışılar dakikada bir "girsem mi" der; çevrimiçiler kendi karar anlarında düşünür,
soyut etkiler SOYUT_SN'de bir toplu uygulanır. Dünyalar (govde.py) haritalarındaki botları kancalarla öğrenir.
"""
import json, os, threading, time, traceback

import harita as H
from . import beyin as B
from . import katalog as K
from . import kisilik as KS
from . import ani as ANI
from . import soyut as S
from .durum import Bot
from . import konusma as KN
from . import oyun_ayari as OA
from .sohbet_motoru import SohbetMotoru
from .hedefler import gorev as GV
from .hedefler import alisveris as ALIS

SOYUT_SN = 5.0
PVP_SN = 10.0
KAYIT_SN = 60.0
GIRIS_DENEME_SN = 60.0
SURUM = 1
AKTIF = None                   # oyun sunucusunun yöneticisi (game.py kurar; govde.py okur)
PRIME_NUFUS = 1.3              # yoğun saatte çevrimiçi olma eğilimi çarpanı
CEPHELER = (16, 16, 29, 13, 14, 15)        # 4-4 iki kat, 4-5, 4-1, 4-2, 4-3

VARSAYILAN = {                 # paketin ayarları (panel/botlar.py aynı anahtarları doğrular)
    'hiz': 1.0,                # ilerleme hızı çarpanı
    'cevrimici_oran': 0.6,     # botların çevrimiçi olma eğilimi çarpanı
    'en_cok_cevrimici': 0,     # aynı anda en çok çevrimiçi (0: sınırsız)
    'telafi_saat': 4,          # oyuncu yokken geçen süreden benzetilen en çok saat (0: telafi yok)
    'telafi_oran': 0.35,       # telafide ilerleme oranı
    'kayit_sn': 15,            # progressive: her firmaya ortalama bu kadar saniyede bir yeni pilot kayıt olur (0: hepsi baştan)
    'firma_guc': [1.0, 1.0, 1.0],        # firmaların gelişim çarpanı (MMO, EIC, VRU)
    'jumpstart_saat': 60,      # jumpstart: ortalama oyun saati (dağılım lognormal)
    'pvp_seviye': 6,
    'yabanci_harita': True,    # başka firmanın haritalarına girebilir
    'sohbet_dk': 6,            # global/firma sohbetinde dakikada en çok bot satırı
    'yardim_en_cok': 3,        # bir yardım çağrısına gelen en çok bot
    'somut_en_cok': 40,        # oyuncunun haritasında gemi olarak gösterilen en çok bot
    'klan_basina': 12,         # kaç bota bir bot klanı
    'kaba_sohbet': 1,          # laf atma: 0 kapalı, 1 hafif, 2 sert, 3 çok sert (küfür ve gerçek tehdit hiçbirinde yok)
    'moderator': False,        # sohbet moderatörü botlar (bot/moderasyon.py)
    'mod_sayisi': 2,
    'kural_buyuk': True, 'kural_sel': True, 'kural_hakaret': True, 'kural_reklam': True,
    'sustur_dk': 10,           # susturma süresi
    'yasak_esik': 3,           # bu kadar susturmadan sonra yasak
    'yasak_saat': 24,
    'prime_baslangic': 19,     # akşam yoğun saatleri (yerel saat): çevrimiçi ve PvP artar, firmalar bir haritada toplanır
    'prime_bitis': 23,
    'prime_pvp': 2.0,          # yoğun saatte PvP isteği çarpanı (1: fark yok)
    'buyuk_savas': True,       # yoğun saatte firmaların PvP botları ortak cephe haritasında toplanır
    'izinler': {'magaza': True, 'gorev': True, 'pvp': True, 'sohbet': True, 'klan': True, 'klan_kur': True, 'arkadas': True,
                'grup': True, 'muzayede': True, 'oyuncuya_saldir': True, 'yardim': True, 'kutu_calma': True, 'kargo': True, 'roket': True, 'ozel_cephane': True, 'ekstra': True, 'mayin': True, 'lab': True, 'skylab': True, 'teknoloji': True, 'ganimet': True, 'assembly': True, 'kapi': True, 'etkinlik': True, 'modlar': True, 'klan_diplomasi': True, 'klan_emir': True, 'kapi_dolgu': True},
}


class Yonetici(SohbetMotoru):
    def __init__(self, paket, durum_yolu=None, log=print, now=None):
        self.paket = paket
        self.durum_yolu = durum_yolu
        self.log = log
        self.ayarlar = dict(VARSAYILAN, **(paket.get('ayarlar') or {}))
        self.ayarlar['izinler'] = dict(VARSAYILAN['izinler'], **(self.ayarlar.get('izinler') or {}))
        self.kip = paket.get('kip', 'normal')
        self.oa = OA.Profil(self.ayarlar.get('oyun_ayari'))      # botların oyun ayarı profili (oyuncununkinden ayrı)
        self.lock = threading.RLock()
        self.botlar = []
        self.ada = {}                  # ad küçük harf -> Bot
        self.haritada = {}             # harita -> {Bot}: çevrimiçi botlar
        self.dunyalar = []             # govde kancaları: harita_degisti(bot, eski), bot_cevrimici(bot, acik)
        self.insanlar = {}             # ad küçük harf -> (ad, harita, firma): sunucudaki gerçek oyuncular (dünyalar bildirir)
        self.son_pvp = self.son_kayit = self.now = now or time.time()   # now: benzetimin saati (sahte saatte de doğru)
        self.calisiyor = False
        self._is = None
        self.toplum = False            # oyun sunucusunda topluluğa ve sohbete bağlı (toplum.kaydol)
        self.son_sosyal = 0.0
        self.kayit_sirasi = {}         # firma -> [Bot]: henüz kayıt olmamış pilotlar (progressive, sırayla katılır)
        self.sonraki_kayit = {}        # firma -> an
        self.sohbet_hazirla()
        self.yukle(now)

    # ------------------------------------------------------------ ayarlar
    def ayar(self, ad, vars=None):
        return self.ayarlar.get(ad, vars)

    def izin(self, ad):
        return bool(self.ayarlar['izinler'].get(ad, True))

    def hiz(self, bot):
        """Botun ilerleme hızı: paketin hızı x firmasının gücü."""
        fg = self.ayarlar.get('firma_guc') or [1, 1, 1]
        return float(self.ayarlar.get('hiz', 1.0)) * float(fg[bot.firma - 1])

    # ------------------------------------------------------------ yükleme / kayıt
    def yukle(self, now=None):
        now = now or time.time()
        kayit = {}
        if self.durum_yolu and os.path.exists(self.durum_yolu):
            try:
                with open(self.durum_yolu, encoding='utf8') as f:
                    kayit = json.load(f)
            except (OSError, ValueError) as e:
                self.log('   botlar: durum okunamadı (%s), baştan' % e)
        eski = {str(k): v for k, v in (kayit.get('botlar') or {}).items()}
        self.ad_kaydi_n = int(kayit.get('ad_kaydi') or 0)
        yeni = []
        # progressive yeni paket: pilotlar oyuna aynı anda değil, gerçek bir sunucuya kayıt olur gibi tek tek katılır (performans,
        # haritalara doğal dağılım); jumpstart kadrosu zaten oynamış sayılır
        sirali = self.kip != 'basit' and self.paket.get('gelisim') != 'jumpstart' and self.ayar('kayit_sn', 15) > 0
        from . import llm_saglayici as SG
        cok_dilli = SG.cok_dilli()
        for kd in self.paket.get('kadro', []):
            k = eski.get(str(kd['no']))
            if k is None:
                k = dict(no=kd['no'], ad=kd['ad'], firma=kd['firma'], kisilik=kd['kisilik'], kayitli=not sirali)
                yeni.append(k)
            else:
                k.update(ad=kd['ad'], firma=kd['firma'], kisilik=kd['kisilik'])      # panelde ad değişmiş olabilir
            if self.kip == 'gelismis' and not cok_dilli:
                k['kisilik'] = dict(k['kisilik'], dil='en')      # dahili dil modeli yalnız İngilizce (llm.py; başka sağlayıcıda serbest)
            b = Bot(k)
            b.izin = self.ayarlar['izinler']
            b.kaba = int(self.ayar('kaba_sohbet', 1))       # kaba sohbet düzeyi (llm.tarz, sohbet_motoru)
            b.saat = lambda: self.now
            b.oa = self.oa
            b.hafiza.dinle = (lambda b: lambda ad, tur, now: ANI.olaydan(self, b, ad, tur, now))(b)     # anı defteri (güçlü sağlayıcı)
            b.sonraki_giris = now + b.r.uniform(0, 20)
            self.botlar.append(b)
            self.ada[b.ad.lower()] = b
        self.ad_kaydi_uygula(yukleniyor=True)            # oyun kapalıyken panelde adı değişen ya da silinen botlar
        if self.kip == 'basit':
            from . import basit
            basit.hazirla(self, now)
            return
        if yeni and self.paket.get('gelisim') == 'jumpstart':
            self.jumpstart([b for b in self.botlar if b.k in yeni], now)
        for b in sorted(self.botlar, key=lambda b: b.r.random()):
            if not b.kayitli:
                self.kayit_sirasi.setdefault(b.firma, []).append(b)
        for f in self.kayit_sirasi:
            self.sonraki_kayit[f] = now + self.ayar('kayit_sn', 15) * b.r.uniform(0.2, 1.0)
        t = kayit.get('t')
        if t and self.ayar('telafi_saat', 0) > 0 and now - t > 600:
            self.telafi(min(now - t, self.ayar('telafi_saat') * 3600) * self.ayar('telafi_oran', 0.35), now)
        self.ilk_nufus(now)
        from . import moderasyon as MOD
        MOD.sec(self)

    def ad_kaydi_uygula(self, yukleniyor=False):
        """Panelde adı değişen ya da silinen botlar (ad_kaydi.py): çalışan botların adı, botların hafızası ve rehberleri; oyun
        açıkken (panel kanalı) klanlar ve bağlı oyuncuların rehberi de. -> uygulanan olay sayısı."""
        import ad_kaydi as AK
        yeni = AK.yeniler(getattr(self, 'ad_kaydi_n', 0))
        if not yeni:
            return 0
        from . import toplum
        listeler = ('arkadas', 'gelen', 'giden', 'reddeden', 'engelli')
        with self.lock:
            if not yukleniyor:
                for e in yeni:
                    if e['tur'] != 'ad':
                        continue
                    b = self.ada.pop(AK._k(e['eski']), None)
                    if b is not None:
                        b.k['ad'] = e['yeni']
                        self.ada[b.ad.lower()] = b
                        for x in self.paket.get('kadro', []):
                            if x['no'] == b.k['no']:
                                x['ad'] = e['yeni']
                        if b.profil is not None:
                            toplum.guncelle(b)          # oyundaki adı (gemisi bir sonraki görünüşte yeni adla)
            for b in self.botlar:
                h = b.hafiza.d
                for e in yeni:
                    if e['tur'] == 'ad' and AK._k(e['eski']) in h:
                        x = h.pop(AK._k(e['eski']))
                        x['ad'] = e['yeni']
                        h[AK._k(e['yeni'])] = x
                    elif e['tur'] == 'sil':
                        h.pop(AK._k(e['ad']), None)
                r = b.k.get('rehber') or {}
                for ad in listeler:
                    if isinstance(r.get(ad), list):
                        x = AK.liste_uygula(r[ad], yeni)
                        if x is not None:
                            r[ad] = x
            self.ad_kaydi_n = yeni[-1]['n']
        toplum._KISILER['t'] = 0
        if not yukleniyor:
            import klan as KL
            import topluluk as TP
            AK.klanlar_uygula(KL)
            for k in list(TP.hepsi().values()):
                if k.ad.lower() not in self.ada:
                    AK.profil_uygula(k.profil)           # bağlı oyuncuların rehberi ve klan kopyası
            self.log('   botlar: ad kaydı uygulandı (%d olay)' % len(yeni))
        return len(yeni)

    def kaydet(self, now=None):
        if not self.durum_yolu:
            return
        now = now or time.time()
        with self.lock:                                  # metin kilit içinde: dünya döngüsü sözlüklere eklerken yarım kalmasın
            d = dict(surum=SURUM, t=now, ad_kaydi=self.ad_kaydi_n, botlar={str(b.k['no']): b.kayit() for b in self.botlar})
            if self.llm is not None:
                d['llm'] = self.llm.ozet()                    # panelin kullanım satırı (son bir saat: istek, token)
            metin = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        tmp = self.durum_yolu + '.tmp'
        os.makedirs(os.path.dirname(self.durum_yolu), exist_ok=True)
        with open(tmp, 'w', encoding='utf8') as f:
            f.write(metin)
        os.replace(tmp, self.durum_yolu)
        self.son_kayit = now

    # ------------------------------------------------------------ çalıştırma
    def baslat(self):
        if self._is:
            return
        self.calisiyor = True
        self._is = threading.Thread(target=self._dongu, name='botlar', daemon=True)
        self._is.start()

    def durdur(self):
        self.calisiyor = False
        try:
            self.kaydet()
        except Exception as e:                           # kapanışta öteki kayıtlar (misafirler, klan) atlanmasın
            self.log('   botlar: kaydedilemedi (%r)' % e)

    def _dongu(self):
        while self.calisiyor:
            t0 = time.time()
            try:
                self.tick(t0)
            except Exception:
                self.log('   botlar: tick hatası\n' + traceback.format_exc())
            time.sleep(max(0.05, 1.0 - (time.time() - t0)))

    def tick(self, now=None):
        now = self.now = now or time.time()
        with self.lock:
            cevrimici = sum(1 for b in self.botlar if b.cevrimici)
            sinir = self.ayar('en_cok_cevrimici', 0) or len(self.botlar)
            cevrimici += self.kayit_tick(now, cevrimici, sinir)
            for b in self.botlar:
                if not b.kayitli:
                    continue
                try:                                     # bir botun hatası (bozuk ya da eski kayıt) ötekileri ve kaydı durdurmasın
                    if not b.cevrimici:
                        if now >= b.sonraki_giris:
                            b.sonraki_giris = now + GIRIS_DENEME_SN * b.r.uniform(0.7, 1.3)
                            if cevrimici < sinir and self._girsin_mi(b, now):
                                self.giris(b, now)
                                cevrimici += 1
                        continue
                    self.bot_tick(b, now)
                    if not b.cevrimici:
                        cevrimici -= 1
                except Exception:
                    self.bot_hatasi(b)
            if now - self.son_pvp >= PVP_SN:
                self.son_pvp = now
                try:
                    self.pvp_tick(now)
                except Exception:
                    self.hata_kaydi('pvp')
            for ad, fn in (('toplum', lambda: self._toplum_tick(now)),
                           ('sohbet', lambda: self.sohbet_tick(now)), ('llm', lambda: self.llm.tick(now) if self.llm else None)):
                try:
                    fn()
                except Exception:
                    self.hata_kaydi(ad)
        if now - self.son_kayit >= KAYIT_SN:
            self.kaydet(now)

    def _toplum_tick(self, now):
        if self.toplum and now - self.son_sosyal >= SOYUT_SN:
            self.son_sosyal = now
            from . import toplum
            toplum.tick(self, now)

    def bot_hatasi(self, b):
        """Bot başına bir kez günlüğe (her saniye aynı iz dökülmesin); 10 hatadan sonra bot bu oturumda dinlenir."""
        n = b.__dict__['_hata'] = b.__dict__.get('_hata', 0) + 1
        if n == 1:
            self.log('   botlar: %s hata verdi (atlandı)\n%s' % (b.ad, traceback.format_exc()))
        if n >= 10:
            b.cevrimici = False
            b.sonraki_giris = self.now + 3600
            self.haritada.get(b.harita, set()).discard(b)

    def hata_kaydi(self, ad):
        c = self.__dict__.setdefault('_hatalar', {})
        c[ad] = c.get(ad, 0) + 1
        if c[ad] in (1, 100, 10000):
            self.log('   botlar: %s hatası (%d. kez)\n%s' % (ad, c[ad], traceback.format_exc()))

    def bot_tick(self, b, now):
        self.now = now
        kosuda = b.hedef is not None and b.hedef.ad in ('kapi', 'mod') and not b.plan.get('bitti')
        if now >= b.oturum_bitis and not b.yolda and b.olu_bitis <= now and not kosuda:   # kapı/mod koşusu bitmeden çıkmaz
            if b.govde is not None and b.govde.alive and not b.__dict__.get('cikis_hazir'):
                # haritanda görünen bot olduğu yerde yok olmaz: istasyonuna ya da bir portala uçup orada çıkar (govde.cikisa_git)
                if not b.__dict__.get('cikis_istegi'):
                    b.cikis_istegi = now
                if now - b.cikis_istegi < 90:
                    return
            b.cikis_istegi = b.cikis_hazir = None
            self.cikis(b, now)
            return
        if b.olu_bitis > now:
            return
        if now >= b.sonraki_karar:
            B.karar(b, self, now)
            b.sonraki_karar = now + B.sonraki_karar_araligi(b)
        dt = now - b.son_soyut
        if dt >= SOYUT_SN:
            b.son_soyut = now
            # oturum uzadıkça yorulur (tutkunlar geç)
            b.ruh.it(yorgunluk=dt / (3600.0 * (1.5 + 3 * (b.k['kisilik']['aliskanlik'] == 'tutkun'))))
            b.ist('sure_sn', int(dt))
            from . import etkinlik as ET
            ET.battle_pass(b, min(dt, 60.0))             # pass görevleri ve Season Pass oynadıkça ilerler (uyku sonrası sınırlı)
            ET.season_pass(b, min(dt, 60.0))
            if b.govde is None and b.hedef is not None:
                b.hedef.soyut(b, min(dt, 60.0), self)

    def kayit_tick(self, now, cevrimici, sinir):
        """Sıradaki pilotlar kayıt olur: her firmaya ayrı ayrı, ortalama kayit_sn'de (±%33) bir; yeni kayıt olan hemen oyuna girer
        (kendi üssünde, 1. seviye) -> giren sayısı."""
        n = 0
        ort = float(self.ayar('kayit_sn', 15) or 0)
        for f, sira in self.kayit_sirasi.items():
            if not sira or now < self.sonraki_kayit.get(f, 0):
                continue
            b = sira.pop(0)
            b.k['kayitli'] = True
            b.k['kayit_t'] = now                         # rütbe puanı: kayıttan beri gün (toplum.puan)
            self.sonraki_kayit[f] = now + ort * b.r.uniform(0.67, 1.33)
            if cevrimici + n < sinir:
                self.giris(b, now)
                n += 1
            else:
                b.sonraki_giris = now + GIRIS_DENEME_SN
        return n

    def prime(self, now=None):
        """Akşamın yoğun saatleri mi (prime_baslangic-prime_bitis, yerel saat; gece yarısını geçebilir; eşitse yok)."""
        h = time.localtime(now or self.now).tm_hour
        a, b = int(self.ayar('prime_baslangic', 19)), int(self.ayar('prime_bitis', 23))
        return a < b and a <= h < b or a > b and (h >= a or h < b)

    def cephe(self, now=None):
        """Yoğun saatin büyük savaş haritası: saat saat değişir, üç firmanın PvP botları aynı yerde buluşur (4-4, 4-5, 4-1/2/3)."""
        return CEPHELER[int((now or self.now) // 3600) % len(CEPHELER)]

    def _girsin_mi(self, b, now):
        saat = time.localtime(now).tm_hour
        p = KS.cevrimici_egilim(b.k['kisilik'], saat) * self.ayar('cevrimici_oran', 0.6) * (PRIME_NUFUS if self.prime(now) else 1)
        # dakikalık deneme: saatlik eğilimi dakikaya böl (ortalama oturum ~1-3 saat; denge çevrimiçi payını eğilime yaklaştırır)
        return b.r.random() < p / 45.0

    def ilk_nufus(self, now):
        """Sunucu açılınca o saatin dengedeki çevrimiçi nüfusu hemen kurulur (gerçek sunucuya giren oyuncu boş bir evren görmez):
        bot, dakikalık giriş olasılığı ve oturum uzunluğundan çıkan payla çevrimiçidir; oturumunun rastgele bir yerinde, sessizce."""
        saat = time.localtime(now).tm_hour
        sinir = self.ayar('en_cok_cevrimici', 0) or len(self.botlar)
        n = 0
        for b in sorted(self.botlar, key=lambda b: b.r.random()):
            if n >= sinir:
                break
            if not b.kayitli:
                continue
            p = KS.cevrimici_egilim(b.k['kisilik'], saat) * self.ayar('cevrimici_oran', 0.6) * (PRIME_NUFUS if self.prime(now) else 1)
            ort = sum(KS.ALISKANLIKLAR[b.k['kisilik']['aliskanlik']][2]) / 2.0
            pay = (p / 45.0 * ort) / (1 + p / 45.0 * ort)
            if b.r.random() < pay:
                self.giris(b, now, sessiz=True)
                b.oturum_bitis = now + (b.oturum_bitis - now) * b.r.uniform(0.1, 1.0)
                b.sonraki_karar = now + b.r.uniform(1, 15)
                n += 1
        self.log('   botlar: %d bot çevrimiçi başladı' % n)

    def giris(self, b, now, sessiz=False):
        if b.harita not in K.HARITALAR:                  # kapıda (ya da kapanmış bir haritada) çıkmıştı: üste döner
            b.k['harita'] = K.ev(b.firma)
            b.plan = {}
        b.cevrimici = True
        b.oturum_bitis = now + KS.oturum_dk(b.k['kisilik'], b.r) * 60
        b.ruh.guncelle(now)
        b.ruh.d['yorgunluk'] = 0.0
        b.son_soyut = now
        b.sonraki_karar = now + b.r.uniform(2, 10)
        b.hedef = None
        b.__dict__.pop('_hata', None)                    # hata sayacı oturumluk (ömürlük sayınca her tek hata botu 1 saat düşürüyordu)
        self.haritada.setdefault(b.harita, set()).add(b)
        b._olay_t = now
        if not sessiz and self.kip != 'basit' and b.r.random() < 0.25 * b.o('konuskanlik'):
            self.konus(b, b.r.choice(('global', 'firma')), KN.kalip(b, 'selam'), now=now + b.r.uniform(5, 40))
        for d in list(self.dunyalar):
            d.bot_cevrimici(b, True)

    def cikis(self, b, now):
        if b.r.random() < 0.15 * b.o('konuskanlik'):
            self.konus(b, 'global', KN.kalip(b, 'cikis'), now=now, hemen=True)
            self.sohbet_tick(now)
        b.cevrimici = False
        b.sonraki_giris = now + b.r.uniform(15, 120) * 60          # çıkınca bir süre girmez
        b.hedef = None
        b.k['hedef'] = None
        b.govde = None
        self.haritada.get(b.harita, set()).discard(b)
        for d in list(self.dunyalar):
            d.bot_cevrimici(b, False)

    # ------------------------------------------------------------ kancalar (soyut.py, govde.py)
    def harita_degisti(self, b, eski):
        if b.cevrimici:
            self.haritada.get(eski, set()).discard(b)
            self.haritada.setdefault(b.harita, set()).add(b)
        GV.ilerlet(b, GV.VISIT_MAP, harita=b.harita, y=self)
        if b.harita == K.ev(b.firma):
            GV.ilerlet(b, GV.HOME, harita=b.harita, y=self)
        for d in list(self.dunyalar):
            d.harita_degisti(b, eski)

    def npc_oldurdu(self, b, tip, n=1):
        kimlik = K.NPC['tipler'].get(tip, {}).get('npc_kimlik')
        if kimlik is not None and b.k.get('gorev'):
            GV.ilerlet(b, GV.KILL_NPC, n=n, npc_kimlik=kimlik, harita=b.harita, y=self)

    def bot_oldu(self, b, katil):
        pass

    # ------------------------------------------------------------ sorgular
    def cevrimici_ad(self, adlar):
        """Adlardan çevrimiçi ilk kişi (bot) ya da None."""
        for a in adlar:
            b = self.ada.get(str(a).lower())
            if b is not None and b.cevrimici:
                return b
        return None

    def dusman_nufusu(self, bot):
        """harita -> [çevrimiçi düşman firma botları]."""
        return {m: [x for x in s if x.firma != bot.firma and x.olu_bitis <= self.now] for m, s in self.haritada.items()}

    def durum(self):
        with self.lock:
            return [b.ozet() for b in self.botlar]

    # ------------------------------------------------------------ bot-bot PvP (soyut)
    def pvp_tick(self, now):
        """Her haritada düşman botlar arası karşılaşma: avdaki (pvp hedefi) ya da saldırgan bot, haritadaki düşmanlardan birini
        bulur (olasılık nüfusla artar). Somut botlar (oyuncunun haritası) burada değil, gerçekten savaşır (govde)."""
        if not self.izin('pvp'):
            return
        for m, s in list(self.haritada.items()):
            if m not in K.HARITALAR:
                continue                                 # kapı haritaları: her botun kendi kopyası
            canli = [b for b in s if b.olu_bitis <= now and b.govde is None and not b.yolda]
            if len(canli) < 2 or not K.pvp_haritasi(m, canli[0].firma) and len({b.firma for b in canli}) < 2:
                continue
            firmalar = {}
            for b in canli:
                firmalar.setdefault(b.firma, []).append(b)
            for a in canli:
                if a.olu_bitis > now:
                    continue
                av = a.hedef is not None and a.hedef.ad == 'pvp'
                ndusman = len(canli) - len(firmalar[a.firma])     # her bot için düşman listesi kurmak yerine sayı (büyük paketlerde O(n²))
                if not ndusman:
                    continue
                # X-1/X-2'de kendi firmasının haritasında başka firmaya saldırmak serbest; karşılaşma olasılığı
                p = (0.12 if av else 0.006 * a.o('saldirganlik')) * min(1.0, ndusman / 3.0)
                if a.r.random() >= p:
                    continue
                f = a.r.choice([f for f in firmalar if f != a.firma])
                hedef = a.r.choice(firmalar[f])
                if a.k.get('klan'):
                    from . import toplum as TP
                    savas = [h for h in firmalar[f] if TP.klan_iliskisi(a, h) == 3]
                    if savas:
                        hedef = a.r.choice(savas)        # klan savaşı: haritadaki düşman klanın üyesi önce
                if hedef.olu_bitis > now or a.k.get('klan') and TP.klan_iliskisi(a, hedef) in (1, 2):
                    continue
                oran = hedef.deger()['guc'] / max(0.5, a.deger()['guc'])
                if not av and oran > 0.9 + 0.6 * a.o('risk'):
                    continue                     # avda değilken güçlüye saldırmaz
                if oran > 1.6 + a.o('risk') + a.ruh['ofke']:
                    continue                     # avda bile çok güçlüye saldırmaz
                sonuc = S.karsilasma(a, hedef, self, now)
                if sonuc and sonuc[0] == 'kazandi' and sonuc[1].k.get('gorev'):
                    GV.ilerlet(sonuc[1], GV.KILL_PLAYERS, harita=sonuc[1].harita, y=self)

    # ------------------------------------------------------------ hızlı ilerletme
    def hizli(self, b, saniye, now, adim=900.0, pvp=False):
        """Botu saniye kadar oynamış gibi ilerletir (jumpstart, telafi): büyük adımlar, kararlar adım başına."""
        t = now - saniye
        b.cevrimici = True
        b.hedef = None
        while t < now:
            dt = min(adim, now - t)
            t += dt
            self.now = t
            b.olu_bitis = 0
            b.yolda = None
            B.karar(b, self, t)
            if b.hedef is not None:
                if b.yolda:
                    while b.yolda:
                        S.atla(b, b.yolda.pop(0), None)
                b.hedef.soyut(b, dt, self)
            if self.izin('magaza'):
                for _ in range(8):           # büyük adımda biriken parayı harcar (gerçek zamanda ayrı kararlar)
                    c = ALIS.aday(b)[0]
                    if c is None or not b.ode(c[1], c[2]):
                        break
                    b.ekle(c[3])
            b.ruh.d['yorgunluk'] = 0.0
        b.cevrimici = False
        b.hedef = None
        b.olu_bitis = 0
        self.now = now

    def jumpstart(self, botlar, now):
        """Yeni kadro gerçekçi bir dağılımla başlar: her bota lognormal "oynadığı saat" (çok acemi, çok orta, az güçlü), firma
        gücüyle çarpılır; bot o kadar oynamış gibi hızlı ilerletilir (donanımı, seviyesi, parası birbiriyle tutarlı)."""
        import math
        ort = max(1.0, float(self.ayar('jumpstart_saat', 60)))
        fg = self.ayar('firma_guc', [1, 1, 1])
        t0 = time.time()
        for b in botlar:
            saat = b.r.lognormvariate(math.log(ort) - 0.5, 1.0) * float(fg[b.firma - 1]) * (0.6 + 0.8 * b.o('hirs'))
            saat = min(saat, ort * 8)
            self.hizli(b, saat * 3600, now, adim=max(1800.0, saat * 3600 / 60))
        self.log('   botlar: jumpstart %d bot, %.1f sn' % (len(botlar), time.time() - t0))

    def telafi(self, saniye, now):
        """Oyuncu yokken geçen sürenin bir kısmı: çevrimiçi olma eğilimi kadar bot ilerler."""
        t0 = time.time()
        for b in self.botlar:
            if not b.kayitli:
                continue
            pay = sum(KS.ALISKANLIKLAR[b.k['kisilik']['aliskanlik']][1]) / 24.0 * self.ayar('cevrimici_oran', 0.6)
            s = saniye * pay * b.r.uniform(0.5, 1.5)
            if s > 300:
                self.hizli(b, s, now, adim=900.0)
        self.log('   botlar: çevrimdışı telafi %.0f dk, %.1f sn' % (saniye / 60, time.time() - t0))


def sunucu(yol, log=print):
    """Oyun sunucusu açılırken (game.main, DO_BOT): paketi okur, yöneticiyi arka planda kurar (jumpstart ve çevrimdışı telafi
    saniyeler sürebilir; oyun beklemez) ve çalıştırır. Paketin durumu paket dosyasının yanındaki <kimlik>/durum.json."""
    global AKTIF
    try:
        with open(yol, encoding='utf8') as f:
            paket = json.load(f)
    except (OSError, ValueError) as e:
        log('   botlar: paket okunamadı (%s): %s' % (yol, e))
        return

    def kur():
        global AKTIF
        kimlik = os.path.splitext(os.path.basename(yol))[0]
        durum = os.path.join(os.path.dirname(yol), kimlik, 'durum.json')
        t0 = time.time()
        y = Yonetici(paket, durum, log)
        import klan as KL
        import topluluk as TP
        from . import toplum
        if not KL.DOSYA:                                  # bot klanları kalıcı (arkadaş sunucusunda ortak klan dosyası zaten var)
            KL.configure(os.path.join(os.path.dirname(durum), 'klanlar.json'))
        toplum.kaydol(y, getattr(TP.OYUN, 'SOHBET', None))
        y.toplum = True
        if y.kip == 'gelismis':
            from . import llm, llm_saglayici, llm_sunucu
            if llm_saglayici.cok_dilli() or llm_sunucu.kurulum() is not None:   # kullanıcının sağlayıcısı ya da kurulu dahili model
                y.llm = llm.Beyin(y, log)                  # model arka planda açılır; hazır olana dek kalıplar
                y.llm.baslat()
            else:
                log('   botlar: Gelişmiş kip ama dil modeli kurulu değil (Botlar > Gelişmiş kip): Normal kip gibi sürüyor')
        AKTIF = y
        y.baslat()
        log('botlar: "%s" (%s, %d bot) %.1f sn' % (paket.get('ad', kimlik), paket.get('kip', 'normal'), len(y.botlar), time.time() - t0))

    threading.Thread(target=kur, name='botlar-kurulum', daemon=True).start()


def kapat():
    """Sunucu kapanıyor (game.stop_gracefully): durum kaydedilir."""
    if AKTIF is not None:
        AKTIF.durdur()
        if AKTIF.llm is not None:
            AKTIF.llm.durdur()
