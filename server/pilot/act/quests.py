"""Auto Mode: the player's quests (quest.py, the session's Quests). Reads the active quests' open conditions (kill these aliens / visit
this map / return to the quest giver), takes a new quest at a quest giver and hands one in. The aliens' and maps' resolution is the bots'
(bot/goals/quest.py npc_types and map_list, bot/catalog map_npcs)."""
import math

import quest as QU
from bot import catalog as K
from bot.goals import quest as BQ

KILL = (6, 27)               # KILL_NPC and its counted variant
VISIT_MAP, ON_MAP, GIVER = 34, 77, 62


class Quests:
    def quest_book(self):
        return getattr(self.session, 'quest', None)

    def quest_goal(self, only=None):
        """The first open condition the bot can play (only: of that quest) -> dict(qid, name, kind: kill | visit | giver, aliens, maps)
        or None."""
        q = self.quest_book()
        if q is None:
            return None
        comp = self.company()
        for key, vals in list(q.st['active'].items()):
            qid = int(key)
            d = QU.QUESTS.get(qid)
            if not d or (only and qid != only):
                continue
            states = QU.evaluate(d['root'], vals)[0]
            for c in QU.conditions(d['root']):
                active, done = states.get(c['id'], (False, False))
                if not active or done or not c.get('mandatory', True):
                    continue
                base = dict(qid=qid, name=d.get('name', str(qid)))
                if c['type'] in KILL:
                    types = sorted({t for m in c.get('matches', []) for t in BQ.npc_types(m)})
                    if not types:
                        continue
                    maps = [m for sc in c.get('subConditions', []) if sc.get('type') == ON_MAP
                            for spec in sc.get('matches', []) for m in BQ.map_list(spec, comp)]
                    if not maps:
                        maps = [m for m in K.MAPS if any(v['tip'] in types for v, _ in K.map_npcs(m))]
                    maps = [m for m in dict.fromkeys(maps) if self.can_enter(m)]
                    if maps:
                        return dict(base, kind='kill', aliens=types, maps=maps)
                elif c['type'] == VISIT_MAP:
                    maps = [m for spec in c.get('matches', []) for m in BQ.map_list(spec, comp) if self.can_enter(m)]
                    if maps:
                        return dict(base, kind='visit', aliens=None, maps=maps[:1])
                elif c['type'] == GIVER:
                    return dict(base, kind='giver', aliens=None, maps=None)
        return None

    def active_quests(self):
        """The accepted quests for the panel's choice: [{id, name, playable (the bot can play its open condition)}]."""
        q = self.quest_book()
        if q is None:
            return []
        out = []
        for key in list(q.st['active']):
            qid = int(key)
            if qid in QU.QUESTS:
                out.append(dict(id=qid, name=QU.QUESTS[qid].get('name', str(qid)), playable=self.quest_goal(qid) is not None))
        return sorted(out, key=lambda x: x['name'])

    @staticmethod
    def quest_name(qid):
        return QU.QUESTS.get(int(qid), {}).get('name', str(qid))

    def quest_active(self, qid):
        q = self.quest_book()
        return q is not None and str(qid) in q.st['active']

    def quest_done(self, qid):
        q = self.quest_book()
        return q is not None and bool(q.done(qid))

    def quest_slots(self):
        q = self.quest_book()
        return q.free_slots() if q is not None else 0

    def go_to_giver(self, now):
        """Toward the nearest quest giver (this map's, else the base map's) -> 'here' | travel state."""
        w = self.w
        if w.near_giver:
            return 'here'
        if w.givers:
            hx, hy = w.hero_pos(now)
            gid, x, y = min(w.givers, key=lambda g: math.hypot(g[1] - hx, g[2] - hy))
            self.move_to(x, y, now)
            return 'moving'
        st = self.travel_to(self.home_map(), now)
        return 'no_route' if st == 'here' else st          # the base map has no quest giver either

    def accept_quest(self):
        """At a quest giver: the highest-level quest the bot can play that can be taken now -> its id or None."""
        q, w = self.quest_book(), self.w
        if q is None or not w.near_giver or not q.free_slots():
            return None
        offer = QU.offered()
        cands = sorted(BQ.quests().items(), key=lambda x: (-x[1]['level'], x[0]))
        for qid, _ in cands:
            if qid not in QU.QUESTS or q.status(qid)[0] != QU.NOT_STARTED or not q.visible(qid, offer):
                continue
            msgs = q.accept(qid)
            if str(qid) in q.st['active']:
                extra = getattr(self.session, 'quest_state_events', None)
                self.session.send(msgs + (extra() if extra else []), 'auto mode: quest accepted')
                return qid
        return None

    def hand_in(self):
        """At a quest giver: the "return to the quest giver" condition (game.py QuestGiverApproachedRequest)."""
        q = self.quest_book()
        if q is None or not self.w.near_giver:
            return False
        msgs = q.event('giver')
        if msgs:
            self.session.send(msgs, 'auto mode: quest giver')
        return True
