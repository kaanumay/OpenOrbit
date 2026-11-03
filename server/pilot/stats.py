"""Auto Mode session statistics (the panel shows the totals, the rates per hour and their curves) and a short journal of what the bot did.

Journal lines are kept as an English template with {0} placeholders and its values, so the panel shows them in its own language (pilot.js
PIL_NOTES lists every template); the server log gets the English text."""
import time
from collections import deque

KEYS = ('kills', 'boxes', 'deaths', 'revives', 'jumps', 'ep', 'honor', 'credits', 'uridium', 'spent_credits', 'spent_uridium', 'sales', 'gates',
        'spent_uridium_gates', 'spent_uridium_build')
CURVE = ('kills', 'credits', 'uridium', 'ep', 'honor')     # sampled for the panel's curves
SAMPLE_SEC = 60
SAMPLES = 240                 # four hours at one sample a minute (older samples are thinned out, see sample())
JOURNAL = 80


def text(key, args):
    try:
        return key.format(*args)
    except (IndexError, KeyError, ValueError):
        return key


class Stats:
    def __init__(self):
        self.reset(0)

    def reset(self, now):
        self.d = dict.fromkeys(KEYS, 0)
        self.d['started'] = now
        self.d['stop_reason'] = ''
        self.journal = deque(maxlen=JOURNAL)
        self.curve = [[0] + [0] * len(CURVE)] if now else []      # [seconds since the start, *CURVE totals]
        self.sampled = now

    def __getitem__(self, k):
        return self.d.get(k, 0)

    def add(self, k, n=1):
        self.d[k] = self.d.get(k, 0) + n

    def note(self, key, args=(), now=None):
        self.journal.append((int(now or time.time()), key, [a if isinstance(a, (int, float)) else str(a) for a in args]))

    def sample(self, now):
        """One point of the curves every SAMPLE_SEC (called every second); past SAMPLES points every other one is dropped, so a long
        session keeps its whole shape."""
        if not self.d['started'] or now - self.sampled < SAMPLE_SEC:
            return
        self.sampled = now
        self.curve.append([int(now - self.d['started'])] + [self.d[k] for k in CURVE])
        if len(self.curve) > SAMPLES:
            self.curve = self.curve[:1] + self.curve[1:-1:2] + self.curve[-1:]

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

    def view(self, now=None):
        now = now or time.time()
        live = [int(now - self.d['started'])] + [self.d[k] for k in CURVE] if self.d['started'] else None
        return dict(self.d, journal=list(self.journal), curve=self.curve + ([live] if live else []), curve_keys=list(CURVE))
