"""Eski Invasion: firma yarışı (yol haritası Ö3; veri data/extra_events.json 'istila').

İstemci: menü öğesi invasion (pencere 68) InvasionEventInitCommand {score_MMO, score_EIC, score_VRU, waveCount} gösterir; metinler
title_invasion, atk_wave_started (%COUNT%). Haritalar maps-config 61-69 (MMO / EIC / VRU Invasion).
Kurallar (2009 haberi, fandom): firmanın ana haritasında, X-3'te ve X-5'te seviye aralığına göre Invasion kapısı (5-9, 10-14, 15+);
içeride yalnız uzaylılar, 22 dalga (Streuner .. Boss Kucurbium) sonra baştan; çıkış yalnız ölerek, onarım ücretsiz; her uzaylı firmaya
1 puan; etkinlik sonunda ilk üç firmaya bir hafta +%10 / +%5 / +%3 hasar. Sunucunun Compromising Invasion kapısından ayrı.
Kapılar etkinlik kapısı motorunda (event_gate.py; kural firma, seviye aralığı, sonsuz). Öteki firmaların puanı sanal.
Tek oyunculu uyarlama: motorun öteki kapıları gibi dalga arasında çıkış portalı açılır (ölmeden ayrılmak için).
Profilde: istila {donem, puan {1, 2, 3}, dalga, odul_alindi}.
"""
import json, os, random, time

import event_gate as EKP
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('istila', {})
EVENT = 'invasion'
MAPS = {int(m): k for k, g in (D.get('kapilar') or {}).items() for m in g['haritalar']}

for _k, _g in (D.get('kapilar') or {}).items():           # game.py EKP.register_npcs'den önce: uzaylı türleri de kaydedilir
    EKP.GATES[_k] = _g
    for _m in _g['haritalar']:
        EKP.BY_MAP[int(_m)] = _k


def active(now=None):
    return EVENT in CAL.active(now)


class Invasion:
    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.world = None
        self.next_score = 0.0
        self.next_info = 0.0
        event_gates.wave_hooks.append(self.on_wave)

    @property
    def st(self):
        d = self.p.d.setdefault('istila', {})
        d.setdefault('puan', {'1': 0, '2': 0, '3': 0})
        d.setdefault('dalga', 0)
        return d

    def faction(self):
        return str(self.p.d['pilot'].get('factionId', 2))

    def info_cmd(self):
        s = self.st['puan']
        return ('InvasionEventInitCommand', {'score_MMO': int(s['1']), 'score_EIC': int(s['2']), 'score_VRU': int(s['3']),
                                             'waveCount': int(self.st['dalga'])})

    def on_map(self):
        return self.world is not None and int(self.world.map_id) in MAPS

    def login_msgs(self):
        return [self.info_cmd()] if active() else []

    def window(self, item):
        return [self.info_cmd()] if item == 'invasion' and active() else []

    def attach(self, world):
        self.world = world
        if self.on_map() and active():
            return [self.info_cmd()]
        return []

    def on_kill(self, w, npc, x, y):
        if not active() or int(w.map_id) not in MAPS or not getattr(npc, 'gate', False):
            return []
        with self.p.lock:
            self.st['puan'][self.faction()] += 1               # uzaylı başına firmaya 1 puan
            self.p.dirty = True
        return []

    def on_wave(self, key, total):
        """Dalga bitti (etkinlik kapısı): sayaç ve sıradaki saldırı dalgasının iletisi."""
        if key not in (D.get('kapilar') or {}):
            return []
        from legacy_protocol import legacy
        with self.p.lock:
            self.st['dalga'] = total
            self.p.dirty = True
        return [self.info_cmd(), legacy('0|A|STM|atk_wave_started|%%COUNT%%|%d' % (total + 1))]

    def tick(self, now):
        if not active(now):
            return self.event_end(now)
        if self.st.get('donem') is None:
            with self.p.lock:
                self.st['donem'] = (CAL.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        msgs = []
        if now >= self.next_score:                         # sanal puanlar: öteki firmalar ve oyuncunun firmasının sanal ekibi
            self.next_score = now + 60
            lo, hi = D.get('minute_points', [20, 60])
            with self.p.lock:
                for f in ('1', '2', '3'):
                    self.st['puan'][f] += random.randint(lo, hi)
                self.p.dirty = True
        if self.on_map() and now >= self.next_info:
            self.next_info = now + 30
            msgs.append(self.info_cmd())
        return msgs

    def event_end(self, now):
        """Etkinlik bitti: firmanın sırasına göre hasar boosterı (bir kez)."""
        st = self.p.d.get('istila')
        if not st or st.get('donem') is None:
            return []
        order = sorted(st['puan'], key=lambda f: -st['puan'][f])
        rank = order.index(self.faction())
        msgs = []
        rows = D.get('odul', [])
        if rank < len(rows):
            loot, hours = rows[rank]
            msgs += self.m.reward(loot, hours)
            self.log('   Invasion bitti: firma %d. (%s), ödül %s %d saat' % (rank + 1, st['puan'], loot, hours))
        with self.p.lock:
            self.p.d['istila'] = {}
            self.p.dirty = True
        return msgs
