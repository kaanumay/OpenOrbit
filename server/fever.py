"""Fever (Ship Boost Event; roadmap Ö3; data data/extra_events.json 'fever').

Client (UIShipBoostSystem, menu item ship_boost_event, window 73): ShipBoostEventInfoCommand {shipBoostSlots [ShipBoostEventModule
{day 1-7 (Monday-Sunday), startTime, endTime ("HH:MM"), shipTypes (displayed ship names), eventNameTextKeys (the maps' text
keys), attributeBoosts [{attribute (ship_boost_effects_modifiertype_<lowercase>), boostValue (percent; ABILITY_COOLDOWN_TIME
is shown negative)}]}], boostUpdateInfo ShipBoostEventUpdateInfoCommand {currentSlot, timeToWindowChange, isBoostActive,
boostInfo {isShipBoosted}}}. Texts: ship_boost_announcement_active / inactive, ship_boost_ttip (boost, and free repair at the top or
the nearest portal on death), ship_boost_schedule_content_effects_1..9 (the days' ships and effects).
In the real game it is on Galactic Strife (PvP) maps; single-player adaptation: PvE maps (data 'events': Hitac's normal maps
X-2..X-8, Eternal Blacklight, Gauntlet of Plutus) and alien damage instead of damage to the player's ship (damage_npc). Ship
matching: the displayed name is the start of the ship's lootId (Aegis -> ship_aegis*, Goliath -> ship_goliath*).
Date-ranged sets ('sets': start, bit, maps, events, days; the real game's Black Light weeks): while running they replace the
default set (cfg); as in the calendar they repeat every 52 weeks (364 days).
"""
import datetime, json, os, time

import map_links as H
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('fever', {})
EVENT = 'fever'
# the client's effect name -> profile.mods() key (damage to aliens: 'npc'; cooldown reduction 'cooldown')
MODS = {'SHIELD': 'shield', 'SPEED': 'speed', 'EVASION': 'evasion', 'HITPOINTS': 'hp', 'DAMAGE_NPC': 'npc', 'DAMAGE': 'npc',
        'ABILITY_COOLDOWN_TIME': 'cooldown', 'EXPERIENCE_POINTS': 'ep', 'HONOUR_POINTS': 'honor', 'LASER_HIT_CHANCE': 'laser_hit_chance',
        'ROCKET_DAMAGE': 'rocket', 'LASER_DAMAGE_PLAYER': 'laser'}


def _hm(s):
    h, m = (int(x) for x in s.split(':'))
    return h * 60 + m


def cfg(now=None):
    """The current set: the running date-ranged set ('setler'; repeats every 52 weeks) or the default set (D)."""
    d = datetime.date.fromtimestamp(time.time() if now is None else now)
    for s in D.get('sets', []):
        a, b = datetime.date.fromisoformat(s['start']), datetime.date.fromisoformat(s['bit'])
        if d >= a and (d - a).days % 364 <= (b - a).days:
            return s
    return D


def _day_slots(ts):
    """The slots of that day (day 1 = Monday), earliest first."""
    wd = datetime.datetime.fromtimestamp(ts).isoweekday()
    return sorted((s for s in cfg(ts).get('days', []) if s['day'] == wd), key=lambda s: _hm(s['start']))


def slot_for(now=None):
    """The slot running now, else today's next one, else tomorrow's first (None if there is none)."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    mins = t.hour * 60 + t.minute + t.second / 60.0
    slots = _day_slots(now)
    for s in slots:
        a, b = _hm(s['start']), _hm(s['bit'])
        if a <= mins < (b if b > a else b + 1440):
            return s
    later = [s for s in slots if _hm(s['start']) > mins]
    if later:
        return later[0]
    tomorrow = _day_slots((t.replace(hour=12, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)).timestamp())
    return tomorrow[0] if tomorrow else None


def window(now=None):
    """(whether it is running now, seconds left until the window changes)."""
    now = time.time() if now is None else now
    t = datetime.datetime.fromtimestamp(now)
    mins = t.hour * 60 + t.minute + t.second / 60.0
    s = slot_for(now)
    if not s:
        return False, 86400
    a, b = _hm(s['start']), _hm(s['bit'])
    b = b if b > a else b + 1440
    if not any(s is x for x in _day_slots(now)):                    # tomorrow's first slot
        return False, int((1440 - mins + a) * 60)
    if a <= mins < b:
        return True, int((b - mins) * 60)
    return False, int((a - mins) * 60)


def ship_matches(slot, loot):
    base = loot[5:] if loot.startswith('ship_') else loot
    return any(base.startswith(n.lower().replace(' ', '-')) for n in slot.get('ships', []))


def map_matches(map_id, now=None):
    c, cls = cfg(now), H.map_class(map_id)
    return cls in c.get('maps', []) or int(map_id) in c.get('map_ids', [])


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
        """Whether Fever applies to the player's ship now (day, hour, ship, map)."""
        s = slot_for(now)
        return bool(s and self.active(now) and ship_matches(s, self.p.ship()['lootId'])
                    and map_matches(self.p.d['position'].get('mapId', 0), now))

    def compute(self, now=None):
        """The effects applied to the ship (profile.mods() on the hot path: computed once a second in the tick and cached)."""
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
        return {'_': 'ShipBoostEventModule', 'day': s['day'], 'startTime': s['start'], 'endTime': s['bit'], 'shipTypes': list(s['ships']),
                'eventNameTextKeys': list(cfg(now).get('events', [])),
                'attributeBoosts': [{'_': 'ShipBoostEventAttributeModule', 'attribute': a, 'boostValue': float(v)}
                                    for a, v in s['effects'].items()]}

    def update_cmd(self, now=None):
        on, left = window(now)
        s = slot_for(now)
        return {'_': 'ShipBoostEventUpdateInfoCommand', 'currentSlot': self.module(s, now) if s else None, 'timeToWindowChange': left,   # seconds (live)
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
            self.log('   Fever %s' % ('started' if on else 'finished'))
        if self.boosted_was is not None and b != self.boosted_was:
            msgs += [('ShipBoostEventBoostInfoCommand', {'isShipBoosted': b})] + self.m.apply_stats()
        self.was, self.boosted_was = on, b
        return msgs

    def attach(self, world):
        world.free_gate_repair = self.free_repair
        self._mods = self.compute()                    # new map: the effect depends on the map
        return []
