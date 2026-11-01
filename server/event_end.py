"""Currencies left over at the end of an event become honor (roadmap E3; Chromin in chromin.py, Infiltrator Fragment in world_boss.py).

The client's history texts (history_msg_event_*_honor_converted): Battle Pass Key, Candy Corn and Golden Candy Corn (halloweenoct2020),
Luminium, Styxus and Charopos Shard (valentine). Rates: Candy Corn 1, Golden Candy Corn 20,000 (darkorbitwiki Trial of Terrors),
Luminium 1 and at most 10,000 honor (wiki Empyrian March), Battle Pass Key 5,000 (Immortal Union FAQ); the rate of the Valentine
shards is unknown (adaptation 1). The official server converts after 24-48 hours; here when the event ends (in the session's first step).
Byte Remnant (Mimesis Mutiny) is not converted to honor: it is deleted from the inventory 24 hours after the event ends (wiki; LATER).
In the profile: event_end {event: timestamp the period started} (those seen while the event was running); event_cleanup {event: the period's
end} (those in LATER).
"""
import event_gate as EKP
import ranks as RT
import event_calendar as CAL
from legacy_protocol import legacy

# event -> [(history text, {lootId: honor rate}, honor limit)]
CONVERT = {
    'halloween': [('history_msg_event_halloweenoct2020_honor_converted',
                   {'resource_collectable_candy-corn': 1, 'resource_collectable_golden-candy-corn': 20000}, None)],
    'empyrian': [('history_msg_event_luminium_honor_converted', {'resource_collectable_luminium': 1}, 10000)],
    'immortal_union': [('history_msg_event_valentine_honor_converted',
                        {'resource_collectable_styxus-shard': 1, 'resource_collectable_charopos-shard': 1}, None)],
}
# event -> CPUs deleted from the inventory when it ends (wiki: "Use your Bountiful Alien CPUs before the event ends as they will be removed")
REMOVE = {}
for _loot, _c in EKP.D.get('cpu', {}).items():
    REMOVE.setdefault(_c['event'], []).append(_loot)
    CONVERT.setdefault(_c['event'], [])
# event -> (how many seconds after the end, the resources deleted): darkorbitwiki mimesis-mutiny "Byte Remnant ... removed 24 hours after the event ends"
LATER = {'mimesis_mutiny': (24 * 3600, ['resource_collectable_byte-remnant'])}
# event -> (title, rank score): when it ends the top 10 (score > 0) get the title. Frozen Labyrinth Synk hunt: Elite Marksman
# (official Turkish forum winter FAQ 1452398, Frozen Labyrinth 2019 1300061)
TITLES = {'labyrinth': ('title_frozenLabyrinth-marksman', lambda x: int((x.d.get('labyrinth') or {}).get('hunts', 0)))}
for _k in TITLES:
    CONVERT.setdefault(_k, [])
BPK = ('history_msg_event_battle_pass_key_honor_converted', {'resource_battle-pass-key': 5000}, None)
for _k, _e in CAL.EVENTS.items():                  # keys left over in every event with a Battle Pass (battle_pass.py; E8)
    if 'BattlePass' in _e.get('kinds', []):
        CONVERT.setdefault(_k, []).append(BPK)


class EventEnd:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        return self.p.d.setdefault('event_end', {})

    @property
    def late(self):
        return self.p.d.setdefault('event_cleanup', {})

    def delayed(self, now):
        """LATER: while the event runs the end time is written; when the time is up the resources are deleted (not converted to honor)."""
        msgs = []
        for ev, (wait, loots) in LATER.items():
            if CAL.is_active(ev, now):
                end = (CAL.period(ev, now) or (now, now))[1]
                if self.late.get(ev) != end:
                    with self.p.lock:
                        self.late[ev] = end
                        self.p.dirty = True
            elif ev in self.late and now >= self.late[ev] + wait:
                for loot in loots:
                    n = self.p.resource(loot)
                    if n > 0:
                        self.p.add_resource(loot, -n)
                        msgs += self.m.resource_msgs(loot, 0, -n)
                        self.log('   %s ended: %s x%d deleted after %d hours' % (CAL.EVENTS[ev]['name'], loot, n, wait // 3600))
                with self.p.lock:
                    del self.late[ev]
                    self.p.dirty = True
        return msgs

    def tick(self, now):
        msgs = self.delayed(now)
        for ev, rows in CONVERT.items():
            if CAL.is_active(ev, now):
                if ev not in self.st:
                    with self.p.lock:
                        self.st[ev] = (CAL.period(ev, now) or (now,))[0]
                        self.p.dirty = True
                continue
            if ev not in self.st:
                continue
            for text, rates, cap in rows:
                held = {loot: self.p.resource(loot) for loot in rates}
                hon = sum(n * rates[loot] for loot, n in held.items() if n > 0)
                if not hon:
                    continue
                hon = min(hon, cap) if cap else hon
                for loot, n in held.items():
                    if n > 0:
                        self.p.add_resource(loot, -n)
                        msgs += self.m.resource_msgs(loot, 0, -n)
                tot = self.p.gain(honor=hon, reason='event_honor')
                msgs.append(legacy('0|LM|ST|HON|%d|%d' % (hon, tot['honor'])))
                RT.note(self.p, text, count=hon)        # the client puts count into %AMOUNT%, it does not look at args (live round 2)
                self.log('   %s ended: %s -> %d honor' % (CAL.EVENTS[ev]['name'], {k: n for k, n in held.items() if n > 0}, hon))
            for loot in REMOVE.get(ev, ()):
                n = self.p.ammo(loot)
                if n > 0:
                    with self.p.lock:
                        self.p.d['ammunition'].pop(loot, None)
                        self.p.dirty = True
                    msgs += self.m.resource_msgs(loot, 0, -n)
                    self.log('   %s ended: %s x%d deleted' % (CAL.EVENTS[ev]['name'], loot, n))
            if ev in TITLES:
                title, score = TITLES[ev]
                import community as TP
                top, me = TP.ranking(self.p, score)
                if score(self.p) > 0 and (me[0] or 1) <= 10:
                    RT.grant_title(self.p, title)
                    self.log('   %s ended: title %s' % (CAL.EVENTS[ev]['name'], title))
            with self.p.lock:
                del self.st[ev]
                self.p.dirty = True
        return msgs
