"""Fiesta Gate (Birthday 2025 window; roadmap Ö3; data data/extra_events.json 'fiesta').

Client (menu item birthday_2025, UI19thBirthdayGateSystem and UI19thGateTipsSystem):
  - Points window: Birthday2025PointRewardRequest {openWindow} -> Birthday2025PointRewardCommand {openWindow, curRewardLevel (level
    reached), curPoints / curLevelPoints (progress of the next level), lootShowCommandList [EventLootShowCommand {lootId,
    lootAmount, bg}] (rewards of the 50 levels; item = index + 1), claimedIndexes [claimed levels]}; Birthday2025ClaimRequest {rewardLevel;
    0 = all that can be claimed}.
  - Entry window (when jumping into the portal in X-1): Birthday2025GateWindowCommand {curLevel (highest open difficulty: 1, 2, 4, 8, 16),
    curLootAmount (coupon), commandList [Birthday2025GateRewardCommand {level, costAmount, costLootId, lootProbabilityModuleList
    [{lootId, minLootAmount, maxLootAmount, probabilityPercentage}], lootShowCommandList}]}; the "Go Now" button is
    enabled while level <= curLevel; Birthday2025GateEnterRequest {level}. Texts bday2025_*, ttip_jumpgate_bday2025.
Rules (official FAQ): from X-1 with a Galaxy Coupon; difficulties open in order (Tranquil 1 coupon / 5 AP ... Mythic 23 / 160); single life;
on failure the coupon is lost, the player returns to X-1; when the gate ends AP; AP fills the 50-level reward line.
The gates are in the event gate engine (event_gate.py): each difficulty is a gate (fiesta_1..5, maps 494-498); registered here.
In the profile: fiesta {ap, claimed [level], on (highest open difficulty)}.
"""
import json, os, time

import event_gate as EKP
import event_calendar as CAL
from galaxy_gates import screen

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('fiesta', {})
EVENT = 'fiesta'
COUPON = D.get('voucher', 'resource_collectable_galaxy-coupon')
BY_LEVEL = {z['level']: z for z in D.get('difficulties', [])}
BY_GATE = {z['gate']: z for z in D.get('difficulties', [])}
PORTAL_ID = EKP.PORTAL_BASE + 90                  # the single Fiesta portal in X-1 (with a window)
TITLE_TRANQUIL = 'title_fiestagate_dec2025'      # "Epoch Lit" (client text): on completing the Tranquil level

# the gates go to the event gate engine (imported before game.py EKP.register_npcs: alien types are registered too)
for _k, _g in (D.get('kapilar') or {}).items():
    EKP.GATES[_k] = _g
    for _m in _g['maps']:
        EKP.BY_MAP[int(_m)] = _k


def active(now=None):
    return EVENT in CAL.active(now)


def mod(name, **f):
    f['_'] = name
    return f


class Fiesta:
    REQUESTS = ('Birthday2025PointRewardRequest', 'Birthday2025ClaimRequest', 'Birthday2025GateEnterRequest')

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.change_map = None                    # the session binds: (target, portal, position)
        self.titles = None                        # the session binds: title_hunt.grant_title (Epoch Lit)
        event_gates.finish_hooks.append(self.on_finish)

    @property
    def st(self):
        d = self.p.d.setdefault('fiesta', {})
        for k, v in (('ap', 0), ('claimed', []), ('on', 1)):
            d.setdefault(k, v)
        return d

    # ------------------------------------------------------------ reward line
    def level(self):
        """(level reached, points in the next level, the next level's points)."""
        ap, lv = self.st['ap'], 0
        for row in D.get('track', []):
            if ap < row['ap']:
                return lv, ap, row['ap']
            ap -= row['ap']
            lv += 1
        last = D['track'][-1]['ap'] if D.get('track') else 1
        return lv, last, last

    def point_cmd(self, open_window):
        lv, cur, need = self.level()
        shows = [mod('EventLootShowCommand', lootId=r['items'][0][0] if r['items'] else '', bg='',
                     lootAmount=r['items'][0][1] if r['items'] else 0) for r in D.get('track', [])]
        return ('Birthday2025PointRewardCommand', dict(openWindow=bool(open_window), curRewardLevel=lv, curPoints=cur,
                                                       curLevelPoints=need, lootShowCommandList=shows,
                                                       claimedIndexes=sorted(self.st['claimed'])))

    def claim(self, level):
        lv = self.level()[0]
        todo = [l for l in range(1, lv + 1) if l not in self.st['claimed']] if level == 0 else \
            ([level] if 1 <= level <= lv and level not in self.st['claimed'] else [])
        msgs = []
        for l in todo:
            row = D['track'][l - 1]
            with self.p.lock:
                self.st['claimed'].append(l)
                self.p.dirty = True
            for loot, n in row['items']:
                msgs += self.m.prize(loot, n)
        if todo:
            self.log('   Fiesta Gate reward line: %s' % todo)
        return [self.point_cmd(False)] + msgs + self.m.money_msgs()

    # ------------------------------------------------------------ entry
    def gate_cmd(self):
        cmds = []
        for z in D.get('difficulties', []):
            g = D['kapilar'][z['gate']]
            o = g['reward']
            probs = [mod('LootProbabilityModule', lootId=l, minLootAmount=n, maxLootAmount=n, probabilityPercentage=round(c * 100, 3))
                     for l, n, c in o.get('chance', [])]
            shows = [mod('EventLootShowCommand', lootId=l, lootAmount=n, bg='') for l, n in o.get('items', [])]
            if o.get('ep'):
                shows.insert(0, mod('EventLootShowCommand', lootId='currency_experience', lootAmount=o['ep'], bg=''))
            cmds.append(mod('Birthday2025GateRewardCommand', level=z['level'], costAmount=z['voucher'], costLootId=COUPON,
                            lootProbabilityModuleList=probs, lootShowCommandList=shows))
        return ('Birthday2025GateWindowCommand', dict(curLevel=self.st['on'], curLootAmount=self.p.resource(COUPON), commandList=cmds))

    def portals(self, map_id, station):
        """The Fiesta portal with a window in X-1 (while the event runs)."""
        import map_links as H
        if not active() or H.map_class(map_id) != 'X-1' or not station:
            return []
        import galaxy_gates as KAPI
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2         # from the station toward the middle of the map, away from the generator gates
        x, y = int(sx + (cx - sx) * 0.3), int(sy + (cy - sy) * 0.3 + 900)
        return [dict(gateId=PORTAL_ID, x=x, y=y, target=0, designId=D.get('portal_design', 15), windowed='fiesta',
                     tooltip=D.get('tooltip', 'ttip_jumpgate_bday2025'))]

    def portal_window(self, g, w, go):
        """Jumped into the portal (under the world lock): the entry window."""
        w.send([self.gate_cmd()])

    def enter(self, level):
        z = BY_LEVEL.get(int(level))
        if not z or not active():
            return [self.gate_cmd()]
        if z['level'] > self.st['on']:
            return [self.gate_cmd(), screen('Clear the previous difficulty first.')]
        if self.p.resource(COUPON) < z['voucher']:
            return [self.gate_cmd(), screen('key:bday2025_entry_info')]
        self.p.add_resource(COUPON, -z['voucher'])
        self.k.enter(z['gate'])
        self.log('   Fiesta Gate %s: %d coupons' % (z['name'], z['voucher']))
        msgs = self.m.resource_msgs(COUPON, self.p.resource(COUPON), -z['voucher'])
        if self.change_map:
            self.change_map(z['map'], {'event_gate': True, 'gate': z['gate'], 'arrival': EKP.center(z['map'])}, None)
        return msgs

    def on_finish(self, key):
        """The gate ended (event_gate.finish): AP and the next difficulty open."""
        z = BY_GATE.get(key)
        if not z:
            return []
        before = self.level()[0]
        with self.p.lock:
            self.st['ap'] += z['ap']
            nxt = z['level'] * 2
            if nxt in BY_LEVEL and self.st['on'] < nxt:
                self.st['on'] = nxt
            self.p.dirty = True
        lv = self.level()[0]
        self.log('   Fiesta Gate %s ended: +%d AP (total %d, level %d)' % (z['name'], z['ap'], self.st['ap'], lv))
        msgs = [screen('+%d Activity Points' % z['ap'], big=True)]
        if z['order'] == 1 and self.titles:          # wiki: "Epoch Lit: Complete the Tranquil level"
            msgs += self.titles(TITLE_TRANQUIL)
        if lv > before:
            msgs.append(self.point_cmd(False))
        return msgs

    # ------------------------------------------------------------ requests
    def handle(self, name, f):
        if name == 'Birthday2025PointRewardRequest':
            return [self.point_cmd(f.get('openWindow'))] if active() or f.get('openWindow') else []
        if name == 'Birthday2025ClaimRequest':
            return self.claim(int(f.get('rewardLevel') or 0))
        if name == 'Birthday2025GateEnterRequest':
            return self.enter(f.get('level'))
        return []
