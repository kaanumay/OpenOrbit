"""Simple mode: bots are distributed over the maps by their level, do not change maps, make no big decisions; on their map they kill
aliens, and on seeing an enemy player they attack or flee depending on strength (ship.py's tactics), and respawn on the same map when they die.

Pack settings:
  basit_haritalar  {map class: bot count} (X-1, X-2, X-3, X-4, 4-X, X-5, X-6, X-7, X-8, 4-5): separately for each company's map
  basit_guc        strength ratio (0.5 weak .. 2 strong): multiplier of the map's typical equipment
  basit_dost       enemy / friendly ratio: the share of those from the map's company (0-1)
The roster is generated from these numbers when the pack is created (panel/bots.py); map assignment and equipment are here, deterministic by seed.
"""
import random

import map_links as H
from .brain import Goal, target
from . import catalog as K

DEFAULT_MAPS = {'X-1': 2, 'X-2': 2, 'X-3': 2, 'X-4': 2, '4-X': 3, 'X-5': 1, 'X-6': 1, 'X-7': 1, 'X-8': 1, '4-5': 2}

# map class -> (ship, laser, laser count share, shield generator, drone count, drone): the typical player on that map
CLASS_GEAR = {
    'X-1': ('ship_phoenix', 'equipment_weapon_laser_lf-1', 1.0, 'equipment_generator_shield_sg3n-a01', 0, None),
    'X-2': ('ship_piranha', 'equipment_weapon_laser_mp-1', 0.8, 'equipment_generator_shield_sg3n-a02', 0, None),
    'X-3': ('ship_nostromo', 'equipment_weapon_laser_mp-1', 1.0, 'equipment_generator_shield_sg3n-a02', 2, 'drone_flax'),
    'X-4': ('ship_bigboy', 'equipment_weapon_laser_sll-01', 1.0, 'equipment_generator_shield_sg3n-a03', 3, 'drone_flax'),
    '4-X': ('ship_vengeance', 'equipment_weapon_laser_lf-2', 1.0, 'equipment_generator_shield_sg3n-a03', 4, 'drone_flax'),
    'X-5': ('ship_goliath', 'equipment_weapon_laser_lf-2', 0.9, 'equipment_generator_shield_sg3n-b02', 6, 'drone_iris'),
    'X-6': ('ship_goliath', 'equipment_weapon_laser_lf-3', 0.9, 'equipment_generator_shield_sg3n-b02', 7, 'drone_iris'),
    'X-7': ('ship_goliath', 'equipment_weapon_laser_lf-3', 1.0, 'equipment_generator_shield_sg3n-b02', 8, 'drone_iris'),
    'X-8': ('ship_goliath', 'equipment_weapon_laser_lf-3', 1.0, 'equipment_generator_shield_sg3n-b02', 8, 'drone_iris'),
    '4-5': ('ship_goliath', 'equipment_weapon_laser_lf-3', 1.0, 'equipment_generator_shield_sg3n-b02', 8, 'drone_iris'),
}
CLASS_LEVEL = {'X-1': 3, 'X-2': 5, 'X-3': 7, 'X-4': 9, '4-X': 11, 'X-5': 13, 'X-6': 14, 'X-7': 15, 'X-8': 16, '4-5': 17}


def map_class(map_id):
    c = H.map_class(map_id)
    return '4-X' if c in ('4-1', '4-2', '4-3', '4-4') else c


def maps(class_name):
    return [m for m in K.MAPS if map_class(m) == class_name]


def slot_count(counts):
    """The size the roster should have (the panel generates the roster accordingly)."""
    return len(distribute(counts))


def distribute(counts):
    """{class: count} -> [(map, company, order)]: for each map of the class, that many places (company maps each get their own per company;
    on shared maps (4-X, 4-5) the company is None: the bot comes with its own company)."""
    out = []
    for s, n in counts.items():
        for m in maps(s):
            owner = H.company(m)
            for k in range(int(n)):
                out.append((m, owner, k))
    return out


def gear(map_id, power=1.0, r=random):
    """The map's typical equipment x strength ratio: fill level of lasers and generators, drone count; one laser tier higher when strong."""
    ship, laser, pay, shield, drones, drone = CLASS_GEAR.get(map_class(map_id), CLASS_GEAR['X-1'])
    g = K.ITEMS['ships'][ship]
    order = ['equipment_weapon_laser_lf-1', 'equipment_weapon_laser_mp-1', 'equipment_weapon_laser_sll-01',
            'equipment_weapon_laser_lf-2', 'equipment_weapon_laser_lf-3']
    i = order.index(laser) if laser in order else 0
    if power >= 1.5 and i + 1 < len(order):
        laser = order[i + 1]
    elif power <= 0.6 and i > 0:
        laser = order[i - 1]
    full = max(0.25, min(1.0, pay * power * r.uniform(0.8, 1.1)))
    drones = max(0, min(8, int(round(drones * min(power, 1.3) * r.uniform(0.7, 1.2))))) if drone else 0
    slot = g['laser'] + drones * (2 if drone == 'drone_iris' else 1)
    return {'ship': ship, 'laser': {laser: max(1, int(round(slot * full)))},
            'shield': {shield: max(1, int(round(g['generators'] * full * 0.8)))}, 'speed': {}, 'drone': {drone: drones} if drones else {},
            'ammunition': 'ammunition_laser_mcb-25' if power >= 1.4 else K.AMMO[0]}


def prepare(y, now):
    """Simple mode loading: distributes the roster over the maps (the roster's basit_harita if it has one), sets up equipment and level; all
    online."""
    power = float(y.setting('simple_power', 1.0))
    places = distribute(y.setting('simple_maps') or DEFAULT_MAPS)
    friend = float(y.setting('simple_friendly', 0.5))
    for i, b in enumerate(y.bots):
        r = random.Random('basit|%s|%d' % (b.name, b.k['no']))
        m = b.k.get('simple_map')
        if not m:
            if not places:
                break
            m, owner, _ = places[i % len(places)]
            b.k['simple_map'] = m
            if owner and r.random() < friend:
                b.k['company'] = owner
            elif owner:
                b.k['company'] = r.choice([f for f in (1, 2, 3) if f != owner])
        b.k['map'] = m
        b.k['gear'] = gear(m, power * r.uniform(0.85, 1.15), r)
        lv = CLASS_LEVEL.get(map_class(m), 5) + r.randint(-1, 2)
        b.k['level'] = max(1, lv)
        b.loadout_changed()
        y.entry(b, now)
        b.session_end = float('inf')


@target
class Simple(Goal):
    """Simple mode's only goal: killing aliens on its own map (in the abstract too)."""
    name = 'simple'
    bot_modes = ('simple',)
    min_sec = 1e9

    def points(self, bot, b):
        return 1.0

    def abstract(self, bot, dt, y):
        from . import abstract_sim as S
        S.farm(bot, dt, y)
