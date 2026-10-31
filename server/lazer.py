"""Lazerlerin özel nitelikleri (veri esyalar.json "lazerler" ← belgeler/wiki/lasers_ammo.md). Set bonusları ve adede bağlı etkiler (set_bonus,
pvp_set, kritik, yavaslatma) ve Asmodeus Fervor'u (ofke) yalnız gemideki lazerleri sayar (wiki "only ship"); lazerin kendi nitelikleri (hasar_aralik, uzayli_bonus,
uzayli_ek, hedef_carpan, ek_hasar_5sn, menzil, can_lazer_basina) dronlardaki lazerlerde de işler.

  hasar_aralik      [en az, en çok]: her isabette rastgele (Unstable LF-4 128-220; dağılım bilinmiyor, düzgün alındı)
  uzayli_bonus      uzaylılara oransal bonus (LF-3 +%15, Caucasus +%15 PvE; yalnız tabana, overdrive'a değil: fandom DPS 250 = 200 x 1,15 + 100)
  uzayli_ek         uzaylılara düz ek hasar, lazer başına (LF-4 Paritydrill "+5 PvE"; wiki "flat +5 added at the end of all
                    calculations": cephane çarpanından sonra eklenir, flat_extra)
  hedef_carpan      {ad: çarpan}: adı eşleşen uzaylıya bu lazerin hasarı (Prometheus x3,5 Black Light uzaylılarına, AA-1/AAP-1
                    yapay zekâ gemilerine: Mimesis ve Cyborg); overdrive'a da işler (fandom Overdrive Mechanism)
  ek_hasar_5sn      5 sn'de bir sonraki isabete düz ek, lazer başına (SL-01 +38, SL-02 +75, SL-03 +150, Caucasus +100, Prometheus +200)
  menzil            lazer menzili değişimi (SL-01/02/03 -%25; gemide bir tane bile varsa)
  can_lazer_basina  gemideki her biri için can bonusu (LF-4 Hyperplasmoid +%0,5)                         profil.ship_mods
  set_bonus         gemideki adede göre hasar bonusu (adet-1 sırası; sonrası son değer) (LF-5 Mortifier, Asmodeus)
  ofke              Asmodeus "Fervor": uzaylı öldürdükçe basamak (en çok 5); ilk öldürmeden sonra ilk_sn, sonra sonraki_sn
                    içinde yeni öldürme gelmezse sıfırlanır
  kritik            {lazer_basina, set_esik, set, azami, carpan}: Odysseus kritik vuruş şansı ve ek hasarı (lazerin hasarı x carpan)
  yavaslatma        [[adet, şans, yavaşlatma, sn]]: gemideki adede göre isabette uzaylıyı yavaşlatma (LF-5 Anchorlock)
  pvp_hasar, pvp_ek, pvp_set   oyunculara (MP-1, SLL, Magmadrill "+5 PvP" düz ek, Anchorlock)

Etkinlik cephane çarpanları (esyalar.json "etkinlik_cephane"): etkinlik sürerken bir cephane listedeki uzaylılara olağandan fazla
vurur (Empyrian March, Prosperous Mutation, Protegit Pandemonium, Immortal Union: UCB-100 / CC-C; Hitac Assault: RSB-75); event_ammo.
"""
import json, os, random, re

HERE = os.path.dirname(os.path.abspath(__file__))
_E = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
LZ = _E['lazerler']
EVENT_AMMO = {k: v for k, v in _E.get('etkinlik_cephane', {}).items() if not k.startswith('_')}
OVERDRIVE_SN = 5.0


def name_match(table, target):
    """{ad: çarpan} tablosunda hedefin adına uyan ilk çarpan (kelime sınırıyla: Sibelon, Sibelonit'e uymaz; büyük/küçük harf
    ayrımsız: Demaner, demaNeR'e uyar) ya da None."""
    if target is None:
        return None
    for ad, c in table.items():
        if re.search(r'(?<![A-Za-z])%s(?![A-Za-z])' % re.escape(ad), target.d['ad'], re.I):
            return c
    return None


def hit(loot, target=None, pvp=False):
    """Bir lazerin uzaylıya isabet hasarı (cephane ve formasyon çarpanından önce)."""
    d = LZ[loot]
    h = random.randint(*d['hasar_aralik']) if 'hasar_aralik' in d else d['hasar']
    if pvp:
        return d.get('pvp_hasar', h)
    h = h * (1 + d.get('uzayli_bonus', 0))
    c = name_match(d.get('hedef_carpan', {}), target)
    return h * c if c else h


def flat_extra(loots, pvp=False):
    """Lazer başına düz ek hasarların toplamı (LF-4 Paritydrill uzaylıya +5, Magmadrill oyuncuya +5). Wiki: "flat +5 added at the end
    of all calculations" (3 x LF-4-PD, MCB-50: 230 x 3 x 3 + 3 x 5 = 2085): cephane çarpanından sonra eklenir, çarpanlara girmez."""
    key = 'pvp_ek' if pvp else 'uzayli_ek'
    return sum(LZ[l].get(key, 0) for l in loots if l in LZ)


def event_ammo(ammo, target, is_active):
    """Etkinlik cephane çarpanı: bu cephane, açık bir etkinlikte hedefe olağandan fazla vuruyorsa çarpanı (en büyüğü), yoksa None.
    is_active: takvim.is_active. Hedef tür anahtarıyla ("tipler") ya da adıyla ("adlar", name_match) eşlenir."""
    if target is None:
        return None
    best = None
    for ev, tab in EVENT_AMMO.items():
        row = tab.get(ammo)
        if row and is_active(ev) and (getattr(target, 'tip', None) in row.get('tipler', ())
                                      or name_match({a: 1 for a in row.get('adlar', ())}, target)):
            best = max(best or 0, row['carpan'])
    return best


def _table(tab, n):
    return tab[min(n, len(tab)) - 1] if n > 0 else 0


def set_bonus(ship, pvp=False):
    bonus = sum(_table(LZ[l]['set_bonus'], ship.count(l)) for l in set(ship) if 'set_bonus' in LZ.get(l, {}))
    return bonus + (sum(_table(LZ[l]['pvp_set'], ship.count(l)) for l in set(ship) if 'pvp_set' in LZ.get(l, {})) if pvp else 0)


def crit_chance(ship):
    out = 0.0
    for l in set(ship):
        k = LZ.get(l, {}).get('kritik')
        if k:
            n = ship.count(l)
            out = max(out, min(k['azami'], n * k['lazer_basina'] + (k['set'] if n >= k['set_esik'] else 0)))
    return out


def crit_damage(ship):
    return sum(LZ[l]['hasar'] * LZ[l]['kritik']['carpan'] for l in ship if 'kritik' in LZ.get(l, {}))


def overdrive(ship, target=None, pvp=False):
    """5 sn'de bir isabete eklenen düz hasar; lazerin hedef çarpanı (Prometheus x3,5) ona da işler (fandom Overdrive Mechanism:
    "overdrive damage is also affected by ... Prometheus Laser's x3.5"; Impulse II'de 410 x 3,5 = 1.435). Oransal uzayli_bonus işlemez."""
    return sum(LZ[l]['ek_hasar_5sn'] * ((None if pvp else name_match(LZ[l].get('hedef_carpan', {}), target)) or 1)
               for l in ship if LZ.get(l, {}).get('ek_hasar_5sn'))


def range_factor(ship):
    return 1 + min((LZ[l].get('menzil', 0) for l in ship if l in LZ), default=0)


def hp_bonus(ship):
    return sum(LZ[l].get('can_lazer_basina', 0) for l in ship if l in LZ)


def slow_proc(ship):
    """LF-5 Anchorlock: gemideki adede göre -> (şans, yavaşlatma, sn) ya da None."""
    best = None
    for l in set(ship):
        n = ship.count(l)
        for adet, sans, yv, sn in LZ.get(l, {}).get('yavaslatma', []):
            if n >= adet:
                best = (sans, yv, sn)
    return best


def _fervor_cfg(ship):
    return next((LZ[l]['ofke'] for l in ship if 'ofke' in LZ.get(l, {})), None)


class Ofke:
    """Asmodeus "Fervor" basamağı (dünya başına; haritadan çıkınca sıfırlanır)."""

    def __init__(self):
        self.level, self.until = 0, 0.0

    def kill(self, ship, now):
        cfg = _fervor_cfg(ship)
        if not cfg:
            return
        if now >= self.until:
            self.level = 0
        self.level = min(len(cfg['basamak']), self.level + 1)
        self.until = now + (cfg['ilk_sn'] if self.level == 1 else cfg['sonraki_sn'])

    def bonus(self, ship, now):
        cfg = _fervor_cfg(ship)
        if not cfg or now >= self.until:
            self.level = 0
            return 0.0
        return sum(cfg['basamak'][:self.level])
