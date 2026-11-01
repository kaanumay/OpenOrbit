"""Event points, progress thresholds and end-of-event rewards (official Turkish forum: Hatching Out 129632, Blacklight Surge 145819,
Pirate Raid 133215, Universal 4 - Europa 177655; data in data/events.json 'scoring').

Fields of 'scoring' (all optional):
  npc        {npc_id: points or [on own company's map, on enemy map]}: ranking points; only the killer gets them
  progress   {npc_id: points}: progress points (Blacklight Surge's Progress Points); they also come from boxes: content line
             'olay_puani:<event>' (Hatching Out's Viral Boxes: VPP; world.grant_loot)
  gate       {gate: progress points}: when the gate is completed (Hatching Out: Alpha/Beta/Gamma 160 VPP; not in Dispatch, the double-reward day
             has no effect)
  thresholds [[progress, [[lootId, count], ...]], ...]: the reward when the threshold is reached (the client's EventProgress window is dead
             in 1.1.115: the reward is given directly, with an on-screen message)
  reset      true: progress restarts after the last threshold (Hatching Out: "the bar can reset"); otherwise once (Blacklight Surge)
  ranking    [{from_, e, items, title}]: when the event ends, a reward by rank (EventRewardConfirmationCommand); in single player the pilot with
             points is 1st (like Mimesis Mutiny); rank_metric 'participation': having logged in during the event instead of points (Europa:
             level and EP ranking, the single player is 1st)
  participation  {items, title}: to everyone who logged in while the event ran, when it ends (Europa: from the claim window)
The client's progress line is '0|LM|ST|EPP|n' ("You received n Progress Points."); the client has no display for ranking points.
In the profile: event_points {event: {period, points, progress, threshold, joined}} (deleted once the event has ended and the reward is given).
"""
import map_links as H
import event_calendar as CAL
import rankings as RK
from legacy_protocol import legacy
from galaxy_gates import screen

LOOT = 'olay_puani:'


def cfg(ev):
    return CAL.EVENTS.get(ev, {}).get('scoring')


def events():
    return [k for k in sorted(CAL.EVENTS) if cfg(k)]


def state(p, ev, now=None):
    """State of the period: starts from scratch when a new period begins (a finished event's stays until the reward is given)."""
    per = CAL.period(ev, now) if CAL.is_active(ev, now) else None
    root = p.d.setdefault('event_points', {})
    st = root.get(ev)
    if st is None or (per and st.get('period') != per[0]):
        with p.lock:
            st = root[ev] = dict(period=per[0] if per else None, points=0, progress=0, threshold=0, joined=False)
            p.dirty = True
    return st


def add(p, ev, n, give, now=None):
    """Progress points: the thresholds' rewards (give(lootId, count) -> messages) and the EPP line."""
    c = cfg(ev)
    if not c or n <= 0 or not CAL.is_active(ev, now):
        return []
    st = state(p, ev, now)
    with p.lock:
        st['progress'] += n
        p.dirty = True
    msgs = [legacy('0|LM|ST|EPP|%d' % n)]
    steps = c.get('thresholds', [])
    while st['threshold'] < len(steps) and st['progress'] >= steps[st['threshold']][0]:
        lim, items = steps[st['threshold']]
        with p.lock:
            st['threshold'] += 1
            p.dirty = True
        for loot, k in items:
            msgs += give(loot, k) if give else []
        msgs.append(screen('%s - %s points reached!' % (CAL.EVENTS[ev]['name'], format(lim, ',')), big=True))
        if st['threshold'] == len(steps) and c.get('reset'):             # Hatching Out: restart when the bar fills
            with p.lock:
                st['progress'] -= steps[-1][0]
                st['threshold'] = 0
    return msgs


def score(p, ev, n, now=None):
    if n > 0 and cfg(ev) and CAL.is_active(ev, now):
        st = state(p, ev, now)
        with p.lock:
            st['points'] += n
            p.dirty = True


def on_kill(p, map_id, npc_id, give, now=None):
    """Points for a killed alien (all active events with scoring)."""
    msgs, key = [], str(npc_id)
    for ev in events():
        c = cfg(ev)
        if not CAL.is_active(ev, now):
            continue
        pts = c.get('npc', {}).get(key)
        if isinstance(pts, list):                       # Blacklight Surge: double on one's own company's map (1-BL and 1-8 of MMO ...)
            pts = pts[0] if H.company(map_id) == p.d.get('pilot', {}).get('factionId') else pts[1]
        if pts:
            score(p, ev, pts, now)
        msgs += add(p, ev, c.get('progress', {}).get(key, 0), give, now)
    return msgs


def gate(p, key, give, now=None):
    """Gate completed (except Dispatch): the event's gate points."""
    return [m for ev in events() for m in add(p, ev, cfg(ev).get('gate', {}).get(key, 0), give, now)]


class EventPoints:
    """Session system (extra_events): kill points, participation and rewards when the event ends."""

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.titles = None                           # extra_events binds it (title_hunt.grant_title)
        self.next = 0.0

    def give(self, loot, n):
        return self.m.prize(loot, n) if self.m else []

    def on_kill(self, w, n, x, y):
        return on_kill(self.p, w.map_id, n.d.get('npc_id'), self.give)

    def tick(self, now):
        if now < self.next:
            return []
        self.next = now + 5.0
        msgs = []
        for ev in events():
            if CAL.is_active(ev, now):
                st = state(self.p, ev, now)
                if not st['joined']:
                    with self.p.lock:
                        st['joined'] = True
                        self.p.dirty = True
            elif ev in self.p.d.get('event_points', {}):
                msgs += self.finish(ev)
        return msgs

    def finish(self, ev):
        """Event ended: the participation and ranking reward once (single-player rank: 1st)."""
        c, st = cfg(ev), self.p.d['event_points'][ev]
        msgs = []
        k = c.get('participation') if st.get('joined') else None
        if k:
            for loot, n in k.get('items', []):
                msgs += self.give(loot, n)
            if k.get('title') and self.titles:
                msgs += self.titles(k['title'])
        ok = st.get('points', 0) > 0 or (c.get('rank_metric') == 'participation' and st.get('joined'))
        r = next((r for r in c.get('ranking', []) if r['from_'] <= 1 <= r['e']), None) if ok else None
        if r:
            for loot, n in r['items']:
                msgs += self.give(loot, n)
            if r.get('title') and self.titles:
                msgs += self.titles(r['title'])
            msgs.append(RK.confirmation(1, RK.DEFAULT_REWARD, r))
        self.log('   %s ended: points %d, progress %d%s' % (CAL.EVENTS[ev]['name'], st.get('points', 0), st.get('progress', 0),
                                                       ', 1st place reward' if r else ''))
        with self.p.lock:
            del self.p.d['event_points'][ev]
            self.p.dirty = True
        return msgs + (self.m.money_msgs() if msgs and self.m else [])
