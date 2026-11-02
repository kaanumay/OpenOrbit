"""Auto Mode session statistics (the panel shows the totals and the rates per hour) and a short journal of what the bot did."""
import time
from collections import deque

KEYS = ('kills', 'boxes', 'deaths', 'revives', 'jumps', 'ep', 'honor', 'credits', 'uridium', 'spent_credits', 'spent_uridium', 'sales', 'gates',
        'spent_uridium_gates')
JOURNAL = 50


class Stats:
    def __init__(self):
        self.reset(0)

    def reset(self, now):
        self.d = dict.fromkeys(KEYS, 0)
        self.d['started'] = now
        self.d['stop_reason'] = ''
        self.journal = deque(maxlen=JOURNAL)

    def __getitem__(self, k):
        return self.d.get(k, 0)

    def add(self, k, n=1):
        self.d[k] = self.d.get(k, 0) + n

    def note(self, text, now=None):
        self.journal.append((int(now or time.time()), text))

    def event(self, kind, kw):
        """Session events (extra_events): kills of the hero (not a group member's), boxes, income (gain: only what came in; spending
        is counted where the bot spends), jumps. Deaths, repairs, sales and gates are counted by the tasks."""
        if kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC' and not kw.get('group'):
            self.add('kills')
        elif kind in ('bonus', 'cargo'):
            self.add('boxes')
        elif kind == 'gain':
            for k in ('ep', 'honor', 'credits', 'uridium'):
                v = kw.get(k) or 0
                if v > 0:
                    self.add(k, v)
        elif kind == 'jump':
            self.add('jumps')

    def view(self):
        return dict(self.d, journal=list(self.journal))
