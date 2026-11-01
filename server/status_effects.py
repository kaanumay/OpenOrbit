"""Status effects: the timed effects of an entity (alien or player). Ship abilities, in future special rockets, mines, EMP and
alien abilities use them (world.py applies them).

Types (meaning of the value):
  slow         speed multiplier drop (0.3 = 30% slower); if several, the strongest
  frozen       cannot move or fire
  hit          accuracy drop (0.4 = 40% less accuracy); added up, at most 1
  shield_damage_taken damage multiplier to the shield (1.5 = the share the shield absorbs melts 1.5 times as fast, the hull share the same; Diminisher Weaken Shields);
               if several, the largest
  damage_bonus damage bonus dealt to this entity (0.05 = +5%; Target Marker); added up
  immune_until takes no damage
  speed_up     speed at least this value (Speed Burst 1,800); on the player floor_speed
  poison       damage to the hull once a second: value (hit), increase (per hit), max_count, remaining (total limit), next (time)
  speed_limit  speed at most this value (the slowing sphere of Barb and The Stinger: 120); on the player max_speed; if several, the smallest
  weakness     drop in the player's laser and rocket damage (0.1 = 10%; Emperor Sibelon's DMG capsule); added up
  skill        an effect in the form of a ship ability on the player (ship_abilities.json 'effect': mirror, absorb_hp, mods); Mimesis Chest's Revenge,
               Assimilate and Flux (mimesis_chest.py); mods into the profile bonuses, ability(key) into hurt_hero
Every effect has a source (e.g. the ability's menu item); it can be removed early by source.
"""
import time


class Effects:
    def __init__(self):
        self.d = {}                   # type -> [{end_time, value, source, ...}]

    def add(self, kind, sec, value=1.0, source=None, now=None, **extra):
        now = now or time.time()
        e = dict(extra, end_time=now + sec, value=value, source=source)
        self.d.setdefault(kind, []).append(e)
        return e

    def get(self, kind, now=None):
        """Ongoing effects (expired ones are pruned)."""
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
        """Types that ended (effects whose time is up are pruned) -> set of types; for those needing recalculation, like the player's speed."""
        now = now or time.time()
        out = set()
        for k in list(self.d):
            if any(now >= e['end_time'] for e in self.d[k]):
                out.add(k)
                self.get(k, now)
        return out

    # ------------------------------------------------------------ combined values
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
        """One effect (mirror, absorb_hp ...) of the active 'skill' effects -> value or None (the chest counterpart of ship_ability.effect)."""
        return next((e['value'][key] for e in self.get('skill', now) if key in e['value']), None)

    def speed_factor(self, now=None):
        return 0.0 if self.frozen(now) else 1.0 - self.slow(now)

    def poison_due(self, now=None):
        """Poison hits whose time has come -> [damage]; after a hit the next time, increase and remainder are updated."""
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
        """The player's effects into the profile bonuses (player_profile.mods): slowness hiz, immobility sabit_hiz 0, accuracy drop."""
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
