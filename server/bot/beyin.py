"""Karar motoru (fayda yapay zekâsı): bot her karar anında uygun hedefleri puanlar ve birini seçer.

Hedef modülleri bot/hedefler/ altında, her biri @hedef ile kaydolur (yeni içerik = yeni modül; beyin değişmez). Bir hedef:
  uygun(bot, b)   bu bağlamda seçilebilir mi
  puan(bot, b)    0..~1: kişilik, ruh hâli ve bağlamdan
  basla(bot, b)   seçilince planını kurar (bot.plan)
  soyut(bot, dt, y)       oyuncunun haritasında değilken etkisi (istatistiksel)
  somut(bot, g, w, now)   oyuncunun haritasındayken gemisini yönetir (govde.py; yoksa varsayılan dolaşma/avlanma)
  bitti(bot, b)   hedef tamamlandı mı (yeni karar erkenden)

Seçim: puan x ruh hâli etkisi + bağlılık payı (süren hedef, en_az_sn dolana dek güçlü) + niyet payı (LLM ya da araç) ->
softmax (sıcaklık sabırsızlıkla artar: dürtüsel botlar daha değişken). İnsan gibi davranmak için puanlara küçük gürültü eklenir ve
karar aralıkları düzensizdir.
"""
import time

from . import katalog as K
from . import kisilik as KS

HEDEFLER = {}            # ad -> Hedef örneği


def hedef(cls):
    """Hedef sınıfını kaydeder (modül içe aktarılınca)."""
    HEDEFLER[cls.ad] = cls()
    return cls


class Hedef:
    ad = ''
    izin = None          # paketin erişim ayarı (kapalıysa hiç seçilmez): 'pvp', 'gorev', 'magaza', 'klan', ...
    kipler = ('normal', 'gelismis')     # hangi bot kiplerinde (basit.py'nin hedefi yalnız 'basit')
    en_az_sn = 60        # seçilince en az bu kadar sürer (iç bağlılık)
    acil = False         # bağlılığı bozabilir (kaçış, ölüm sonrası)

    def uygun(self, bot, b):
        return True

    def puan(self, bot, b):
        return 0.0

    def basla(self, bot, b):
        pass

    def soyut(self, bot, dt, y):
        pass

    def somut(self, bot, g, w, now):
        return False                # False: govde varsayılan davranışı

    def bitti(self, bot, b):
        return False

    def __repr__(self):
        return '<Hedef %s>' % self.ad


class Baglam:
    """Karar anının bir kez hesaplanan bilgileri (her hedef aynısını okur). Ağır işler tembel (ilk istenince)."""

    def __init__(self, bot, y, now=None):
        self.bot, self.y = bot, y
        self.now = now or time.time()
        self.deger = bot.deger()
        self._harita = None
        self._alis = None

    @property
    def harita(self):
        """Kasılacak harita adayları [(fayda, harita, değerlendirme)] (iyiden kötüye)."""
        if self._harita is None:
            self._harita = harita_adaylari(self.bot, self.deger, self.y)
        return self._harita

    @property
    def alisveris(self):
        """(alınabilecek en iyi eşya, biriktirilen hedef) -> alisveris.aday()."""
        if self._alis is None:
            from .hedefler import alisveris
            self._alis = alisveris.aday(self.bot)
        return self._alis

    def ayar(self, ad, vars=None):
        return self.y.ayar(ad, vars) if self.y is not None else vars


def harita_adaylari(bot, deger, y=None):
    """Girebildiği haritalar kasılma faydasına göre. Fayda: kişiliğin istediği kazanç (EP / kredi / uridyum) - ölüm riski x temkin
    - yol maliyeti; avcı ve riskçi başka firmanın haritalarını, temkinli kendi firmasınınkini sever. Paketin harita sınırı (en
    yüksek harita sınıfı) ve firmalar arası geçiş ayarı uyulur."""
    o = bot.ozellik
    cesaret = KS.sinirla(0.3 + 0.6 * o['risk'] + 0.2 * bot.ruh['ozguven'] - 0.3)
    yabanci = y.ayar('yabanci_harita', True) if y is not None else True
    out = []
    lv, firma = bot.seviye, bot.firma
    for m in K.HARITALAR:
        if not K.girebilir(m, firma, lv):
            continue
        sahip = K.H.company(m)
        if sahip and sahip != firma and not yabanci:
            continue
        r = K.harita_degerlendir(m, deger['dps'], deger['ehp'], cesaret)
        if not r['hedefler']:
            continue
        kazanc = (r['saat_ep'] * (0.6 + o['hirs']) / 10.0 + r['saat_kredi'] * (0.5 + o['tutumluluk']) / 10.0
                  + r['saat_uridyum'] * 25.0 + r['saat_onur'] * 5.0)
        risk = r['olum_saat'] * (1.6 - o['risk']) * 0.35
        yol = K.yol(bot.harita, m, firma, lv)
        if yol is None:
            continue
        atlama = len(yol) - 1
        pvp = K.pvp_haritasi(m, firma)
        tercih = 1.0 + (0.25 * (o['saldirganlik'] - 0.5) if pvp else 0.1) + (0.15 if m == bot.harita else 0)
        if sahip and sahip != firma:
            tercih -= 0.35 * (1 - o['risk'])
        # kalabalık: haritadaki botlar aynı uzaylıları paylaşır (gerçek oyuncular boş haritaya kayar; başlangıç haritalarına yığılma)
        kalabalik = len(y.haritada.get(m, ())) - (1 if m == bot.harita else 0) if y is not None else 0
        fayda = (kazanc / 1000.0) * tercih * (1 - min(0.9, risk)) / (1 + 0.04 * max(0, kalabalik)) - atlama * 0.03 * (1.2 - o['sabir'])
        out.append((fayda, m, r))
    out.sort(key=lambda x: -x[0])
    return out


def karar(bot, y, now=None):
    """Botun yeni hedefi (değişmediyse aynısı). Süren hedefin bağlılığı ve LLM niyeti hesaba katılır."""
    now = now or time.time()
    from . import silah as SL, skylab as SK, gorunum as GR
    SL.ikmal(bot)                                   # cephane ve roket azaldıysa alır (oyuncu gibi, iş arasında)
    SK.yatirim(bot, now)
    GR.alisveris(bot, now)                          # gemi tasarımı ve dron formasyonu (gösterişe ve parasına göre)                            # Skylab'ı yükseltir (parası ve kaynağı yetiyorsa)
    from . import teknoloji as TK
    TK.uret(bot)                                    # Assembly: teknoloji eşyaları
    TK.ikmal(bot)                                   # fırlatıcı roketi
    from . import ganimet as GB, kapi as KP
    GB.assembly(bot)                                # Assembly: malzemesi olan en değerli tarif (anahtar, eşya …)
    KP.uretici(bot)                                 # Galaksi Kapısı üreticisi: enerjisi (ya da uridyumu) varsa çekiliş
    from . import modlar as MD
    MD.pasif(bot, now)                              # Dispatch, Galaxy Trek
    b = Baglam(bot, y, now)
    simdiki = bot.hedef
    ruh = bot.ruh
    ruh.guncelle(now)
    niyet = bot.k.get('niyet')
    if niyet and niyet.get('bitis', 0) < now:
        niyet = bot.k['niyet'] = None
    sure = now - bot.hedef_bas
    kosu = simdiki is not None and simdiki.ad in ('kapi', 'mod') and not bot.plan.get('bitti')   # niyet koşuyu bölmesin: oradan yol yok
    if simdiki is not None and not simdiki.bitti(bot, b) and (kosu or sure < simdiki.en_az_sn and not niyet):
        acil = [h for h in HEDEFLER.values() if h.acil and h is not simdiki and izinli(h, y) and h.uygun(bot, b)]
        if not acil:
            return simdiki
    adaylar = []
    for h in HEDEFLER.values():
        if not izinli(h, y) or not h.uygun(bot, b):
            continue
        p = h.puan(bot, b)
        if h is simdiki and not h.bitti(bot, b):
            # bağlılık: insan bir işi yarıda bırakmaz; sıkıldıkça (aynı iş uzadıkça) azalır
            p += 0.25 * max(0.0, 1 - ruh['sikilma']) + (0.3 if sure < h.en_az_sn else 0)
        if niyet and niyet.get('hedef') == h.ad:
            p += niyet.get('pay', 0.6)
        p *= 1 + bot.r.uniform(-0.08, 0.08)
        adaylar.append((h, p))
    if not adaylar:
        return simdiki
    sicaklik = 0.05 + 0.12 * (1 - bot.o('sabir'))
    sec = KS.softmax_sec(adaylar, sicaklik, bot.r)
    if sec is not simdiki or sec.bitti(bot, b):
        # biten hedef yeniden seçilince yeniden başlar: önceden yalnız sıkılma artıyordu, alışverişi biten bot hep "alışverişte"
        # kalıp bir daha hiçbir şey almıyordu (oyuncu bildirimi 2026-10-31: milyonlarca uridyumla yükseltme almıyorlardı)
        if simdiki is not None and sec is not simdiki:
            ruh.it(sikilma=-0.35)
        bot.hedef, bot.hedef_bas, bot.plan = sec, now, {}
        bot.k['hedef'] = sec.ad
        sec.basla(bot, b)
    else:
        ruh.it(sikilma=0.04 * (1.3 - bot.o('sabir')))
    return sec


def izinli(h, y):
    if y is None:
        return 'normal' in h.kipler
    return y.kip in h.kipler and (h.izin is None or y.izin(h.izin))


def zorla(bot, ad, plan=None, pay=1.0, sure=600, now=None):
    """Araç ya da LLM bir hedefi istedi: niyet olarak eklenir (sonraki kararda güçlü pay) ve hemen karar verilir."""
    now = now or time.time()
    bot.k['niyet'] = dict(hedef=ad, pay=pay, bitis=now + sure, plan=plan or {})
    bot.sonraki_karar = now


def sonraki_karar_araligi(bot):
    """İki karar arası (sn): sabırsız ve dürtüsel botlar sık, sabırlılar seyrek düşünür."""
    return bot.r.uniform(8, 22) * (0.6 + bot.o('sabir'))


# hedef modülleri (kaydolsunlar diye)
from .hedefler import yukle as _yukle  # noqa: E402
_yukle()
