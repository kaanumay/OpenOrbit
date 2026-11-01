"""Karar motoru (fayda yapay zekâsı): bot her karar anında uygun hedefleri puanlar ve birini seçer.

Hedef modülleri bot/goals/ altında, her biri @hedef ile kaydolur (yeni içerik = yeni modül; beyin değişmez). Bir hedef:
  uygun(bot, b)   bu bağlamda seçilebilir mi
  puan(bot, b)    0..~1: kişilik, ruh hâli ve bağlamdan
  basla(bot, b)   seçilince planını kurar (bot.plan)
  soyut(bot, dt, y)       oyuncunun haritasında değilken etkisi (istatistiksel)
  somut(bot, g, w, now)   oyuncunun haritasındayken gemisini yönetir (ship.py; yoksa varsayılan dolaşma/avlanma)
  bitti(bot, b)   hedef tamamlandı mı (yeni karar erkenden)

Seçim: puan x ruh hâli etkisi + bağlılık payı (süren hedef, en_az_sn dolana dek güçlü) + niyet payı (LLM ya da araç) ->
softmax (sıcaklık sabırsızlıkla artar: dürtüsel botlar daha değişken). İnsan gibi davranmak için puanlara küçük gürültü eklenir ve
karar aralıkları düzensizdir.
"""
import time

from . import catalog as K
from . import personality as PS

GOALS = {}            # ad -> Hedef örneği


def target(cls):
    """Hedef sınıfını kaydeder (modül içe aktarılınca)."""
    GOALS[cls.name] = cls()
    return cls


class Goal:
    name = ''
    permission = None          # paketin erişim ayarı (kapalıysa hiç seçilmez): 'pvp', 'gorev', 'magaza', 'klan', ...
    bot_modes = ('normal', 'advanced')     # hangi bot kiplerinde (basit.py'nin hedefi yalnız 'basit')
    min_sec = 60        # seçilince en az bu kadar sürer (iç bağlılık)
    urgent = False         # bağlılığı bozabilir (kaçış, ölüm sonrası)

    def eligible(self, bot, b):
        return True

    def points(self, bot, b):
        return 0.0

    def start(self, bot, b):
        pass

    def abstract(self, bot, dt, y):
        pass

    def concrete(self, bot, g, w, now):
        return False                # False: govde varsayılan davranışı

    def finished(self, bot, b):
        return False

    def __repr__(self):
        return '<Hedef %s>' % self.name


class Context:
    """Karar anının bir kez hesaplanan bilgileri (her hedef aynısını okur). Ağır işler tembel (ilk istenince)."""

    def __init__(self, bot, y, now=None):
        self.bot, self.y = bot, y
        self.now = now or time.time()
        self.value = bot.value()
        self._game_map = None
        self._shopping = None

    @property
    def game_map(self):
        """Kasılacak harita adayları [(fayda, harita, değerlendirme)] (iyiden kötüye)."""
        if self._game_map is None:
            self._game_map = map_candidates(self.bot, self.value, self.y)
        return self._game_map

    @property
    def shopping(self):
        """(alınabilecek en iyi eşya, biriktirilen hedef) -> alisveris.aday()."""
        if self._shopping is None:
            from .goals import shopping
            self._shopping = shopping.candidate(self.bot)
        return self._shopping

    def setting(self, name, vars=None):
        return self.y.setting(name, vars) if self.y is not None else vars


def map_candidates(bot, value, y=None):
    """Girebildiği haritalar kasılma faydasına göre. Fayda: kişiliğin istediği kazanç (EP / kredi / uridyum) - ölüm riski x temkin
    - yol maliyeti; avcı ve riskçi başka firmanın haritalarını, temkinli kendi firmasınınkini sever. Paketin harita sınırı (en
    yüksek harita sınıfı) ve firmalar arası geçiş ayarı uyulur."""
    o = bot.traits
    courage = PS.clamp(0.3 + 0.6 * o['risk'] + 0.2 * bot.mood['confidence'] - 0.3)
    foreign = y.setting('foreign_map', True) if y is not None else True
    out = []
    lv, firma = bot.level, bot.firma
    for m in K.MAPS:
        if not K.can_enter(m, firma, lv):
            continue
        owner = K.H.company(m)
        if owner and owner != firma and not foreign:
            continue
        r = K.evaluate_map(m, value['dps'], value['ehp'], courage)
        if not r['targets']:
            continue
        earnings = (r['ep_per_hour'] * (0.6 + o['ambition']) / 10.0 + r['credits_per_hour'] * (0.5 + o['frugality']) / 10.0
                  + r['uridium_per_hour'] * 25.0 + r['honor_per_hour'] * 5.0)
        risk = r['deaths_per_hour'] * (1.6 - o['risk']) * 0.35
        route = K.route(bot.game_map, m, firma, lv)
        if route is None:
            continue
        jump = len(route) - 1
        pvp = K.pvp_map(m, firma)
        preference = 1.0 + (0.25 * (o['aggression'] - 0.5) if pvp else 0.1) + (0.15 if m == bot.game_map else 0)
        if owner and owner != firma:
            preference -= 0.35 * (1 - o['risk'])
        # kalabalık: haritadaki botlar aynı uzaylıları paylaşır (gerçek oyuncular boş haritaya kayar; başlangıç haritalarına yığılma)
        crowd = len(y.on_map.get(m, ())) - (1 if m == bot.game_map else 0) if y is not None else 0
        utility = (earnings / 1000.0) * preference * (1 - min(0.9, risk)) / (1 + 0.04 * max(0, crowd)) - jump * 0.03 * (1.2 - o['patience'])
        out.append((utility, m, r))
    out.sort(key=lambda x: -x[0])
    return out


def decision(bot, y, now=None):
    """Botun yeni hedefi (değişmediyse aynısı). Süren hedefin bağlılığı ve LLM niyeti hesaba katılır."""
    now = now or time.time()
    from . import weapons as WP, skylab as SK, appearance as GR
    WP.resupply(bot)                                   # cephane ve roket azaldıysa alır (oyuncu gibi, iş arasında)
    SK.invest(bot, now)
    GR.shopping(bot, now)                          # gemi tasarımı ve dron formasyonu (gösterişe ve parasına göre)                            # Skylab'ı yükseltir (parası ve kaynağı yetiyorsa)
    from . import technology as TECH
    TECH.produce(bot)                                    # Assembly: teknoloji eşyaları
    TECH.resupply(bot)                                   # fırlatıcı roketi
    from . import loot as LT, galaxy_gates as GT
    LT.assembly(bot)                                # Assembly: malzemesi olan en değerli tarif (anahtar, eşya …)
    GT.generator(bot)                                 # Galaksi Kapısı üreticisi: enerjisi (ya da uridyumu) varsa çekiliş
    from . import modes as MD
    MD.passive(bot, now)                              # Dispatch, Galaxy Trek
    b = Context(bot, y, now)
    current = bot.target
    mood = bot.mood
    mood.update(now)
    intent = bot.k.get('intent')
    if intent and intent.get('end_time', 0) < now:
        intent = bot.k['intent'] = None
    duration = now - bot.goal_start
    run = current is not None and current.name in ('gate', 'mod') and not bot.plan.get('finished')   # niyet koşuyu bölmesin: oradan yol yok
    if current is not None and not current.finished(bot, b) and (run or duration < current.min_sec and not intent):
        urgent = [h for h in GOALS.values() if h.urgent and h is not current and allowed(h, y) and h.eligible(bot, b)]
        if not urgent:
            return current
    candidates = []
    for h in GOALS.values():
        if not allowed(h, y) or not h.eligible(bot, b):
            continue
        p = h.points(bot, b)
        if h is current and not h.finished(bot, b):
            # bağlılık: insan bir işi yarıda bırakmaz; sıkıldıkça (aynı iş uzadıkça) azalır
            p += 0.25 * max(0.0, 1 - mood['boredom']) + (0.3 if duration < h.min_sec else 0)
        if intent and intent.get('target') == h.name:
            p += intent.get('pay', 0.6)
        p *= 1 + bot.r.uniform(-0.08, 0.08)
        candidates.append((h, p))
    if not candidates:
        return current
    temperature = 0.05 + 0.12 * (1 - bot.o('patience'))
    sec = PS.softmax_pick(candidates, temperature, bot.r)
    if sec is not current or sec.finished(bot, b):
        # biten hedef yeniden seçilince yeniden başlar: önceden yalnız sıkılma artıyordu, alışverişi biten bot hep "alışverişte"
        # kalıp bir daha hiçbir şey almıyordu (oyuncu bildirimi 2026-10-31: milyonlarca uridyumla yükseltme almıyorlardı)
        if current is not None and sec is not current:
            mood.it(boredom=-0.35)
        bot.target, bot.goal_start, bot.plan = sec, now, {}
        bot.k['target'] = sec.name
        sec.start(bot, b)
    else:
        mood.it(boredom=0.04 * (1.3 - bot.o('patience')))
    return sec


def allowed(h, y):
    if y is None:
        return 'normal' in h.bot_modes
    return y.mode in h.bot_modes and (h.permission is None or y.permission(h.permission))


def force(bot, name, plan=None, pay=1.0, duration=600, now=None):
    """Araç ya da LLM bir hedefi istedi: niyet olarak eklenir (sonraki kararda güçlü pay) ve hemen karar verilir."""
    now = now or time.time()
    bot.k['intent'] = dict(target=name, pay=pay, end_time=now + duration, plan=plan or {})
    bot.next_decision = now


def next_decision_interval(bot):
    """İki karar arası (sn): sabırsız ve dürtüsel botlar sık, sabırlılar seyrek düşünür."""
    return bot.r.uniform(8, 22) * (0.6 + bot.o('patience'))


# hedef modülleri (kaydolsunlar diye)
from .goals import load as _load  # noqa: E402
_load()
