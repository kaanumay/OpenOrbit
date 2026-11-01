"""Basit kip: botlar haritalara seviyelerine göre dağıtılır, harita değiştirmez, büyük karar vermez; bulundukları haritada uzaylı
keser, düşman olan oyuncuyu görünce gücüne göre saldırır ya da kaçar (ship.py'nin taktiği), ölünce aynı haritada yeniden doğar.

Paket ayarları:
  basit_haritalar  {harita sınıfı: bot sayısı} (X-1, X-2, X-3, X-4, 4-X, X-5, X-6, X-7, X-8, 4-5): her firmanın haritasına ayrı ayrı
  basit_guc        güç oranı (0,5 zayıf .. 2 güçlü): haritanın tipik donanımının çarpanı
  basit_dost       düşman / dost oranı: haritanın firmasından olanların payı (0-1)
Kadro paket oluşturulurken bu sayılara göre üretilir (panel/bots.py); harita ataması ve donanım burada, tohumla belirlenimci.
"""
import random

import map_links as H
from .brain import Goal, target
from . import catalog as K

DEFAULT_MAPS = {'X-1': 2, 'X-2': 2, 'X-3': 2, 'X-4': 2, '4-X': 3, 'X-5': 1, 'X-6': 1, 'X-7': 1, 'X-8': 1, '4-5': 2}

# harita sınıfı -> (gemi, lazer, lazer adedi payı, kalkan jeneratörü, dron sayısı, dron): o haritada oynayan tipik oyuncu
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
    """Kadronun olması gereken büyüklüğü (panel kadroyu buna göre üretir)."""
    return len(distribute(counts))


def distribute(counts):
    """{sınıf: sayı} -> [(harita, firma, sıra)]: sınıfın her haritasına sayı kadar yer (firma haritalarında her firmanınkine ayrı;
    ortak haritalarda (4-X, 4-5) firma None: bot kendi firmasıyla gelir)."""
    out = []
    for s, n in counts.items():
        for m in maps(s):
            owner = H.company(m)
            for k in range(int(n)):
                out.append((m, owner, k))
    return out


def gear(map_id, power=1.0, r=random):
    """Haritanın tipik donanımı x güç oranı: lazer ve jeneratörlerin doluluğu, dron sayısı; güçlüde bir üst lazer."""
    ship, laser, pay, shield, drones, drone = CLASS_GEAR.get(map_class(map_id), CLASS_GEAR['X-1'])
    g = K.ITEMS['gemiler'][ship]
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
    return {'gemi': ship, 'lazer': {laser: max(1, int(round(slot * full)))},
            'kalkan': {shield: max(1, int(round(g['generators'] * full * 0.8)))}, 'hiz': {}, 'dron': {drone: drones} if drones else {},
            'cephane': 'ammunition_laser_mcb-25' if power >= 1.4 else K.AMMO[0]}


def prepare(y, now):
    """Basit kip yükleme: kadroyu haritalara dağıtır (kadronun basit_harita'sı varsa o), donanımı ve seviyeyi kurar; hepsi
    çevrimiçi."""
    power = float(y.setting('basit_guc', 1.0))
    places = distribute(y.setting('basit_haritalar') or DEFAULT_MAPS)
    friend = float(y.setting('basit_dost', 0.5))
    for i, b in enumerate(y.bots):
        r = random.Random('basit|%s|%d' % (b.name, b.k['no']))
        m = b.k.get('simple_map')
        if not m:
            if not places:
                break
            m, owner, _ = places[i % len(places)]
            b.k['simple_map'] = m
            if owner and r.random() < friend:
                b.k['firma'] = owner
            elif owner:
                b.k['firma'] = r.choice([f for f in (1, 2, 3) if f != owner])
        b.k['harita'] = m
        b.k['ekip'] = gear(m, power * r.uniform(0.85, 1.15), r)
        lv = CLASS_LEVEL.get(map_class(m), 5) + r.randint(-1, 2)
        b.k['seviye'] = max(1, lv)
        b.loadout_changed()
        y.entry(b, now)
        b.session_end = float('inf')


@target
class Simple(Goal):
    """Basit kipin tek hedefi: kendi haritasında uzaylı kesmek (soyutta da)."""
    name = 'basit'
    bot_modes = ('basit',)
    min_sec = 1e9

    def points(self, bot, b):
        return 1.0

    def abstract(self, bot, dt, y):
        from . import abstract_sim as S
        S.farm(bot, dt, y)
