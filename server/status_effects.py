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
        e = dict(extra, bitis=now + sec, deger=value, kaynak=source)
        self.d.setdefault(kind, []).append(e)
        return e

    def get(self, kind, now=None):
        """Süren etkiler (bitenler ayıklanır)."""
        now = now or time.time()
        lst = [e for e in self.d.get(kind, []) if now < e['bitis']]
        if lst:
            self.d[kind] = lst
        else:
            self.d.pop(kind, None)
        return lst

    def remove(self, kind=None, source=None):
        for k in ([kind] if kind else list(self.d)):
            self.d[k] = [e for e in self.d.get(k, []) if source is not None and e['kaynak'] != source]
            if not self.d[k]:
                self.d.pop(k, None)

    def expired(self, now=None):
        """Biten türler (süresi dolan etkiler ayıklanır) -> tür kümesi; oyuncunun hızı gibi yeniden hesap gerektirenler için."""
        now = now or time.time()
        out = set()
        for k in list(self.d):
            if any(now >= e['bitis'] for e in self.d[k]):
                out.add(k)
                self.get(k, now)
        return out

    # ------------------------------------------------------------ birleşik değerler
    def slow(self, now=None):
        return max(max((e['deger'] for e in self.get('yavas', now)), default=0.0),
                   0.1 if self.get('enfeksiyon', now) else 0.0)

    def frozen(self, now=None):
        return bool(self.get('donuk', now))

    def accuracy_loss(self, now=None):
        return min(1.0, sum(e['deger'] for e in self.get('isabet', now)))

    def shield_damage(self, now=None):
        return max((e['deger'] for e in self.get('kalkan_hasari', now)), default=1.0)

    def damage_bonus(self, now=None):
        return sum(e['deger'] for e in self.get('hasar_bonus', now))

    def invulnerable(self, now=None):
        return bool(self.get('dokunulmaz', now))

    def speed_cap(self, now=None):
        return min((e['deger'] for e in self.get('hiz_siniri', now)), default=None)

    def ability(self, key, now=None):
        """Etkin 'yetenek' etkilerinin bir etkisi (yansit, emme_can …) -> değer ya da None (gemi_yetenek.effect'in sandık karşılığı)."""
        return next((e['deger'][key] for e in self.get('yetenek', now) if key in e['deger']), None)

    def speed_factor(self, now=None):
        return 0.0 if self.frozen(now) else 1.0 - self.slow(now)

    def poison_due(self, now=None):
        """Zamanı gelen zehir vuruşları -> [hasar]; vuruş sonrası bir sonraki zaman, artış ve kalan güncellenir."""
        now = now or time.time()
        hits = []
        for e in self.get('zehir', now):
            if now < e.get('next', 0) or e.get('kalan', 1) <= 0:
                continue
            dmg = min(e['deger'], e.get('kalan', e['deger']))
            hits.append(dmg)
            e['kalan'] = e.get('kalan', dmg) - dmg
            e['deger'] = min(e['deger'] + e.get('increase', 0), e.get('en_cok', e['deger']))
            e['next'] = e.get('next', now) + 1.0
        return hits

    def mods(self, now=None):
        """Oyuncunun etkileri profil bonuslarına (profil.mods): yavaşlık hiz, donukluk sabit_hiz 0, isabet düşüşü."""
        out = {}
        if self.get('enfeksiyon', now):
            out.update(lazer=0.1, roket=0.1, hp_multiplier=0.85)
        if self.slow(now):
            out['hiz'] = -self.slow(now)
        if self.frozen(now):
            out['sabit_hiz'] = 0
        if self.accuracy_loss(now):
            out['isabet'] = -self.accuracy_loss(now)
        burst = max((e['deger'] for e in self.get('hizlanma', now)), default=0)
        if burst:
            out['floor_speed'] = burst
        cap = self.speed_cap(now)
        if cap is not None:
            out['azami_hiz'] = cap
        for e in self.get('yetenek', now):
            for k, v in e['deger'].get('mods', {}).items():
                out[k] = out.get(k, 0) + v
        weak = sum(e['deger'] for e in self.get('zayiflik', now))
        if weak:
            out['lazer'] = out.get('lazer', 0) - weak
            out['roket'] = out.get('roket', 0) - weak
        return out
