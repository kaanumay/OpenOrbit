"""Bot: bir pilotun kalıcı kaydı (paket durumu, durum.json'da sözlük) ve çalışırken gereken geçici alanları.

Kalıcı kayıt (k):
  no, ad, firma, kisilik            kadrodan (değişmez)
  uid                               sunucudaki kimliği (BOT_UID_TABAN + no)
  seviye, ep, kredi, uridyum, onur  ilerleme
  ekip                              katalog biçiminde donanım (sahip olunan her şey; donat yerleştirir)
  harita, x, y                      son konumu
  ruh, hafiza                       ruh hâli ve kişilere karşı ilişkiler (kisilik.RuhHali, kisilik.Hafiza)
  klan, arkadaslar                  klan kimliği ya da None; arkadaş adları (rehberin kopyası)
  istat                             npc, oyuncu, olum, gorev, sure_sn, harcama
  gorev                             süren görev {id, kosullar: {koşul: sayı}} ya da None; tamam: bitirdiği görevler
  hedef, niyet                      son hedefi (beyin) ve LLM'in eğilimi {hedef: pay, bitis}
"""
import random, time

import player_profile as PF
from . import catalog as K
from . import personality as PS
from . import game_settings as GS
from . import society as T

BOT_UID_BASE = 1800000000


class Bot:
    def __init__(self, k):
        self.k = k
        k.setdefault('uid', BOT_UID_BASE + int(k['no']))
        k.setdefault('seviye', 1)
        for a in ('ep', 'kredi', 'uridyum', 'onur'):
            k.setdefault(a, 0)
        k.setdefault('gear', K.new_gear())
        k.setdefault('harita', K.ev(k['firma']))
        k.setdefault('x', 0)
        k.setdefault('y', 0)
        k.setdefault('mood', {})
        k.setdefault('memory', {})
        k.setdefault('klan', None)
        k.setdefault('friends', [])
        k.setdefault('stats', {})
        if 'npc_points' not in k['stats']:       # eski kayıt: öldürmelerin türü yok; uzaylı başına sıradan uzaylıların ortalaması (3,7),
            k['stats']['npc_points'] = round(k['stats'].get('npc', 0) * 3.7)       # oyuncu gemisi başına kendi gemisinin puanı
            k['stats']['player_points'] = k['stats'].get('player', 0) * T.ship_rank_points(k['gear']['gemi'])
        k.setdefault('gorev', None)
        k.setdefault('tamam', [])
        k.setdefault('kargo', {})
        k.setdefault('stock', {'ammunition_laser_lcb-10': 1000, 'ammunition_rocket_r-310': 20})     # yeni oyuncunun cephanesi
        k.setdefault('hedef', None)
        k.setdefault('intent', None)
        if k.get('onur', 0) < 0 and not k.get('_honor_fix'):
            k['onur'] = 0              # eski kayıt: kargo kutusu cezasıyla eksiye düşen onur bir kez sıfırlanır (govde.calar_mi)
        k['_honor_fix'] = 1
        k['memory'].pop('', None)      # eski kayıt: saldıran bot gemisi adsız hatırlanıyordu (govde._ad)
        k['personality']['_name'] = k['ad']                     # saat dilimi ve zevk adından (kişilik kadrodan her açılışta yeniden gelir)
        self.mood = PS.Mood(k['mood'], k.get('mood_time'))
        self.memory = PS.Memory(k['memory'])
        self.r = random.Random('%s|%s|%s' % (k['ad'], k['no'], k['stats'].get('sure_sn', 0)))     # belirlenimci (benzetim)
        # geçici
        self.online = False
        self.session_end = 0.0
        self.next_login = 0.0         # çevrimdışıyken bir sonraki "girsem mi" anı
        self.next_decision = 0.0
        self.target = None                # beyin.Hedef örneği
        self.goal_start = 0.0
        self.plan = {}                   # hedefin kendi durumu (gidilen harita, hedef uzaylı ...)
        self.en_route = None                # [haritalar ...]: portal yolunda (soyut atlama)
        self.en_route_time = 0.0               # sıradaki atlamanın anı
        self.dead_until = 0.0             # öldü: bu ana dek doğmadı (üste dönüyor)
        self.body = None                # somut gemi (govde.BotGemi) ya da None
        self.last_abstract = time.time()
        self._value = None               # degerler() önbelleği (ekip değişince sıfırlanır)
        self._candidates = None             # alisveris.adaylar() önbelleği
        self.events = []                # gelen olaylar (sohbet, davet, saldırı ...): beyin ve LLM okur
        self.pending = []               # yanıt bekleyen davetler [(tür, kimlik, ad, an)] (toplum.davetler)
        self.session = None               # çevrimiçiyken toplum.BotOturum
        self.profile = None               # topluluk için Profil (toplum.py)
        self.permission = {}                   # paketin erişim ayarları (yonetici bağlar)
        self.hour = time.time            # olayların saati (yonetici benzetimin saatini bağlar)
        self.game_settings = GS.STANDARD             # paketin oyun ayarı profili (yonetici bağlar; oyuncunun ayarlarından ayrı)

    # ------------------------------------------------------------ kısayollar
    @property
    def name(self):
        return self.k['ad']

    @property
    def uid(self):
        return self.k['uid']

    @property
    def saved(self):
        """Sunucuya kayıt oldu mu (progressive'de pilotlar sırayla katılır; eski kayıtlarda alan yok: kayıtlı)."""
        return self.k.get('registered', True)

    @property
    def firma(self):
        return self.k['firma']

    @property
    def level(self):
        return self.k['seviye']

    @property
    def game_map(self):
        return self.k['harita']

    @property
    def traits(self):
        return self.k['personality']['traits']

    @property
    def archetype(self):
        return self.k['personality']['archetype']

    def o(self, name):
        return self.k['personality']['traits'][name]

    def ist(self, name, n=1):
        self.k['stats'][name] = self.k['stats'].get(name, 0) + n

    def shield_share(self):
        """Jeneratör yuvalarının kalkana ayrılan payı: temkinli kalkan, avcı hız sever; klan emri (klan_emir: tam kalkan, tam hız,
        dengeli) önce gelir."""
        if self.k.get('structure'):
            from .clan_orders import LAYOUT_SHARE
            return LAYOUT_SHARE.get(self.k['structure'], 0.6)
        return PS.clamp(0.85 - 0.45 * self.o('risk') * self.o('aggression') - 0.15 * (self.archetype == 'hunter'), 0.3, 0.95)

    def clan_savings(self):
        """Klan kuracak lider kişilikli bot (klansız, 4+ seviye) kuruluş bedelini kenara ayırır: alışveriş ve açık artırma bu
        krediye dokunmaz. Önceden 8 saatte bile hiçbir bot klan kuramıyordu (para hep başka şeye gidiyordu)."""
        if (self.archetype != 'lider' or self.k.get('klan') is not None or self.level < 4 or not self.permission.get('klan', True)
                or not self.permission.get('clan_found', True)):
            return 0
        import clan as KL
        return KL.FOUNDING_COST * 1.3

    def value(self):
        """Savaş değerleri; etkin boosterlar (hasar, can, kalkan) üstüne eklenir (süreleri dolunca kendiliğinden düşer)."""
        d = self._base_value()
        from . import loot as LT
        dmg, hp, shd = LT.booster_share(self, 'DAMAGE'), LT.booster_share(self, 'HITPOINTS'), LT.booster_share(self, 'SHIELD')
        if dmg or hp or shd:
            d = dict(d, dps=d['dps'] * (1 + dmg), can=d['can'] * (1 + hp), kalkan=d['kalkan'] * (1 + shd),
                     ehp=d['ehp'] * (1 + 0.5 * hp + 0.5 * shd))
        return d

    def _base_value(self):
        """Savaş değerleri; dps ve ehp uzaylılara karşı: profilin uzaylı canı ve hasarı çarpanıyla (zor profilde aynı gemi daha
        yavaş öldürür, daha çok hasar alır). guc donanımın kendisi (karşılaştırma, panel)."""
        if self._value is None:
            d = K.values(self.k['gear'], self.shield_share())
            d['dps'] /= max(0.1, self.game_settings.multiplier('npc_can', 'harita'))
            d['ehp'] /= max(0.1, self.game_settings.multiplier('npc_damage', 'harita'))
            self._value = d
        return self._value

    def loadout_changed(self):
        self._value = self._candidates = None
        if self.body is not None:
            self.body.refresh()

    # ------------------------------------------------------------ ilerleme
    def earn(self, ep=0, kredi=0, uridyum=0, onur=0):
        """Kazanç (ya da kayıp); seviye EP tablosundan (profil.level_for). -> yeni seviyeye çıktı mı."""
        k = self.k
        # küsurat birikir: soyut benzetimin 5 sn'lik adımları uridyumu 0,4 gibi parçalarla verir, kesilince hiç birikmiyordu
        fractions = self.__dict__.setdefault('_fraction', {})
        full = {}
        for a, v in (('ep', ep), ('kredi', kredi), ('uridyum', uridyum), ('onur', onur)):
            v = v + fractions.get(a, 0.0)
            full[a] = int(v)
            fractions[a] = v - full[a]
        k['ep'] += full['ep']
        if full['kredi'] > 0 and full['ep'] > 0 and k.get('klan'):
            self._clan_income = self.__dict__.get('_clan_income', 0) + full['kredi']   # uzaylı/görev kazancı: klan vergisi (toplum)
        k['kredi'] = max(0, k['kredi'] + full['kredi'])
        k['uridyum'] = max(0, k['uridyum'] + full['uridyum'])
        k['onur'] += full['onur']
        lv = PF.level_for(k['ep'])
        if lv != k['seviye']:
            leveled_up = lv > k['seviye']
            k['seviye'] = lv
            if leveled_up:
                self.mood.it(morale=0.2, confidence=0.05)
                self.event('seviye', seviye=lv)
            return leveled_up
        return False

    def reward(self, kaynak, hiz=1.0, **earnings):
        """Oyunun ödülü (kaynak: npc, gorev, kutu ya da None): paketin hızı, oyun ayarı profili ve EP/onur boosterlarıyla çarpılır."""
        from . import loot as LT
        bst = {'ep': 1 + LT.booster_share(self, 'EXPERIENCE_POINTS'), 'onur': 1 + LT.booster_share(self, 'HONOUR_POINTS')}
        return self.earn(**{k: v * hiz * self.game_settings.multiplier(k, kaynak) * bst.get(k, 1.0) for k, v in earnings.items()})

    def pay(self, currency, amount):
        """'C' | 'U' ile öde -> ödendi mi."""
        a = 'kredi' if currency == 'C' else 'uridyum'
        if self.k[a] < amount:
            return False
        self.k[a] -= int(amount)
        self.ist('spend_' + a, int(amount))
        return True

    def add(self, loot, n=1):
        """Satın alınan ya da kazanılan eşya donanıma (gemi: aktif gemi olur)."""
        e = self.k['gear']
        if loot.startswith('ship_'):
            if not (K.ITEMS['ships'].get(loot) or {}).get('hp'):
                return False                             # yalnız görünüm olan tasarım: gemi değil
            e['gemi'] = loot
        elif loot in K.ITEMS['lasers']:
            e['lazer'][loot] = e['lazer'].get(loot, 0) + n
        elif loot in K.ITEMS['shield_generators']:
            e['kalkan'][loot] = e['kalkan'].get(loot, 0) + n
        elif loot in K.ITEMS['speed_generators']:
            e['hiz'][loot] = e['hiz'].get(loot, 0) + n
        elif loot in K.ITEMS['drones']:
            e['drone'][loot] = e['drone'].get(loot, 0) + n
        elif loot in K.ITEMS['combat_items']['launcher']['kinds']:
            e['launcher'] = loot                       # roket fırlatıcısı (teknoloji.py)
        elif loot in K.ITEMS['extras'] or loot in K.ITEMS['repair_robots']:
            from . import extras as EX
            EX.equip(self, loot)                          # CPU ve onarım robotu ekstra yuvasına (ekstra.py)
            return True
        elif loot in K.ITEMS['laser_ammo'] or loot in K.ITEMS['rockets'] or loot in K.ITEMS['combat_items']['launcher_ammo'] \
                or loot.startswith('tech_') or loot.startswith('ammunition_'):
            from . import weapons as WP
            WP.add(self, loot, n)                      # cephane ve roket stoğa (silah.py)
            return True
        else:
            return False
        self.loadout_changed()
        return True

    # ------------------------------------------------------------ kargo
    def cargo_fill(self):
        """Kargonun doluluğu (0..1): yer kaplayan cevherler / geminin kargo alanı."""
        k = self.k.get('kargo') or {}
        return sum(v for t, v in k.items() if int(t) in K.CARGO_ORE) / max(1, K.cargo_capacity(self.k['gear']))

    def add_cargo(self, contents):
        """Cevherleri sığdığı kadar kargoya alır -> alınanlar {tür: adet}."""
        cargo = self.k.setdefault('kargo', {})
        empty = K.cargo_capacity(self.k['gear']) - sum(v for t, v in cargo.items() if int(t) in K.CARGO_ORE)
        claimed = {}
        for t, v in sorted(contents.items(), key=lambda x: -K.ore_prices(0).get(int(x[0]), 0)):   # değerliler önce
            n = int(v) if int(t) not in K.CARGO_ORE else max(0, min(int(v), empty))
            if n > 0:
                cargo[str(t)] = cargo.get(str(t), 0) + n
                claimed[int(t)] = n
                if int(t) in K.CARGO_ORE:
                    empty -= n
        return claimed

    def sell_cargo(self):
        """İstasyonda kargonun satılabilir cevherlerini satar (onura bağlı fiyat, profilin cevher fiyatı çarpanı) -> kazanılan kredi.
        Önce laboratuvar: yükseltmeyi seven bot arıtıp lazerine, kalkanına, roketine yükler (lab.py); kalanı satılır."""
        from . import lab as LB, weapons as WP, skylab as SK
        SK.carry(self, self.hour(), K.cargo_capacity(self.k['gear']) * 3)      # Skylab'dan gelen cevher (taşıma hakkı kadar)
        LB.decision(self, WP.hourly_ammo(self))
        price = K.ore_prices(self.k['onur'], self.game_settings.multiplier('ore_price'))
        cargo = self.k.setdefault('kargo', {})
        kredi = 0
        for t in list(cargo):
            if int(t) in price:
                kredi += price[int(t)] * cargo.pop(t)
            elif int(t) in K.CARGO_ORE:              # rafineride satılmayan (Palladium: 5-2'deki tüccarda kapı enerjisine) depoya
                from . import weapons as WP
                name = K.ITEMS['ores']['kinds'].get(str(t), 'resource_ore_%s' % t)
                WP.stock(self)[name] = WP.stock(self).get(name, 0) + cargo.pop(t)
        if kredi:
            self.earn(kredi=kredi)
            self.ist('ore_credits', kredi)
            self.event('sold_ore', kredi=kredi)
        return kredi

    def event(self, kind, now=None, **f):
        """Olay kuyruğu (en çok 30): beyin ve LLM bağlamı için."""
        self.events.append(dict(tur=kind, t=now or self.hour(), **f))
        del self.events[:-30]

    def save(self):
        self.k['mood'] = self.mood.save()
        self.k['mood_time'] = self.mood.t
        return self.k

    def summary(self):
        """Panel ve LLM için kısa durum."""
        d = self.value()
        return dict(no=self.k['no'], ad=self.name, firma=self.firma, archetype=self.archetype, seviye=self.level, ep=self.k['ep'],
                    kredi=self.k['kredi'], uridyum=self.k['uridyum'], onur=self.k['onur'], gemi=self.k['gear']['gemi'],
                    power=round(d['power'], 1), harita=K.H.name(self.game_map), online=self.online, klan=self.k['klan'],
                    hedef=self.k['hedef'], concrete=self.body is not None, stats=dict(self.k['stats']), registered=self.saved,
                    kargo=round(self.cargo_fill(), 2))
