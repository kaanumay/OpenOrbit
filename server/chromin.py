"""Chromin Rush (roadmap stage 3; data in data/extra_events.json 'chromin' <- tools/extra_events.py).

Client: the menu item chrominEvent (window 67, UIChrominRushSystem) shows ChrominUpdateCommand {currentAmt, maxAmt}; the "GET NOW"
button is a web payment page (in single player, the shop's Chromin packs for uridium). Texts (chromin_ttip): Chromin drops from the
Galaxy Gate aliens, at most 160,000 are held; while the event runs, the part above the cap is converted to credits
(history_chromin_compensation), and when the event ends the remaining Chromin becomes honor (history_msg_event_chromin_honor_converted).
Chromin pays for Assembly's 49 event recipes (ON_SCHEDULE; the calendar's 'currency', assembly.event_recipes).

Sources: when aliens of the Delta, Epsilon, Zeta, Kappa and Kronos gates (galaxy_gates.py) die, a Chromin box drops with some probability
(CHROMIN_BOX_1..3, small/medium/large by amount; the client's box names are "Chromin"). The amount is the alien's strength (HP + shield)
as a fraction of the per-gate total (wiki ~2,700); once all of a gate's aliens are killed, the expected total is that much. All Chromin
inputs (box, pack, quest, GM) go through the shop's reward path: the cap is applied there (gain).
In the profile: chromin {period: timestamp when the event started, cap_warning: bool}.
"""
import json, os, random, time

import settings as SET
import galaxy_gates as KAPI
import ranks as RT
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('chromin', {})
LOOT = 'resource_collectable_chromin'
EVENT = 'chromin'
CAP = D.get('maximum', 160000)
CREDITS_PER = D.get('credit_ratio', 1)          # credits per Chromin over the cap
HONOR_PER = D.get('honor_ratio', 0.05)          # honor per Chromin left at the end of the event


def active(now=None):
    return EVENT in CAL.active(now)


def box_for(npc, gate):
    """The Chromin box of a gate alien -> (box type, amount) or None (the gate is not a Chromin gate)."""
    total = (D.get('kapilar') or {}).get(gate)
    if not total:
        return None
    strength = npc.d.get('hp', 0) + npc.d.get('kalkan', 0)
    n = max(1, int(round(D.get('per_gate', 2700) * strength / float(total) / max(0.01, D.get('probability', 1.0)))))
    kind = 'CHROMIN_BOX_1'
    for k, at in D.get('box_thresholds', []):
        if n >= at:
            kind = k
    return kind, n


class Chromin:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        return self.p.d.setdefault('chromin', {})

    def amount(self):
        return self.p.resource(LOOT)

    def update_cmd(self):
        return ('ChrominUpdateCommand', {'currentAmt': int(self.amount()), 'maxAmt': CAP})

    def login_msgs(self):
        return [self.update_cmd()] if active() or self.amount() else []

    def gain(self, n):
        """Chromin input (the shop's reward path): up to the cap into storage, the excess into credits while the event runs (the client's text)."""
        have = self.amount()
        room = max(0, CAP - have)
        got, extra = min(n, room), max(0, n - room)
        msgs = []
        if got:
            total = self.p.add_resource(LOOT, got)
            msgs += self.m.resource_msgs(LOOT, total, got)
        if active() and self.st.get('period') is None:
            with self.p.lock:
                self.st['period'] = CAL.period(EVENT)[0] if CAL.period(EVENT) else time.time()
                self.p.dirty = True
        if extra:
            cr = int(extra * CREDITS_PER)
            tot = self.p.gain(credits=cr, reason='chromin_compensation')
            msgs += self.m.money_msgs() + [legacy('0|LM|ST|CRE|%d|%d' % (cr, tot['credits']))]
            RT.note(self.p, 'history_chromin_compensation', count=cr)    # the client puts the count into %AMOUNT% (live round 2)
            self.log('   Chromin cap: %d excess converted to %d credits' % (extra, cr))
        if have + got >= CAP and not self.st.get('cap_warning'):
            with self.p.lock:
                self.st['cap_warning'] = True
                self.p.dirty = True
            msgs.append(legacy('0|A|STM|msg_event_chromin_max_quantity_reached'))
        return msgs + [self.update_cmd()]

    def on_kill(self, w, npc, x, y):
        """A Galaxy Gate alien died (under the world lock): a Chromin box while the event runs."""
        if not active() or int(w.map_id) not in KAPI.BY_MAP or npc.d.get('uncounted'):
            return []
        b = box_for(npc, KAPI.BY_MAP[int(w.map_id)])
        if not b or random.random() >= SET.chance('drop', D.get('probability', 1.0), 'event'):
            return []
        kind, n = b
        h = w.drop_box(kind, x, y, None, D.get('lifetime_sec', 300))
        w.boxes[h]['event'] = {'type': kind, 'mod': 'hepsi', 'guaranteed': [[LOOT, n]]}
        return []

    def tick(self, now):
        """The event ended: the remaining Chromin becomes honor (once); the cap warning is shown again in a new event."""
        if active(now) or self.st.get('period') is None:
            return []
        n = self.amount()
        msgs = []
        if n:
            hon = int(n * HONOR_PER)
            self.p.add_resource(LOOT, -n)
            tot = self.p.gain(honor=hon, reason='chromin_honor')
            msgs += self.m.resource_msgs(LOOT, 0, -n) + [legacy('0|LM|ST|HON|%d|%d' % (hon, tot['honor']))]
            RT.note(self.p, 'history_msg_event_chromin_honor_converted', count=hon)
            self.log('   Chromin Rush ended: %d Chromin -> %d honor' % (n, hon))
        with self.p.lock:
            self.st.clear()
            self.p.dirty = True
        return msgs + [self.update_cmd()]
