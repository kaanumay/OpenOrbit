"""Fever (Ship Boost Event; yol haritası Ö3; veri data/extra_events.json 'fever').

İstemci (UIShipBoostSystem, menü öğesi ship_boost_event, pencere 73): ShipBoostEventInfoCommand {shipBoostSlots [ShipBoostEventModule
{day 1-7 (pazartesi-pazar), startTime, endTime ("SS:DD"), shipTypes (gösterilen gemi adları), eventNameTextKeys (haritaların metin
anahtarı), attributeBoosts [{attribute (ship_boost_effects_modifiertype_<küçük harf>), boostValue (yüzde; ABILITY_COOLDOWN_TIME
eksiyle gösterilir)}]}], boostUpdateInfo ShipBoostEventUpdateInfoCommand {currentSlot, timeToWindowChange, isBoostActive,
boostInfo {isShipBoosted}}}. Metinler: ship_boost_announcement_active / inactive, ship_boost_ttip (güçlenme ve ölünce üste ya da en
yakın portalda ücretsiz onarım), ship_boost_schedule_content_effects_1..9 (günlerin gemileri ve etkileri).
Asıl oyunda Galactic Strife (PvP) haritalarında; tek oyunculu uyarlama: PvE haritaları (veri 'olaylar': Hitac'ın normal haritaları
X-2..X-8, Eternal Blacklight, Gauntlet of Plutus) ve oyuncu gemisine verilen hasar yerine uzaylı hasarı (damage_npc). Gemi
eşleşmesi: gösterilen ad geminin lootId'sinin başı (Aegis -> ship_aegis*, Goliath -> ship_goliath*).
Tarih aralıklı setler ('setler': bas, bit, haritalar, olaylar, gunler; gerçek oyunun Black Light haftaları): sürerken varsayılan
takımın yerine geçer (cfg); takvimdeki gibi her 52 haftada (364 gün) tekrarlanır.
"""
import datetime, json, os, time

import map_links as H
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('fever', {})
EVENT = 'fever'
# istemcinin etki adı -> profil.mods() anahtarı (uzaylıya hasar: 'npc'; bekleme azalması 'bekleme')
MODS = {'SHIELD': 'kalkan', 'SPEED': 'hiz', 'EVASION': 'kacinma', 'HITPOINTS': 'can', 'DAMAGE_NPC': 'npc', 'DAMAGE': 'npc',
        'ABILITY_COOLDOWN_TIME': 'bekleme', 'EXPERIENCE_POINTS': 'ep', 'HONOUR_POINTS': 'onur', 'LASER_HIT_CHANCE': 'lazer_isabet',
        'ROCKET_DAMAGE': 'roket', 'LASER_DAMAGE_PLAYER': 'lazer'}


def _hm(s):
    h, m = (int(x) for x in s.split(':'))
    return h * 60 + m


def cfg(now=None):
    """Geçerli takım: sürmekte olan tarih aralıklı set ('setler'; her 52 haftada tekrar) ya da varsayılan takım (D)."""
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    for s in D.get('sets', []):
        a, b = datetime.date.fromisoformat(s['bas']), datetime.date.fromisoformat(s['bit'])
        if d >= a and (d - a).days % 364 <= (b - a).days:
            return s
    return D


def slot_for(now=None):
    """Bugünün dilimi (gün 1 = pazartesi) ya da None."""
    t = datetime.datetime.fromtimestamp(time.time() if now is None else now)
    return next((s for s in cfg(now).get('days', []) if s['gun'] == t.isoweekday()), None)


def window(now=None):
    """(şu an sürüyor mu, pencerenin değişmesine kalan saniye)."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    mins = t.hour * 60 + t.minute + t.second / 60.0
    s = slot_for(now)
    if not s:
        return False, 86400
    a, b = _hm(s['bas']), _hm(s['bit'])
    b = b if b > a else b + 1440
    if a <= mins < b:
        return True, int((b - mins) * 60)
    if mins < a:
        return False, int((a - mins) * 60)
    nxt = slot_for((t.replace(hour=12, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)).timestamp())    # yarın
    return False, int((1440 - mins + (_hm(nxt['bas']) if nxt else 1440)) * 60)


def ship_matches(slot, loot):
    base = loot[5:] if loot.startswith('ship_') else loot
    return any(base.startswith(n.lower().replace(' ', '-')) for n in slot.get('gemiler', []))


def map_matches(map_id, now=None):
    c, cls = cfg(now), H.map_class(map_id)
    return cls in c.get('haritalar', []) or int(map_id) in c.get('map_ids', [])


class Fever:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.was = None
        self.boosted_was = None
        self._mods = {}
        profile.event_mods = self.mods

    def enabled(self):
        import event_calendar as CAL
        return CAL.is_active(EVENT)

    def active(self, now=None):
        return self.enabled() and window(now)[0]

    def boosted(self, now=None):
        """Fever şu an oyuncunun gemisine uygulanıyor mu (gün, saat, gemi, harita)."""
        s = slot_for(now)
        return bool(s and self.active(now) and ship_matches(s, self.p.ship()['lootId'])
                    and map_matches(self.p.d['position'].get('mapId', 0), now))

    def compute(self, now=None):
        """Gemiye uygulanan etkiler (profil.mods() sıcak yolda: tick'te saniyede bir hesaplanıp saklanır)."""
        if not self.boosted(now):
            return {}
        out = {}
        for a, v in slot_for(now)['effects'].items():
            k = MODS.get(a.upper())
            if k:
                out[k] = out.get(k, 0) + v / 100.0
        return out

    def mods(self):
        return self._mods

    def free_repair(self):
        return bool(self._mods)

    def module(self, s, now=None):
        return {'_': 'ShipBoostEventModule', 'day': s['gun'], 'startTime': s['bas'], 'endTime': s['bit'], 'shipTypes': list(s['gemiler']),
                'eventNameTextKeys': list(cfg(now).get('events', [])),
                'attributeBoosts': [{'_': 'ShipBoostEventAttributeModule', 'attribute': a, 'boostValue': float(v)}
                                    for a, v in s['effects'].items()]}

    def update_cmd(self, now=None):
        on, left = window(now)
        s = slot_for(now)
        return {'_': 'ShipBoostEventUpdateInfoCommand', 'currentSlot': self.module(s, now) if s else None, 'timeToWindowChange': left,   # saniye (canlı)
                'isBoostActive': bool(on and self.enabled()),
                'boostInfo': {'_': 'ShipBoostEventBoostInfoCommand', 'isShipBoosted': self.boosted(now)}}

    def info_cmd(self, now=None):
        return ('ShipBoostEventInfoCommand', {'shipBoostSlots': [self.module(s, now) for s in cfg(now).get('days', [])],
                                             'boostUpdateInfo': self.update_cmd(now)})

    def login_msgs(self):
        if not self.enabled():
            return []
        self.was, self.boosted_was = self.active(), self.boosted()
        self._mods = self.compute()
        return [self.info_cmd()]

    def tick(self, now):
        if not self.enabled():
            self._mods = {}
            return []
        on, b = self.active(now), self.boosted(now)
        self._mods = self.compute(now)
        msgs = []
        if self.was is not None and on != self.was:
            msgs += [legacy('0|A|STM|ship_boost_announcement_%s' % ('active' if on else 'inactive')), self.info_cmd(now)]
            self.log('   Fever %s' % ('başladı' if on else 'bitti'))
        if self.boosted_was is not None and b != self.boosted_was:
            msgs += [('ShipBoostEventBoostInfoCommand', {'isShipBoosted': b})] + self.m.apply_stats()
        self.was, self.boosted_was = on, b
        return msgs

    def attach(self, world):
        world.free_gate_repair = self.free_repair
        self._mods = self.compute()                    # yeni harita: etki haritaya bağlı
        return []
