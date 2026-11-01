"""The old Invasion: a company race (roadmap Ö3; data data/extra_events.json 'istila').

Client: the menu item invasion (window 68) shows InvasionEventInitCommand {score_MMO, score_EIC, score_VRU, waveCount}; texts
title_invasion, atk_wave_started (%COUNT%). Maps maps-config 61-69 (MMO / EIC / VRU Invasion).
Rules (2009 news, fandom): on the company's home map, on X-3 and on X-5 an Invasion gate by level range (5-9, 10-14, 15+);
inside only aliens, 22 waves (Streuner .. Boss Kucurbium) then from the start; you leave only by dying, repair is free; each alien gives the company
1 point; at the end of the event the top three companies get +10% / +5% / +3% damage for a week. Separate from the server's Compromising Invasion gate.
The gates run in the event gate engine (event_gate.py; rule company, level range, endless). The other companies' points are virtual.
Single-player adaptation: like the engine's other gates, an exit portal opens between waves (to leave without dying).
In the profile: invasion {period, points {1, 2, 3}, wave}.
"""
import json, os, random, time

import event_gate as EKP
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('invasion', {})
EVENT = 'invasion'
MAPS = {int(m): k for k, g in (D.get('kapilar') or {}).items() for m in g['maps']}

for _k, _g in (D.get('kapilar') or {}).items():           # before game.py EKP.register_npcs: the alien types are registered too
    EKP.GATES[_k] = _g
    for _m in _g['maps']:
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
        d = self.p.d.setdefault('invasion', {})
        d.setdefault('points', {'1': 0, '2': 0, '3': 0})
        d.setdefault('wave', 0)
        return d

    def faction(self):
        return str(self.p.d['pilot'].get('factionId', 2))

    def info_cmd(self):
        s = self.st['points']
        return ('InvasionEventInitCommand', {'score_MMO': int(s['1']), 'score_EIC': int(s['2']), 'score_VRU': int(s['3']),
                                             'waveCount': int(self.st['wave'])})

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
            self.st['points'][self.faction()] += 1               # 1 company point per alien
            self.p.dirty = True
        return []

    def on_wave(self, key, total):
        """Wave over (event gate): the counter and the message of the next attack wave."""
        if key not in (D.get('kapilar') or {}):
            return []
        from legacy_protocol import legacy
        with self.p.lock:
            self.st['wave'] = total
            self.p.dirty = True
        return [self.info_cmd(), legacy('0|A|STM|atk_wave_started|%%COUNT%%|%d' % (total + 1))]

    def tick(self, now):
        if not active(now):
            return self.event_end(now)
        if self.st.get('period') is None:
            with self.p.lock:
                self.st['period'] = (CAL.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        msgs = []
        if now >= self.next_score:                         # virtual points: the other companies and the virtual team of the player's company
            self.next_score = now + 60
            lo, hi = D.get('minute_points', [20, 60])
            with self.p.lock:
                for f in ('1', '2', '3'):
                    self.st['points'][f] += random.randint(lo, hi)
                self.p.dirty = True
        if self.on_map() and now >= self.next_info:
            self.next_info = now + 30
            msgs.append(self.info_cmd())
        return msgs

    def event_end(self, now):
        """Event over: a damage booster by the company's rank (once)."""
        st = self.p.d.get('invasion')
        if not st or st.get('period') is None:
            return []
        order = sorted(st['points'], key=lambda f: -st['points'][f])
        rank = order.index(self.faction())
        msgs = []
        rows = D.get('reward', [])
        if rank < len(rows):
            loot, hours = rows[rank]
            msgs += self.m.reward(loot, hours)
            self.log('   Invasion over: company rank %d (%s), reward %s %d hours' % (rank + 1, st['points'], loot, hours))
        with self.p.lock:
            self.p.d['invasion'] = {}
            self.p.dirty = True
        return msgs
