"""The Mimesis Chest's buff draw (KAPILAR_PVE-27, KUTULAR-40; data data/major_content.json 'mimesis'.'chest' <- tools/major_content.py).

When Mimesis boxes (client: MIMESIS_AI_*_BOX, all "Mimesis Box"; wiki: the box became "Mimesis Chest") that drop in the Mimesis Mutiny gate (Escort maps) and
in the invasion (Terror / Reflector) are collected, on top of the reward there is a 30% chance of one of seven effects (world.take_box
-> roll): Heal (instant 120,000 HP), Flux (15 s +10% speed), Heal Field (50,000 HP to you and the players within 500 units), Frost
Field (technique effect), Revenge (10 s), Shield (80,000 shield; gives nothing without a generator), Assimilate (10 s). Revenge and Assimilate
act through the ship abilities' effect (ship_abilities.json 'effect'): the status effect is applied to the player as 'skill' (status_effects.Effects.ability /
mods; world.hurt_hero reads it). Rules (wiki): stacks with other effects; the same effect does not stack, its duration is refreshed; it does not trigger if the same ship ability or
technique effect is active; it is removed on a map change (world: the 'skill' type is map-specific). The Escort NPC (EM Freighter) is not
a player, so Heal Field does not heal it. In single player Heal Field also reaches only nearby group members on the shared map.
The module does not import world (world imports this); it works with the world object.
"""
import json, math, os, random, time

import ship_ability as SA
import technology as TECH
from legacy_protocol import stm

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('mimesis', {}).get('chest') or {}
SRC = 'mimesis_chest'


def pick():
    """Draw: one of seven effects at 30% (weighted by probabilities) -> the effect row or None."""
    rows = D.get('effects') or []
    if not rows or random.random() >= D.get('probability', 0.3):
        return None
    return random.choices(rows, [r['probability'] for r in rows])[0]


def roll(w, now=None):
    """A Mimesis box was collected: draw, apply the resulting effect -> messages."""
    e = pick()
    return apply(w, e, now) if e else []


def near(w, radius, now):
    """Player worlds in the effect area: the player and the live group members within (radius) on the shared map."""
    hx, hy = w.hero_pos(now)
    members = [v for v in (w.shared.members if w.shared is not None else ()) if v is not w and v.running and not v.hero_dead]
    return [w] + [v for v in members if math.hypot(v.hero_pos(now)[0] - hx, v.hero_pos(now)[1] - hy) <= radius]


def heal(w, hp=0, shield=0):
    """Instant HP and/or shield (does not exceed the maximum; without a shield generator the maximum is 0, nothing is added) -> messages."""
    if w.hero_dead:
        return []
    g = w.p.d['ship']
    hp0, sh0 = g.get('hitPoints', 0), g.get('shield', 0)
    w.p.set_hull(hp=hp0 + hp if hp else None, shield=sh0 + shield if shield else None)
    if int(g.get('hitPoints', 0)) <= int(hp0) and int(g.get('shield', 0)) <= int(sh0):
        return []                                           # full or no shield generator: no healing
    msgs = [w.hp_msg()]
    if shield:
        msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}))
    return msgs + w.heal_msgs(hp0 if hp else None, sh0 if shield else None)


def apply(w, e, now=None):
    """Apply an effect (e: a row of major_content.json mimesis.chest.effects) -> messages to the player."""
    now = time.time() if now is None else now
    t = e['type']
    w.log('   Mimesis Chest effect: %s' % e['name'])
    if t == 'hp':
        return heal(w, hp=e['hp'])
    if t == 'shield':
        return heal(w, shield=e['shield'])
    if t == 'hp_field':
        for v in near(w, e['radius'], now)[1:]:
            v.deliver(heal(v, hp=e['hp']))
        return heal(w, hp=e['hp'])
    if t == 'speed':
        return timed(w, 'flux', e['duration_sec'], {'mods': {'speed': e['speed']}}, None)
    if t == 'skill':
        item = e['skill']
        if SA.is_active(w.p, item, now):
            return []                                       # does not trigger if the same ship ability is active (wiki)
        return timed(w, item, e['duration_sec'], dict(SA.ABILITIES[item]['effect']), item)
    if t == 'tech':
        item = e['tech']
        if w.tech.active(item, now):
            return []
        return frost(w, item, TECH.ITEMS[item], now)
    return []


def timed(w, name, sec, value, item):
    """Timed 'skill' status effect (the same effect does not stack, its duration is refreshed); when it ends the ability's "... stopped" line. item: the ship ability."""
    src = '%s:%s' % (SRC, name)
    w.hero_effects.remove('skill', source=src)
    w.hero_effect('skill', sec, value, source=src)

    def stop():
        if not any(x['source'] == src for x in w.hero_effects.get('skill')) and item:
            w.send(SA.line(item, True))
    w.later(sec + 0.1, stop)
    return SA.line(item) if item else []


def frost(w, item, c, now):
    """Frost Field: the technique's effect once per second for sure_sn (technology.Technology.second: slowing and damage in the radius)."""
    if getattr(w, '_chest_freeze', 0) > now:
        w._chest_freeze = now + c['duration_sec']              # running: its duration is refreshed
        return []
    w._chest_freeze = now + c['duration_sec']

    def tick():
        t = time.time()
        if w.hero_dead or t >= w._chest_freeze:
            w._chest_freeze = 0
            w.send(w.tech.visual(item, False))
            return
        w.tech.second(item, c, t)
        w.later(1.0, tick)
    w.later(1.0, tick)
    return w.tech.visual(item, True)
