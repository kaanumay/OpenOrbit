"""Mimesis Chest'in buff çekilişi (KAPILAR_PVE-27, KUTULAR-40; veri data/major_content.json 'mimesis'.'sandik' <- tools/major_content.py).

Mimesis Mutiny kapısında (Escort haritaları) ve istilada (Terror / Reflector) düşen Mimesis kutuları (istemci: MIMESIS_AI_*_BOX,
hepsi "Mimesis Box"; wiki: kutu "Mimesis Chest" oldu) toplanınca ödülün üstüne %30 olasılıkla yedi etkiden biri gelir (dunya.take_box
-> roll): Heal (anında 120.000 can), Flux (15 sn +%10 hız), Heal Field (sana ve 500 birim yakındaki oyunculara 50.000 can), Frost
Field (teknik etkisi), Revenge (10 sn), Shield (80.000 kalkan; jeneratör yoksa vermez), Assimilate (10 sn). Revenge ve Assimilate
gemi yeteneklerinin etkisiyle (ship_abilities.json 'etki') durum etkisi 'yetenek' olarak oyuncuya biner (durum.Etkiler.ability /
mods; dunya.hurt_hero okur). Kurallar (wiki): başka etkilerle birikir; aynı etki birikmez, süresi yenilenir; aynı gemi yeteneği ya da
teknik etkinse tetiklenmez; harita değişiminde kalkar (dunya: 'yetenek' türü haritaya özgü). Escort NPC'si (EM Freighter) zaten
oyuncu olmadığından Heal Field onu iyileştirmez. Tek oyunculuda Heal Field yalnız ortak haritadaki yakın grup üyelerine de.
Modül dunya'yı içe aktarmaz (dunya bunu içe aktarır); dünya nesnesiyle çalışır.
"""
import json, math, os, random, time

import ship_ability as SA
import technology as TECH
from legacy_protocol import stm

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'major_content.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('mimesis', {}).get('sandik') or {}
SRC = 'mimesis_sandik'


def pick():
    """Çekiliş: %30'da yedi etkiden biri (olasılıklarla ağırlıklı) -> etki satırı ya da None."""
    rows = D.get('etkiler') or []
    if not rows or random.random() >= D.get('olasilik', 0.3):
        return None
    return random.choices(rows, [r['olasilik'] for r in rows])[0]


def roll(w, now=None):
    """Mimesis kutusu toplandı: çekiliş, çıkan etkiyi uygula -> mesajlar."""
    e = pick()
    return apply(w, e, now) if e else []


def near(w, radius, now):
    """Etki alanındaki oyuncu dünyaları: kendisi ve ortak haritadaki yakın (radius) canlı grup üyeleri."""
    hx, hy = w.hero_pos(now)
    members = [v for v in (w.shared.members if w.shared is not None else ()) if v is not w and v.running and not v.hero_dead]
    return [w] + [v for v in members if math.hypot(v.hero_pos(now)[0] - hx, v.hero_pos(now)[1] - hy) <= radius]


def heal(w, hp=0, shield=0):
    """Anında can ve/ya da kalkan (azami değeri aşmaz; kalkan jeneratörü yoksa azami 0, hiçbir şey eklenmez) -> mesajlar."""
    if w.hero_dead:
        return []
    g = w.p.d['gemi']
    hp0, sh0 = g.get('hitPoints', 0), g.get('shield', 0)
    w.p.set_hull(hp=hp0 + hp if hp else None, shield=sh0 + shield if shield else None)
    if int(g.get('hitPoints', 0)) <= int(hp0) and int(g.get('shield', 0)) <= int(sh0):
        return []                                           # dolu ya da kalkan jeneratörü yok: iyileşme yok
    msgs = [w.hp_msg()]
    if shield:
        msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}))
    return msgs + w.heal_msgs(hp0 if hp else None, sh0 if shield else None)


def apply(w, e, now=None):
    """Bir etkiyi uygula (e: major_content.json mimesis.sandik.etkiler satırı) -> oyuncuya mesajlar."""
    now = time.time() if now is None else now
    t = e['tur']
    w.log('   Mimesis Chest etkisi: %s' % e['ad'])
    if t == 'can':
        return heal(w, hp=e['can'])
    if t == 'kalkan':
        return heal(w, shield=e['kalkan'])
    if t == 'can_alani':
        for v in near(w, e['yaricap'], now)[1:]:
            v.deliver(heal(v, hp=e['can']))
        return heal(w, hp=e['can'])
    if t == 'hiz':
        return timed(w, 'flux', e['sure_sn'], {'mods': {'hiz': e['hiz']}}, None)
    if t == 'yetenek':
        item = e['yetenek']
        if SA.is_active(w.p, item, now):
            return []                                       # aynı gemi yeteneği etkinse tetiklenmez (wiki)
        return timed(w, item, e['sure_sn'], dict(SA.ABILITIES[item]['etki']), item)
    if t == 'teknik':
        item = e['teknik']
        if w.tech.active(item, now):
            return []
        return frost(w, item, TECH.ITEMS[item], now)
    return []


def timed(w, name, sec, value, item):
    """Süreli 'yetenek' durum etkisi (aynı etki birikmez, süresi yenilenir); bitince yeteneğin "… stopped" satırı. item: gemi yeteneği."""
    src = '%s:%s' % (SRC, name)
    w.hero_effects.remove('yetenek', source=src)
    w.hero_effect('yetenek', sec, value, source=src)

    def stop():
        if not any(x['kaynak'] == src for x in w.hero_effects.get('yetenek')) and item:
            w.send(SA.line(item, True))
    w.later(sec + 0.1, stop)
    return SA.line(item) if item else []


def frost(w, item, c, now):
    """Frost Field: tekniğin etkisi sure_sn boyunca saniyede bir (teknoloji.Teknoloji.second: yarıçapta yavaşlatma ve hasar)."""
    if getattr(w, '_chest_freeze', 0) > now:
        w._chest_freeze = now + c['sure_sn']              # sürüyor: süresi yenilenir
        return []
    w._chest_freeze = now + c['sure_sn']

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
