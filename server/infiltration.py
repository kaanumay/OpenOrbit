"""Infiltration (roadmap Ö3; data data/extra_events.json 'infiltration').

Client: the menu item infiltration (window 87, "Infiltration Game") shows InfiltrationStatusCommand {currentNpcs (remaining), maxNpcs,
secondsRemaining} ("Infiltrators killed: %COUNT%"). Texts (flashres): msg_infiltration_spawned_map_single (%MAP%),
msg_infiltration_success, msg_infiltration_defeat. The hidden ship uses ShipCreateCommand.cloaked; becoming visible is 0|n|INV|<id>|0.
Rules (official FAQ 2013, fandom): a hidden commando team appears on a random company map (not X-1); it must be found and destroyed in 10 minutes,
otherwise it escapes. The commandos do not shoot, a yellow dot on the minimap; when hit (or by EMP) they become visible; they give more reward than
a normal alien (2x; sources say 2x/4x). In the evening hours (19-22) rounds follow one another; Thanksgiving week.
Single-player adaptation: the team is on one of the player's company's X-2..X-8 maps; if the player is on that map (or arrives later)
the remaining commandos spawn at a random place on the map. Team size, time between rounds and alien types are in the data (_uyarlama); with the
'hidden_boss' probability of the round one of the commandos is a hidden Boss Kristallon (the loot of the Uber Kristallon; fandom Infiltration).
Company ranking (official Turkish forum Infiltration FAQ: "will appear in the sidebar"; the company that destroys the team gets points): UpdateEventSummaryScoreCommand
{scoreCommandList: [EventSummaryScoreCommand {score, factionModule}], eventEnd, eventType 'Infiltration'} (the client's UIScoreSystem
shows the sidebar_infiltration_title_long title for this type; il2cpp 1.1.115). The player's company gets +1 for every team it destroys; the other
companies are virtual: at the end of every round +1 with 50% probability (adaptation). Scores are in the profile, per event period; rounds are per session.
"""
import json, os, random, time

import map_links as H
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('infiltration', {})
EVENT = 'infiltration'


def active(now=None):
    return EVENT in CAL.active(now)


def in_slot(now=None):
    t = time.localtime(time.time() if now is None else now)
    h = t.tm_hour + t.tm_min / 60.0
    return any(a <= h < b for a, b in D.get('hours', [[19, 22]]))


class Infiltration:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.round = None                          # {map, class_name, kinds, count, killed, end_time, spawned}
        self.next_round = 0.0
        self.outside = 0                          # commandos killed by the other players on the shared map (on_kill; tick counts)

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    def scores(self, now=None):
        """The company scores of this event period {'1','2','3'} (zero when the period changes)."""
        span = CAL.period(EVENT, now)
        d = self.p.d.setdefault('infiltration', {})
        if span and d.get('period') != int(span[0]):
            d.update(period=int(span[0]), points={'1': 0, '2': 0, '3': 0})
            self.p.dirty = True
        return d.setdefault('points', {'1': 0, '2': 0, '3': 0})

    def score_cmd(self, now=None):
        s = self.scores(now)
        return ('UpdateEventSummaryScoreCommand', {'eventType': 'Infiltration', 'eventEnd': False, 'scoreCommandList': [
            {'_': 'EventSummaryScoreCommand', 'score': int(s[f]), 'factionModule': {'_': 'FactionModule', 'faction': int(f)}}
            for f in ('1', '2', '3')]})

    def round_over(self, won, now=None):
        """Round over: if won, +1 to the player's company; the other companies are virtual (50%) -> sidebar."""
        s = self.scores(now)
        with self.p.lock:
            if won:
                s[str(self.faction())] = int(s.get(str(self.faction()), 0)) + 1
            for f in ('1', '2', '3'):
                if f != str(self.faction()) and random.random() < 0.5:
                    s[f] = int(s.get(f, 0)) + 1
            self.p.dirty = True
        return [self.score_cmd(now)]

    def status_cmd(self, now=None):
        r = self.round
        now = time.time() if now is None else now
        if not r:
            return ('InfiltrationStatusCommand', {'currentNpcs': 0, 'maxNpcs': 0, 'secondsRemaining': 0})
        # currentNpcs = remaining commandos (the client writes the "killed" count as maxNpcs - currentNpcs; live)
        return ('InfiltrationStatusCommand', {'currentNpcs': r['count'] - r['killed'], 'maxNpcs': r['count'],
                                              'secondsRemaining': max(0, int(r['end_time'] - now))})

    def map_for(self, cls):
        return next((m for m, n in H.NAMES.items() if H.map_class(m) == cls and H.company(m) == self.faction()), 0)

    def start_round(self, now):
        cls = random.choice(D.get('maps', ['X-2', 'X-3', 'X-4', 'X-5', 'X-6', 'X-7', 'X-8']))
        pool = D.get('kinds', ['75', '73', '76', '78', '81'])
        n = D.get('count', 6)
        kinds = [random.choice(pool) for _ in range(n)]
        boss = D.get('hidden_boss')
        if boss and random.random() < boss['probability']:      # hidden Boss Kristallon: in place of one commando (the loot of the Uber Kristallon)
            kinds[random.randrange(n)] = boss['type']
        self.round = dict(map=self.map_for(cls), class_name=cls, kinds=kinds, count=n, killed=0,
                          end_time=now + D.get('duration_sec', 600), spawned=False)
        self.log('   Infiltration: commando team %s (%d)' % (H.name(self.round['map']), n))
        msgs = [legacy('0|A|STM|msg_infiltration_spawned_map_single|%%MAP%%|%s' % H.name(self.round['map'])), self.status_cmd(now)]
        if self.world and int(self.world.map_id) == self.round['map']:
            self.spawn(self.world)
        return msgs

    def spawn(self, w):
        """The team's remaining commandos on this map (under the world lock or in attach)."""
        r = self.round
        if not r or r['spawned'] or int(w.map_id) != r['map']:
            return
        r['spawned'] = True
        mw, mh = H.map_size(w.map_id)
        cx, cy = random.randint(int(mw * 0.15), int(mw * 0.85)), random.randint(int(mh * 0.15), int(mh * 0.85))
        r['ids'] = []
        for tip in r['kinds'][r['killed']:]:
            if tip not in w.CFG_TYPES:
                continue

            def prep(n):
                n.hidden = True
                n.reward_multiplier = D.get('reward_multiplier', 2)
                n.infiltration = self                     # the team's owner (on a friend server the other player can hit it too)
                n.passive = True                     # commandos do not shoot (official FAQ 2013)
                n.summoned = tip == D.get('hidden_boss', {}).get('type')       # the hidden boss does not respawn when it dies (the event's map check does not delete it either)
            n = w.spawn_npc_at(tip, cx + random.randint(-400, 400), cy + random.randint(-400, 400), prep=prep)
            if n is not None:
                n.engaged = False
                r['ids'].append(n.id)

    def attach(self, world):
        self.world = world
        if self.round and active():
            self.spawn(world)
            return [self.status_cmd(), self.score_cmd()]
        return [self.score_cmd()] if active() else []

    def login_msgs(self):
        return [self.status_cmd(), self.score_cmd()] if active() else []

    def on_kill(self, w, npc, x, y):
        owner = getattr(npc, 'infiltration', None)
        if owner is not self:
            if owner is not None:                # the other player's team: the counter is theirs, the messages in their round (tick)
                owner.outside += 1
            return []
        return self.killed()

    def killed(self):
        r = self.round
        if not r:
            return []
        r['killed'] += 1
        if r['killed'] >= r['count']:
            r['end_time'] = time.time()             # the counter stops, the window shows the final state (n/n)
        msgs = [self.status_cmd()]
        if r['killed'] >= r['count']:
            self.log('   Infiltration: team destroyed')
            msgs.append(legacy('0|A|STM|msg_infiltration_success'))
            self.round = None
            self.next_round = time.time() + D.get('interval_sec', 120)
            msgs += self.round_over(True)
        return msgs

    def tick(self, now):
        msgs = []
        while self.outside > 0:
            self.outside -= 1
            msgs += self.killed()
        if msgs:
            return msgs
        if not active(now):
            self.round = None
            return []
        r = self.round
        if r and now >= r['end_time']:
            self.log('   Infiltration: team escaped (%d/%d)' % (r['killed'], r['count']))
            msgs = [legacy('0|A|STM|msg_infiltration_defeat')]
            w = self.world
            if w and r.get('ids'):
                with w.lock:
                    for uid in r['ids']:
                        n = w.npcs.get(uid)
                        if n and n.alive:
                            w.send(w.remove_npc(n))        # team escaped
            self.round = None
            self.next_round = now + D.get('interval_sec', 120)
            return msgs + [self.status_cmd(now)] + self.round_over(False, now)
        if not r and in_slot(now) and now >= self.next_round:
            return self.start_round(now)
        return []
