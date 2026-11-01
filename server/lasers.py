"""Special properties of lasers (data items.json "lasers" <- belgeler/wiki/lasers_ammo.md). Set bonuses and effects that depend on the count (set_bonus,
pvp_set, crit, slow) and Asmodeus Fervor (anger) count only the lasers on the ship (wiki "only ship"); a laser's own properties (damage_range, alien_bonus,
alien_extra, target_multiplier, extra_damage_5sec, range, hp_per_laser) also work for lasers on drones.

  damage_range      [min, max]: random on every hit (Unstable LF-4 128-220; the distribution is unknown, taken as uniform)
  alien_bonus       proportional bonus against aliens (LF-3 +15%, Caucasus +15% PvE; to the base only, not to overdrive: fandom DPS 250 = 200 x 1.15 + 100)
  alien_extra       flat extra damage against aliens, per laser (LF-4 Paritydrill "+5 PvE"; wiki "flat +5 added at the end of all
                    calculations": added after the ammo multiplier, flat_extra)
  target_multiplier {name: multiplier}: this laser's damage against the alien whose name matches (Prometheus x3.5 against Black Light aliens, AA-1/AAP-1
                    against AI ships: Mimesis and Cyborg); also works on overdrive (fandom Overdrive Mechanism)
  extra_damage_5sec flat extra to the next hit every 5 s, per laser (SL-01 +38, SL-02 +75, SL-03 +150, Caucasus +100, Prometheus +200)
  range             change to the laser's range (SL-01/02/03 -25%; if even one is on the ship)
  hp_per_laser      HP bonus for each one on the ship (LF-4 Hyperplasmoid +0.5%)                         profile.ship_mods
  set_bonus         damage bonus by the count on the ship (in order of count-1; the last value after that) (LF-5 Mortifier, Asmodeus)
  anger             Asmodeus "Fervor": a tier as aliens are killed (at most 5); resets if no new kill comes within first_sec after the first
                    kill, then within next_sec
  crit              {per_laser, set_threshold, set, maximum, multiplier}: Odysseus critical-hit chance and extra damage (the laser's damage x multiplier)
  slow              [[count, chance, slow, sec]]: slowing an alien on hit by the count on the ship (LF-5 Anchorlock)
  pvp_damage, pvp_ek, pvp_set   against players (MP-1, SLL, Magmadrill "+5 PvP" flat extra, Anchorlock)

Event ammo multipliers (items.json "event_ammo"): while an event runs an ammo hits the aliens in the list harder than usual
(Empyrian March, Prosperous Mutation, Protegit Pandemonium, Immortal Union: UCB-100 / CC-C; Hitac Assault: RSB-75); event_ammo.
"""
import json, os, random, re

HERE = os.path.dirname(os.path.abspath(__file__))
_E = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
LS = _E['lasers']
EVENT_AMMO = {k: v for k, v in _E.get('event_ammo', {}).items() if not k.startswith('_')}
OVERDRIVE_SEC = 5.0


def name_match(table, target):
    """The first multiplier in the {name: multiplier} table that matches the target's name (with a word boundary: Sibelon does not match Sibelonit; case
    insensitive: Demaner matches demaNeR) or None."""
    if target is None:
        return None
    for name, c in table.items():
        if re.search(r'(?<![A-Za-z])%s(?![A-Za-z])' % re.escape(name), target.d['name'], re.I):
            return c
    return None


def hit(loot, target=None, pvp=False):
    """A laser's hit damage on an alien (before the ammo and formation multiplier)."""
    d = LS[loot]
    h = random.randint(*d['damage_range']) if 'damage_range' in d else d['damage']
    if pvp:
        return d.get('pvp_damage', h)
    h = h * (1 + d.get('alien_bonus', 0))
    c = name_match(d.get('target_multiplier', {}), target)
    return h * c if c else h


def flat_extra(loots, pvp=False):
    """Sum of the flat extra damage per laser (LF-4 Paritydrill +5 on an alien, Magmadrill +5 on a player). Wiki: "flat +5 added at the end
    of all calculations" (3 x LF-4-PD, MCB-50: 230 x 3 x 3 + 3 x 5 = 2085): added after the ammo multiplier, not part of the multipliers."""
    key = 'pvp_extra' if pvp else 'alien_extra'
    return sum(LS[l].get(key, 0) for l in loots if l in LS)


def event_ammo(ammo, target, is_active):
    """Event ammo multiplier: if this ammo hits the target harder than usual in an open event, its multiplier (the largest), otherwise None.
    is_active: calendar.is_active. The target is matched by type key ("types", the key in npc.json) or by name ("names", name_match)."""
    if target is None:
        return None
    best = None
    for ev, tab in EVENT_AMMO.items():
        row = tab.get(ammo)
        if row and is_active(ev) and (getattr(target, 'tip', None) in row.get('types', ())
                                      or name_match({a: 1 for a in row.get('names', ())}, target)):
            best = max(best or 0, row['multiplier'])
    return best


def _table(tab, n):
    return tab[min(n, len(tab)) - 1] if n > 0 else 0


def set_bonus(ship, pvp=False):
    bonus = sum(_table(LS[l]['set_bonus'], ship.count(l)) for l in set(ship) if 'set_bonus' in LS.get(l, {}))
    return bonus + (sum(_table(LS[l]['pvp_set'], ship.count(l)) for l in set(ship) if 'pvp_set' in LS.get(l, {})) if pvp else 0)


def crit_chance(ship):
    out = 0.0
    for l in set(ship):
        k = LS.get(l, {}).get('crit')
        if k:
            n = ship.count(l)
            out = max(out, min(k['maximum'], n * k['per_laser'] + (k['set'] if n >= k['set_threshold'] else 0)))
    return out


def crit_damage(ship):
    return sum(LS[l]['damage'] * LS[l]['crit']['multiplier'] for l in ship if 'crit' in LS.get(l, {}))


def overdrive(ship, target=None, pvp=False):
    """Flat damage added to a hit every 5 s; the laser's target multiplier (Prometheus x3.5) applies to it too (fandom Overdrive Mechanism:
    "overdrive damage is also affected by ... Prometheus Laser's x3.5"; for Impulse II 410 x 3.5 = 1,435). The proportional alien_bonus does not apply."""
    return sum(LS[l]['extra_damage_5sec'] * ((None if pvp else name_match(LS[l].get('target_multiplier', {}), target)) or 1)
               for l in ship if LS.get(l, {}).get('extra_damage_5sec'))


def range_factor(ship):
    return 1 + min((LS[l].get('range', 0) for l in ship if l in LS), default=0)


def hp_bonus(ship):
    return sum(LS[l].get('hp_per_laser', 0) for l in ship if l in LS)


def slow_proc(ship):
    """LF-5 Anchorlock: by the count on the ship -> (chance, slow, sec) or None."""
    best = None
    for l in set(ship):
        n = ship.count(l)
        for count, chance, slow_value, sec in LS.get(l, {}).get('slow', []):
            if n >= count:
                best = (chance, slow_value, sec)
    return best


def _fervor_cfg(ship):
    return next((LS[l]['anger'] for l in ship if 'anger' in LS.get(l, {})), None)


class Fervor:
    """The Asmodeus "Fervor" tier (per world; resets when it leaves the map)."""

    def __init__(self):
        self.level, self.until = 0, 0.0

    def kill(self, ship, now):
        cfg = _fervor_cfg(ship)
        if not cfg:
            return
        if now >= self.until:
            self.level = 0
        self.level = min(len(cfg['tier']), self.level + 1)
        self.until = now + (cfg['first_sec'] if self.level == 1 else cfg['next_sec'])

    def bonus(self, ship, now):
        cfg = _fervor_cfg(ship)
        if not cfg or now >= self.until:
            self.level = 0
            return 0.0
        return sum(cfg['tier'][:self.level])
