"""Durum etkileri: bir varlığın (uzaylı ya da oyuncu) süreli etkileri. Gemi yetenekleri, ileride özel roketler, mayınlar, EMP ve
uzaylı yetenekleri bunları kullanır (world.py uygular).

Türler (değer anlamı):
  yavas        hız çarpanı düşüşü (0.3 = %30 yavaş); birden çoksa en güçlüsü
  donuk        kıpırdamaz ve ateş etmez
  isabet       isabet düşüşü (0.4 = %40 daha az isabet); toplanır, en çok 1
  kalkan_hasari kalkana giden hasar çarpanı (1.5 = kalkan emdiği payın 1,5 katı erir, gövde payı aynı; Diminisher Weaken Shields);
               birden çoksa en büyüğü
  hasar_bonus  bu varlığa verilen hasar bonusu (0.05 = +%5; Target Marker); toplanır
  dokunulmaz   hasar almaz
  hizlanma     hız en az bu değer (Speed Burst 1.800); oyuncuda ust_hiz
  zehir        saniyede bir gövdeye hasar: deger (vuruş), artis (her vuruşta artış), en_cok, kalan (toplam sınır), sonraki (zaman)
  hiz_siniri   hız en çok bu değer (Barb ve The Stinger'ın yavaşlatma küresi: 120); oyuncuda azami_hiz; birden çoksa en küçüğü
  zayiflik     oyuncunun lazer ve roket hasarı düşüşü (0.1 = %10; Emperor Sibelon'un DMG kapsülü); toplanır
  yetenek      oyuncuda gemi yeteneği biçiminde etki (ship_abilities.json 'etki': yansit, emme_can, mods); Mimesis Chest'in Revenge,
               Assimilate ve Flux'u (mimesis_chest.py); mods profil bonuslarına, ability(anahtar) hurt_hero'ya
Her etkinin kaynağı (ör. yeteneğin menü öğesi) vardır; kaynağa göre erken kaldırılabilir.
"""
import time


class Effects:
    def __init__(self):
        self.d = {}                   # tür -> [{bitis, deger, kaynak, ...}]

    def add(self, kind, sec, value=1.0, source=None, now=None, **extra):
        now = now or time.time()
        e = dict(extra, end_time=now + sec, value=value, source=source)
        self.d.setdefault(kind, []).append(e)
        return e

    def get(self, kind, now=None):
        """Süren etkiler (bitenler ayıklanır)."""
        now = now or time.time()
        lst = [e for e in self.d.get(kind, []) if now < e['end_time']]
        if lst:
            self.d[kind] = lst
        else:
            self.d.pop(kind, None)
        return lst

    def remove(self, kind=None, source=None):
        for k in ([kind] if kind else list(self.d)):
            self.d[k] = [e for e in self.d.get(k, []) if source is not None and e['source'] != source]
            if not self.d[k]:
                self.d.pop(k, None)

    def expired(self, now=None):
        """Biten türler (süresi dolan etkiler ayıklanır) -> tür kümesi; oyuncunun hızı gibi yeniden hesap gerektirenler için."""
        now = now or time.time()
        out = set()
        for k in list(self.d):
            if any(now >= e['end_time'] for e in self.d[k]):
                out.add(k)
                self.get(k, now)
        return out

    # ------------------------------------------------------------ birleşik değerler
    def slow(self, now=None):
        return max(max((e['value'] for e in self.get('slow', now)), default=0.0),
                   0.1 if self.get('infection', now) else 0.0)

    def frozen(self, now=None):
        return bool(self.get('frozen', now))

    def accuracy_loss(self, now=None):
        return min(1.0, sum(e['value'] for e in self.get('hit', now)))

    def shield_damage(self, now=None):
        return max((e['value'] for e in self.get('shield_damage_taken', now)), default=1.0)

    def damage_bonus(self, now=None):
        return sum(e['value'] for e in self.get('damage_bonus', now))

    def invulnerable(self, now=None):
        return bool(self.get('immune_until', now))

    def speed_cap(self, now=None):
        return min((e['value'] for e in self.get('speed_limit', now)), default=None)

    def ability(self, key, now=None):
        """Etkin 'yetenek' etkilerinin bir etkisi (yansit, emme_can …) -> değer ya da None (gemi_yetenek.effect'in sandık karşılığı)."""
        return next((e['value'][key] for e in self.get('skill', now) if key in e['value']), None)

    def speed_factor(self, now=None):
        return 0.0 if self.frozen(now) else 1.0 - self.slow(now)

    def poison_due(self, now=None):
        """Zamanı gelen zehir vuruşları -> [hasar]; vuruş sonrası bir sonraki zaman, artış ve kalan güncellenir."""
        now = now or time.time()
        hits = []
        for e in self.get('poison', now):
            if now < e.get('next', 0) or e.get('remaining', 1) <= 0:
                continue
            dmg = min(e['value'], e.get('remaining', e['value']))
            hits.append(dmg)
            e['remaining'] = e.get('remaining', dmg) - dmg
            e['value'] = min(e['value'] + e.get('increase', 0), e.get('max_count', e['value']))
            e['next'] = e.get('next', now) + 1.0
        return hits

    def mods(self, now=None):
        """Oyuncunun etkileri profil bonuslarına (profil.mods): yavaşlık hiz, donukluk sabit_hiz 0, isabet düşüşü."""
        out = {}
        if self.get('infection', now):
            out.update(laser=0.1, rocket=0.1, hp_multiplier=0.85)
        if self.slow(now):
            out['speed'] = -self.slow(now)
        if self.frozen(now):
            out['fixed_speed'] = 0
        if self.accuracy_loss(now):
            out['hit'] = -self.accuracy_loss(now)
        burst = max((e['value'] for e in self.get('speed_up', now)), default=0)
        if burst:
            out['floor_speed'] = burst
        cap = self.speed_cap(now)
        if cap is not None:
            out['max_speed'] = cap
        for e in self.get('skill', now):
            for k, v in e['value'].get('mods', {}).items():
                out[k] = out.get(k, 0) + v
        weak = sum(e['value'] for e in self.get('weakness', now))
        if weak:
            out['laser'] = out.get('laser', 0) - weak
            out['rocket'] = out.get('rocket', 0) - weak
        return out
