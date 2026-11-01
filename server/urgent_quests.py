"""Urgent Missions (Diminishing Quests; roadmap Ö3; data data/extra_events.json 'urgent_quests').

Client (menu item diminish_quests, UIDiminishingQuestSystem): DiminishingQuestInitializationCommand {quest QuestDefinitionModule,
timeToQuestEnd (sec), acceptabilityStatus {type}} shows the quest; acceptance is DiminishingQuestAcceptQuestRequest {questId,
acceptabilityStatus} -> DiminishingQuestAcceptQuestResponse {acceptabilityStatus, timeToQuestEnd}; removal is
DiminishingQuestRemoveQuestCommand {acceptabilityStatus}. States (AcceptabilityType): 0 NOT_ACCEPTABLE, 1 NOT_STARTED, 2 RUNNING,
3 COMPLETED, 4 DISABLED. Texts (flashres): diminishing_quest_available / _accepted / _completed / _expired /
_cannot_accept_outside_base. Progress of the conditions is QuestConditionUpdateCommand.
Rules (March 2022 update, player reports): it appears suddenly after hunting aliens for a long time without a break; it can be accepted only at the main base (or at the
Clan Battle Station); it disappears when its time runs out; the targets are ordinary aliens (e.g. 2 Streuner, 2 Lordakia, 2 Mordon).
In the original game the reward was to restore the "diminishing rewards"; since the server has no diminishing rewards, the quest gives its own reward (adaptation:
a multiple of the targets' rewards).
The menu item is visible only while a quest exists (user 2026-10-18, H140: the window opened with no quest was empty, two small images). The client
builds the menu's icons only at login and when a map loads (UIMainCenterNewSystem.ShowMenuList; RefreshMenuList event on scene
change): a WindowItemCommand that arrives during play only changes the item's data, it neither adds nor removes the icon. When a quest arrives the client opens
the window by flying it from the icon (DiminishingQuestHandler -> OpenWindow -> PlayFly: KeyNotFound if the icon is not in the dictionary, H110). When the menu is
built, the icon of a visible item is created, that of an invisible one is only hidden (it stays in MenuItemDic). So the server tracks whether the icon
was created in the session (icon): if created, the quest is shown at once; otherwise the quest waits, the item is reported visible and it is shown
at the next map load (ReadyRequest; the menu is rebuilt); its time starts when it is shown. When the quest ends the item is hidden;
the icon stays until the next build: if opened with no quest, the window is closed with WindowItemCommand and a short explanation appears.
(Not DiminishingQuestRemoveQuestCommand: when the client's handler removes the quest it closes the window and calls SetQuestInfo with an empty
quest, NullReferenceException; it also happens when a quest ends, harmless, a client defect.)
In the profile: urgent_quest {quest (definition), state, shown, end_time (when shown), value, rewards, counter (kills since the last quest), last}.
"""
import json, os, random, time

import map_links as H
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('urgent_quests', {})
EVENT = 'urgent_quests'
NOT_ACCEPTABLE, NOT_STARTED, RUNNING, COMPLETED, DISABLED = 0, 1, 2, 3, 4
QUEST_ID = 796000
ITEM = 'diminish_quests'                  # menu item
REBUILD_SEC = 2.0                          # allowance between a map load (ReadyRequest) and the menu being rebuilt
NO_QUEST_TEXT = 'No urgent mission right now. Urgent missions appear during long alien hunts.'


def active(now=None):
    return EVENT in CAL.active(now)


def mod(name, **f):
    f['_'] = name
    return f


def status(t):
    return mod('QuestAcceptabilityStatusModule', type=t)


def quest_def(qid, targets, rewards):
    """Kill quest (KILL_NPC conditions; all required)."""
    conds = []
    for i, (npc_id, n) in enumerate(targets):
        conds.append(mod('QuestElementModule', questCase=mod('QuestCaseModule', id=0, active=False, mandatory=False, ordered=False,
                                                             mandatoryCount=0, modifier=[]),
                         condition=mod('QuestConditionModule', id=qid * 10 + i + 1, matches=[str(npc_id)], type=6, displayType=6,
                                       targetValue=n, mandatory=True, subConditions=[],
                                       state=mod('QuestConditionStateModule', currentValue=0, active=True, completed=False))))
    return mod('QuestDefinitionModule', id=qid, types=[mod('QuestTypeModule', type=8)],
               rootCase=mod('QuestCaseModule', id=qid * 10, active=True, mandatory=True, ordered=False, mandatoryCount=len(conds),
                            modifier=conds),
               rewards=[mod('LootModule', lootId=l, amount=a, modifier='') for l, a in rewards],
               icons=[mod('QuestIconModule', icon=1)], textKeyFoundation='', portraitId='', star=0)


class UrgentQuests:
    REQUESTS = ('DiminishingQuestAcceptQuestRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.since = time.time()                   # uninterrupted play (start of the session)
        self.icon = None                           # whether the icon was created in the session (known at login; stays afterwards)
        self.vis_sent = None                       # visibility reported to the client (the item's data)
        self.rebuild_at = None                     # the moment the menu will be rebuilt (map load)
        self.win_open = False                      # window open (UIWindowUpdateRequest maximized)

    @property
    def st(self):
        return self.p.d.setdefault('urgent_quest', {})

    def attach(self, world):
        self.world = world
        return []

    # ------------------------------------------------------------ menu item
    def has_quest(self, now=None):
        """A pending or shown quest whose time has not run out."""
        q = self.st
        if not q.get('quest') or q.get('state') not in (NOT_STARTED, RUNNING):
            return False
        return not q.get('shown', True) or (time.time() if now is None else now) < q.get('end_time', 0)

    def menu_visible(self, now=None):
        """The item's visibility (player_profile.WINDOW_HOOKS): while the event runs and a quest exists."""
        return active(now) and self.has_quest(now)

    def sync(self, now=None):
        """WindowItemCommand if visibility changed (maximized False: closes an open window, does not open; the icon is built on the map)."""
        v = self.menu_visible(now)
        if self.vis_sent is None or self.vis_sent == v:
            return []
        self.vis_sent = v
        it = self.p.window_item(ITEM) if hasattr(self.p, 'window_item') else None
        return [('WindowItemCommand', dict(it, visible=v, maximized=False))] if it else []

    def on_ready(self):
        """Map loaded (ReadyRequest; other than the first login): the client will rebuild the menu with the reported visibility."""
        self.rebuild_at = time.time() + REBUILD_SEC
        return []

    def show(self, now):
        """Send the quest to the client (the window opens); the time of a pending quest starts now."""
        q = self.st
        fresh = not q.get('shown', True)
        if fresh:
            with self.p.lock:
                q['shown'] = True
                q['end_time'] = now + D.get('sure_sn', 1200)
                self.p.dirty = True
            self.log('   Urgent Mission: %s' % q.get('targets'))
        return self.sync(now) + [self.init_cmd(now)] + ([legacy('0|A|STM|diminishing_quest_available')] if fresh else [])

    def can_show(self):
        return self.icon is not False and self.rebuild_at is None     # icon None: no login happened (tests)

    # ------------------------------------------------------------ quest
    def make(self, now):
        """3 targets from the map's ordinary aliens (2-4 each)."""
        import world as world_module
        w = self.world
        rows = (world_module.CFG['maps'].get(str(w.map_id)) or {}).get('npc', []) if w else []
        T = world_module.CFG['types']
        kinds = [r['tip'] for r in rows if r['tip'] in T and T[r['tip']].get('npc_id') and not T[r['tip']].get('boss')]
        if not kinds:
            return None
        pick = random.sample(kinds, min(3, len(kinds)))
        targets = [(T[k]['npc_id'], random.randint(*D.get('count', [2, 4]))) for k in pick]
        mult = D.get('reward_multiplier', 3)
        tot = {'ep': 0, 'honor': 0, 'credits': 0, 'uridium': 0}
        for k, (npc_id, n) in zip(pick, targets):
            for a in tot:
                tot[a] += T[k].get('reward', {}).get(a, 0) * n * mult
        cur = {'ep': 'currency_experience', 'honor': 'currency_honour', 'credits': 'currency_credits', 'uridium': 'currency_uridium'}
        rewards = [(cur[a], int(v)) for a, v in tot.items() if v]
        qid = QUEST_ID + random.randint(1, 999)
        return dict(quest=quest_def(qid, targets, rewards), state=NOT_STARTED, shown=False, end_time=0, value={},
                    rewards=rewards, targets=[[k, n] for k, (_, n) in zip(pick, targets)])

    def init_cmd(self, now=None):
        # timeToQuestEnd is seconds (live: milliseconds showed 18 min as "12 Days 17 Hrs.")
        q = self.st
        now = time.time() if now is None else now
        return ('DiminishingQuestInitializationCommand', dict(quest=q['quest'], timeToQuestEnd=max(0, int(q['end_time'] - now)),
                                                              acceptabilityStatus=status(q['state'])))

    def login_msgs(self):
        """The ready bundle. At first login the menu was built with the item's visibility at that moment (UILayoutCommand, player_profile.WINDOW_HOOKS). The bundle is
        sent again at every map load: nothing is done there (the quest stays on the client; if sent again the window would reopen on every
        map); the menu rebuild is in on_ready."""
        if self.vis_sent is not None:
            return []
        now = time.time()
        self.icon = self.vis_sent = self.menu_visible(now)
        return self.show(now) if self.icon else []

    def on_kill(self, w, npc, x, y):
        return self.kill(npc.d.get('npc_id'))

    def kill(self, npc_id):
        """An alien died (itself or a group member on the same map; game.Session.quest_event) -> messages."""
        q = self.st
        with self.p.lock:
            q['counter'] = q.get('counter', 0) + 1
            self.p.dirty = True
        if q.get('state') != RUNNING:
            return []
        import quest_tracker as GT
        msgs, done = GT.advance(self.p, q['quest']['rootCase'], q['value'], 'kill', {'npc': npc_id, 'avatar': 'NPC'})
        if done:
            with self.p.lock:
                q['state'] = COMPLETED
                self.p.dirty = True
            for loot, n in q['rewards']:
                msgs += self.m.prize(loot, n, 'quest')
            msgs += [legacy('0|A|STM|diminishing_quest_completed'),
                     ('DiminishingQuestRemoveQuestCommand', {'acceptabilityStatus': status(COMPLETED)})] + self.m.money_msgs()
            self.log('   Urgent Mission completed: %s' % q['targets'])
            self.reset()
            msgs += self.sync()
        return msgs

    def reset(self):
        with self.p.lock:
            for k in ('quest', 'state', 'shown', 'end_time', 'value', 'rewards', 'targets'):
                self.st.pop(k, None)
            self.st['counter'] = 0
            self.st['last'] = time.time()
            self.p.dirty = True
        self.since = time.time()

    def tick(self, now):
        out = []
        if self.rebuild_at is not None and now >= self.rebuild_at:
            self.rebuild_at = None
            self.icon = bool(self.icon) or bool(self.vis_sent)    # if visible, the icon was created; a created icon stays even if hidden
        q = self.st
        if active(now) and q.get('quest'):
            if not q.get('shown', True):
                return out + (self.show(now) if self.can_show() else self.sync(now))
            if now >= q['end_time']:
                self.log('   Urgent Mission expired')
                self.reset()
                return out + [legacy('0|A|STM|diminishing_quest_expired'),
                              ('DiminishingQuestRemoveQuestCommand', {'acceptabilityStatus': status(NOT_ACCEPTABLE)})] + self.sync(now)
            return out
        out += self.sync(now)                          # the event started / ended
        if not active(now):
            return out
        w = self.world
        if not w or w.hero_dead or getattr(w, 'gate', None):
            return out
        if now - self.since < D.get('play_sec', 2700) or q.get('counter', 0) < D.get('kills', 150):
            return out
        if now - q.get('last', 0) < D.get('interval_sec', 3600):
            return out
        new = self.make(now)
        if not new:
            return out
        with self.p.lock:
            q.update(new)
            self.p.dirty = True
        if self.can_show():
            return out + self.show(now)
        self.log('   Urgent Mission waiting (no icon in the menu; when the map loads): %s' % new['targets'])
        return out + self.sync(now)

    def window_update(self, f):
        """Window opened (the client sends no UIButtonTriggerRequest for this window, only UIWindowUpdateRequest maximized True;
        it also comes on move/resize: only the closed-to-open transition)."""
        if f.get('itemId') != ITEM:
            return None
        opened = bool(f.get('maximized')) and not self.win_open
        self.win_open = bool(f.get('maximized'))
        return self.window(ITEM) if opened else None

    def window(self, item):
        """Window opened: a pending quest is shown at once; if there is no quest (icon of a finished quest) the window closes."""
        if item != ITEM:
            return None
        now = time.time()
        if self.has_quest(now) and not self.st.get('shown', True):
            return self.show(now)
        if not self.has_quest(now):
            import galaxy_gates as KAPI                    # screen text (MessageCommand; the client is English)
            it = self.p.window_item(ITEM) if hasattr(self.p, 'window_item') else None
            close = [('WindowItemCommand', dict(it, visible=False, maximized=False))] if it else []
            return close + [KAPI.screen(NO_QUEST_TEXT)]
        return None

    def handle(self, name, f):
        q = self.st
        if name != 'DiminishingQuestAcceptQuestRequest' or not q.get('quest') or q.get('state') != NOT_STARTED or \
                not q.get('shown', True):
            return []
        w = self.world
        home = w and w.in_station() and w.station and H.company(w.map_id) == self.p.d['pilot'].get('factionId')
        if not home:
            return [legacy('0|A|STM|diminishing_quest_cannot_accept_outside_base')]
        with self.p.lock:
            q['state'] = RUNNING
            self.p.dirty = True
        self.log('   Urgent Mission accepted')
        return [('DiminishingQuestAcceptQuestResponse', dict(acceptabilityStatus=status(RUNNING),
                                                              timeToQuestEnd=max(0, int(q['end_time'] - time.time())))),
                legacy('0|A|STM|diminishing_quest_accepted')]
