"""Pursuit of Prestige / Title Frenzy (roadmap Ö3; data in data/extra_events.json 'title_hunt').

Client (menu item titleFrenzy, window 116, UITitleFrenzySystem): TitleFrenzyInfoCommand {schedule TitleFrenzyScheduleUpdateCommand
{timeToNextWindow, timeToWindowEnd}, timeToEventEnd, titleKey, rankRewards [RankRewardRangeModule], npcIds}, TitleFrenzyOwnerUpdateCommand
{username, titleId, mapId} (who holds the title; the window's "Titles are currently on the following NPCs/Players" list),
TitleFrenzyRankingInfoCommand {isActive, myRank, prevRank, nextRank, rankingInfoList [{username, score, rank}]}; the ranking's reward
tab RankRewardRequest rankType 12 (rankings.py), Rankings' page RankingsEventsInfoRequest rankType 3. Texts:
log_msg_titlefrenzy_takeover (%NAME% %MAP%: on an alien), log_msg_titlefrenzy_playertakeover (on a player), titlefrenzy_window-*.
Rules (wiki hitac-assault): 4 Prestige titles on random Hitac Underlings (X-2..X-8); hours 07-09, 12-14, 18-20, 22-24;
whoever kills the alien carrying the title gets it; death, logging out, entering base or a gate, and holding for 30 min without interruption make
the title be lost (the title passes to another alien); the total holding time decides the ranking. While a title is held it shows above the ship (0|n|t).
Single-player adaptation: the rivals are virtual (the auction rivals' names); a virtual rival occasionally grabs the title on an alien, holds it
for a while and drops it; their scores accumulate this way too. If the title is on an alien on another map, not this one, it appears only
in the list; when the player gets to that map an Underling carries the title (with the title above the ship). Score: minutes held.
In the profile: title_hunt {period, points (min), titles {id: {owner: 'npc'|'player', map, class_name, name, start}}, rivals {name: score}}.
On a multiplayer server each player's titles are their own; a title on an alien of the shared map goes by the player's name (titles {name: id}):
so two players do not take the same Underling to be the carrier of their own title (a single n.title used to be shared). Other players on the server are in the ranking too.
"""
import json, os, random, time

import map_links as H
import rankings as RK
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('title_hunt', {})
EVENT = D.get('event', 'title_hunt')
RANK_TYPE = 12                                     # RankRewardRequest.RankType.TITLE_FRENZY
WINDOWS = [tuple(w) for w in D.get('hours', [[7, 9], [12, 14], [18, 20], [22, 24]])]
MAPS = D.get('maps', ['X-2', 'X-3', 'X-4', 'X-5', 'X-6', 'X-7', 'X-8'])
TITLE_KEY = D.get('title', 'title_titlefrenzy_event2026')
REWARD_TITLE = D.get('reward_title', 'title_titlefrenzy-aug2026-reward')
COUNT = D.get('count', 4)
HOLD_MAX = D.get('max_hold_sec', 1800)
CARRIER = D.get('carrier', 'event_hitac_underling_')
TITLE_ID_BASE = 1500                               # id of the title above the ship (the client shows the key)
if D.get('table'):
    RK.TABLES[RANK_TYPE] = D['table']


def register_titles():
    """The titles into the achievement table (the title above the ship, a reward title selectable in the achievement window)."""
    import achievement as ACV
    for i, key in enumerate((TITLE_KEY, REWARD_TITLE)):
        if key not in ACV.TITLES:
            ACV.TITLES[key] = TITLE_ID_BASE + i
            ACV.TITLE_KEYS[TITLE_ID_BASE + i] = key


def map_id(cls, faction):
    """The id of map X-n by company (map class -> id)."""
    return next((m for m, n in H.NAMES.items() if H.map_class(m) == cls and (H.company(m) in (None, faction))), 0)


def in_window(now=None):
    """(whether the window is ongoing, seconds left until the window's end/start)."""
    t = time.localtime(time.time() if now is None else now)
    h = t.tm_hour + t.tm_min / 60.0 + t.tm_sec / 3600.0
    for a, b in WINDOWS:
        if a <= h < b:
            return True, int((b - h) * 3600)
    nxt = min([a for a, b in WINDOWS if a > h] or [WINDOWS[0][0] + 24])
    return False, int((nxt - h) * 3600)


class TitleHunt:
    REQUESTS = ('RankingsEventsInfoRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.attached = 0.0                        # the moment the map opens (carriers are assigned a little later)
        self.shown = None                          # the opening whose titles are sent to the client (attached)
        self.was = None
        self.next_rival = 0.0
        self.base_title = None                     # the achievement's title above the ship (binds the session: achievement.title_msgs)
        register_titles()

    @property
    def st(self):
        d = self.p.d.setdefault('title_hunt', {})
        for k, v in (('points', 0.0), ('titles', {}), ('rivals', {})):
            d.setdefault(k, v)
        return d

    def enabled(self, now=None):
        """Pursuit of Prestige is ongoing and Hitac's Underlings are on the maps (Hitac Assault)."""
        cur = CAL.active(now)
        return EVENT in cur and 'hitac' in cur

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    # ------------------------------------------------------------ komutlar
    def owner_cmds(self):
        out = []
        for tid in range(1, COUNT + 1):
            t = self.st['titles'].get(str(tid))
            if not t:
                out.append(('TitleFrenzyOwnerUpdateCommand', {'username': '', 'titleId': tid, 'mapId': 0}))
                continue
            name = self.p.d['pilot'].get('userName', '') if t['owner'] == 'player' else t['name']
            out.append(('TitleFrenzyOwnerUpdateCommand', {'username': name, 'titleId': tid, 'mapId': t.get('map', 0)}))
        return out

    def schedule_cmd(self, now=None):
        on, left = in_window(now)
        # durations in seconds (live: when milliseconds were sent, 1 h 41 min showed as "70 Days 14 Hrs.")
        return {'_': 'TitleFrenzyScheduleUpdateCommand', 'timeToNextWindow': 0 if on else left,
                'timeToWindowEnd': left if on else 0}

    def info_cmd(self, now=None):
        return ('TitleFrenzyInfoCommand', dict(schedule=self.schedule_cmd(now), timeToEventEnd=CAL.time_left(EVENT, now),
                                               titleKey=TITLE_KEY, rankRewards=RK.ranges(RANK_TYPE), npcIds=D.get('npc_ids', [299])))

    def ranking(self):
        """The player, the server's other players and the virtual rivals, by score."""
        import community as TP
        rows = [(self.p.d['pilot'].get('userName', ''), self.st['points'] + self.held_minutes(), True)]
        for k in TP.all_().values():
            if k.profile is not self.p and (k.profile.d.get('title_hunt') or {}).get('period') == self.st.get('period'):
                o = TitleHunt.__new__(TitleHunt)
                o.p = k.profile
                rows.append((k.name, (k.profile.d['title_hunt'].get('points') or 0.0) + o.held_minutes(), False))
        rows += [(n, s, False) for n, s in self.st['rivals'].items()]
        rows.sort(key=lambda r: -r[1])
        return rows

    def ranking_cmd(self):
        rows = self.ranking()
        mod = lambda i: None if i < 0 or i >= len(rows) else {'_': 'TitleFrenzyRankingInfoModule', 'username': rows[i][0],
                                                              'score': round(float(rows[i][1]), 1), 'rank': i + 1}
        me = next(i for i, r in enumerate(rows) if r[2])
        return ('TitleFrenzyRankingInfoCommand', dict(isActive=self.enabled(), myRank=mod(me), prevRank=mod(me - 1),
                                                      nextRank=mod(me + 1),
                                                      rankingInfoList=[mod(i) for i in range(min(len(rows), D.get('entries', 10)))]))

    def login_msgs(self):
        if not self.enabled():
            return []
        msgs = [self.info_cmd()] + self.owner_cmds()          # the ranking only when Rankings opens (goes to Hall of Fame's UI;
        return msgs + self.ship_title_msgs()                   # InitRankingUI gave an error while the window was closed: live round Ö3)

    def window(self, item):
        """Window opened (UIButtonTriggerRequest titleFrenzy)."""
        if item != 'titleFrenzy' or not self.enabled():
            return []
        return [self.info_cmd()] + self.owner_cmds()

    def handle(self, name, f):
        if name == 'RankingsEventsInfoRequest' and int(f.get('rankType') or 0) == 3:
            return [self.ranking_cmd()]
        return []

    # ------------------------------------------------------------ titles
    def held(self):
        return [tid for tid, t in self.st['titles'].items() if t['owner'] == 'player']

    def held_minutes(self, now=None):
        now = time.time() if now is None else now
        return sum(max(0, now - t['start']) for t in self.st['titles'].values() if t['owner'] == 'player') / 60.0

    def ship_title_msgs(self):
        """The title above the ship: the Prestige title while a title is held, otherwise the achievement's selected title (achievement.title_msgs)."""
        if self.held():
            return [legacy('0|n|t|%d|%d|%s' % (self.p.user_id, TITLE_ID_BASE, TITLE_KEY))]
        return []

    def to_npc(self, tid, avoid=None, now=None):
        """The title passes to an Underling on a random map."""
        cls = random.choice([m for m in MAPS if m != avoid] or MAPS)
        name = D.get('carrier_name', 'Hitac-Underling')
        with self.p.lock:
            self.st['titles'][str(tid)] = {'owner': 'npc', 'map': map_id(cls, self.faction()), 'class_name': cls, 'name': name,
                                             'start': time.time() if now is None else now}
            self.p.dirty = True
        return [self.owner_one(tid), legacy('0|A|STM|log_msg_titlefrenzy_takeover|%%NAME%%|%s|%%MAP%%|%s' % (name, cls))]

    def owner_one(self, tid):
        return next(m for m in self.owner_cmds() if m[1]['titleId'] == int(tid))

    def drop(self, why, now=None):
        """The player loses titles (death, logout, base, gate, 30 min): time to score, the title to another alien."""
        now = time.time() if now is None else now
        msgs = []
        for tid in self.held():
            t = self.st['titles'][tid]
            gained = max(0, now - t['start']) / 60.0
            with self.p.lock:
                self.st['points'] += gained
                self.p.dirty = True
            self.log('   Prestige title %s dropped (%s): +%.1f min' % (tid, why, gained))
            msgs += self.to_npc(tid, avoid=t.get('class_name'), now=now)
        if msgs:
            msgs += self.title_reset_msgs()
        return msgs

    def title_reset_msgs(self):
        """The Prestige title is gone: the achievement's selected title (none if no title)."""
        base = self.base_title() if self.base_title else []
        return base or [legacy('0|n|t|%d|0|' % self.p.user_id)]

    def attach(self, world):
        """Map opened: the carriers of the titles here are assigned in tick (live: at attach the map's aliens had not been
        restored yet, the title passed to no Underling)."""
        self.world = world
        self.attached = time.time()
        return []

    def mark(self, n):
        """This player's title carried by the alien, or None."""
        return (getattr(n, 'titles', None) or {}).get(self.key)

    @property
    def key(self):
        return str(self.p.d['pilot'].get('userName', '')).strip().lower()

    def carriers(self, now):
        """Titles on this map without a carrier go to an Underling (with the title above the ship) -> messages."""
        w = self.world
        if not w or now - self.attached < 2.0:            # after the aliens are created on the client
            return []
        cls = H.map_class(w.map_id)
        mine = [tid for tid, t in self.st['titles'].items() if t['owner'] == 'npc' and t.get('class_name') == cls]
        if not mine:
            return []
        msgs = []
        with w.lock:
            if self.shown != self.attached:         # the map was re-entered: the returning carriers' title is not on the client
                self.shown = self.attached
                msgs += [legacy('0|n|t|%d|%d|%s' % (n.id, TITLE_ID_BASE, TITLE_KEY))
                         for n in w.npcs.values() if n.alive and self.mark(n) in mine]
            have = {self.mark(n) for n in w.npcs.values() if n.alive}
            free = [n for n in w.npcs.values() if n.alive and n.tip.startswith(CARRIER) and not getattr(n, 'titles', None)]
            for tid, n in zip([tid for tid in mine if tid not in have], free):
                n.titles = dict(getattr(n, 'titles', None) or {}, **{self.key: tid})
                msgs.append(legacy('0|n|t|%d|%d|%s' % (n.id, TITLE_ID_BASE, TITLE_KEY)))
        return msgs

    def on_kill(self, w, npc, x, y):
        tid = self.mark(npc)
        if not tid or not self.enabled():
            return []
        t = self.st['titles'].get(tid)
        if not t or t['owner'] != 'npc':
            return []
        with self.p.lock:
            self.st['titles'][tid] = {'owner': 'player', 'map': int(w.map_id), 'class_name': H.map_class(w.map_id), 'name': '',
                                         'start': time.time()}
            self.p.dirty = True
        name = self.p.d['pilot'].get('userName', '')
        self.log('   Prestige title %s taken (%s)' % (tid, H.name(w.map_id)))
        return [self.owner_one(tid), legacy('0|A|STM|log_msg_titlefrenzy_playertakeover|%%NAME%%|%s|%%MAP%%|%s' % (name, H.name(w.map_id)))] \
            + self.ship_title_msgs()

    # ------------------------------------------------------------ time
    def start_window(self, now):
        msgs = []
        with self.p.lock:
            self.st['titles'] = {}
            self.p.dirty = True
        for tid in range(1, COUNT + 1):
            msgs += self.to_npc(tid, now=now)
        if self.world:
            self.attach(self.world)
        return msgs + [self.info_cmd(now)]

    def end_window(self, now):
        msgs = self.drop('pencere bitti', now)
        with self.p.lock:
            self.st['titles'] = {}
            self.p.dirty = True
        return msgs + [self.info_cmd(now)] + self.owner_cmds()

    def rivals_tick(self, now):
        """Virtual rivals: occasionally grab the title on an alien, hold it for a while and drop it; their scores accumulate."""
        if now < self.next_rival:
            return []
        self.next_rival = now + 60
        import auction as MZ
        msgs = []
        for tid, t in list(self.st['titles'].items()):
            if t['owner'] == 'rival' and now - t['start'] >= t.get('duration', 600):
                with self.p.lock:
                    self.st['rivals'][t['name']] = self.st['rivals'].get(t['name'], 0.0) + (now - t['start']) / 60.0
                    self.p.dirty = True
                msgs += self.to_npc(tid, avoid=t.get('class_name'), now=now)
            elif t['owner'] == 'npc' and random.random() < D.get('rival_capture', 0.08):
                name = '%s%s' % (random.choice(MZ.R['names']), random.choice(MZ.R['attachments']))
                with self.p.lock:
                    self.st['titles'][tid] = dict(t, owner='rival', name=name, start=now, duration=random.randint(*D.get('rival_duration', [300, 1500])))
                    self.p.dirty = True
                msgs.append(self.owner_one(tid))
        return msgs

    def tick(self, now):
        if not self.enabled(now):
            return self.event_end(now)
        if self.st.get('period') is None:
            with self.p.lock:
                self.st['period'] = (CAL.period(EVENT, now) or (now,))[0]
                self.p.dirty = True
        on = in_window(now)[0]
        msgs = []
        if self.was is not None and on != self.was:
            msgs += self.start_window(now) if on else self.end_window(now)
        elif self.was is None and on and not self.st['titles']:
            msgs += self.start_window(now)
        self.was = on
        if on:
            msgs += self.carriers(now)
            msgs += self.rivals_tick(now)
            for tid in self.held():                        # 30 dk kesintisiz tutma
                if now - self.st['titles'][tid]['start'] >= HOLD_MAX:
                    msgs += self.drop('30 dk', now)
                    break
            w = self.world
            if self.held() and w and (w.in_station() or getattr(w, 'gate', None)):
                msgs += self.drop('üs/kapı', now)
        return msgs

    def event_end(self, now):
        """Event ended: reward by ranking (once) and the state is reset."""
        if self.st.get('period') is None:
            return []
        msgs = self.drop('etkinlik bitti', now)
        rank = next(i + 1 for i, r in enumerate(self.ranking()) if r[2])
        t = RK.TABLES.get(RANK_TYPE) or {}
        r = next((r for r in t.get('ranges', []) if r['from_'] <= rank <= r['e']), None)
        if r and self.st['points'] > 0:
            for loot, n in r['items']:
                msgs += self.m.prize(loot, n)
            if r.get('title'):
                msgs += self.grant_title(r['title'])
            msgs.append(RK.confirmation(rank, RK.DEFAULT_REWARD, r))           # Title Frenzy is not in RewardType
            self.log('   Pursuit of Prestige ended: rank %d (%.1f min), reward %s' % (rank, self.st['points'], r['items']))
        with self.p.lock:
            self.p.d['title_hunt'] = {}
            self.p.dirty = True
        return msgs + self.m.money_msgs()

    def grant_title(self, key):
        import achievement as ACV
        st = ACV.state(self.p)
        ACV.title_id(key)                                  # so it can be selected in the achievement window (an event title not in the table)
        if key not in st['titles']:
            with self.p.lock:
                st['titles'].append(key)
                self.p.dirty = True
        # the client has no "title received" text; since the LOT line looks up the name in the item source it wrote "You received ." to the logbook
        # (live round 2): the line is not sent, the title is selected in the achievement window
        return []
