"""Auto Mode: the player's quests (quest.py, the session's Quests). Reads the active quests' open conditions, takes a new quest at a quest
giver and hands one in. The aliens are resolved like the bots' (bot/goals/quest.py npc_types, bot/catalog map_npcs), the maps by
quest.maps_for, kept when the ship can reach them (bot/catalog.route).

What the bot plays (a condition -> a goal kind; anything else, or a condition with a state sub-condition such as "cloaked" or "in the
radiation zone", cannot be played):
  kill    destroy / damage these aliens (KILL_NPC, KILL_NPCS, DAMAGE_NPCS), on their maps
  grind   any alien counts (a kill / damage condition with no alien, take damage, fire laser ammo, collect cargo boxes, reach a level)
  visit   enter a map                      point   reach a coordinate on a map (VISIT_MAP with COORDINATES; the per-second 'pos' event)
  travel  fly a distance (on a map)        stay    spend a time (on a map; the per-second 'pos' event)
  boxes   collect bonus boxes (on a map)   ore     harvest an ore (COLLECT_LOOT of a raw ore that spawns on a map)
  giver   return to the quest giver (only once nothing else of the quest can be played)
Ordered quests open one condition at a time (quest.evaluate): only the open ones are played. The quests that run against the clock are
played first (the least time left first). The quests' restrictions (quest 'failed') are kept by the hunt: forbidden aliens are never fired
at, forbidden ammo is not fired, a quest that fails on death flees earlier (Pilot.hunt_cfg)."""
import math
import time

import galaxy_gates as GG
import map_links as H
import quest as QU
import quest_tracker as GT
import world as W
from bot import catalog as K
from bot.goals import quest as BQ

from .economy import SELL_ORES

KILL, DAMAGE_NPCS = (6, 27), 29              # KILL_NPC and its counted variant; damage these aliens ([count, npcId ..., 0])
VISIT_MAP, ON_MAP, GIVER, COORDINATES = 34, 77, 62, 11
TRAVEL, ENDURANCE, BONUS, CARGO, LOOT = (12, 13), 3, 55, 51, 67
TAKE_DAMAGE, AMMUNITION, LEVEL = 9, 22, 53
KILL_PLAYERS, DAMAGE_PLAYERS = 28, 30
SELL_ORE, ORE_UPDATE, SLOT_BAR, ASSET, SKYLAB, STARTER_GATE, DIE, SALVAGE, STEAL, BUILT_RECIPE = 52, 72, 70, 75, 76, 68, 35, 23, 24, 85
MISCELLANEOUS, RADIATION = 19, '5'
UPDATE_ITEMS = {'LASER': 0, 'ROCKET': 1, 'SPEED': 2, 'SHIELD': 3}       # LabUpdateItemRequest itemToUpdate
STARTER_KEY, STARTER_QUEST = 'start', 20012  # the Devolarium Attack event gate (its portal on X-1 while quest 20012 runs)
MINE = 'ammunition_mine_acm-01'              # the mine bought and laid for "lay mines" (AMMUNITION 3)
OLD_ORE = {o: loot for loot, o in GT.OLD_ORE.items()}
PLAYED_SUBS = (ON_MAP, COORDINATES, 19)      # MISCELLANEOUS: only "in the radiation zone" while flying a distance is played
ACCEPT_KINDS = ([1], [2])                    # quests taken on its own: the starter and main quests (not dailies, challenges, events)
NO_LASER, NO_ROCKET = ('0', '1'), ('0', '2')     # a forbidden ammo class (quest 'failed' ammunition): 0 all, 1 laser, 2 rocket


ALL_MAPS = sorted(H.NAMES)
NPC_MAPS = sorted(int(m) for m in K.NPC['maps'] if str(m).isdigit())      # the maps with permanent aliens (npc.json)
ORE_ID = {loot: int(t) for t, loot in W.ITEMS['ores']['kinds'].items()}


RECIPES = {int(t): {int(k): v for k, v in r.items()} for t, r in W.ITEMS['lab']['recipes'].items()}     # refined ore -> its ores
XENOMIT, PALLADIUM = 3, 8
FINISH_GATES = 80                            # FINISH_GALAXY_GATES [count, gate names ..., maps ...]
GATE_NPCS = {}                               # alien npc id -> the galaxy gates whose waves have it (easiest first)
for _k, _g in GG.GATES.items():
    for _w in _g['waves']:
        for _a in _w['alien_spawns']:
            if _k not in GATE_NPCS.setdefault(str(_a['npc_id']), []):
                GATE_NPCS[str(_a['npc_id'])].append(_k)
GATE_MAPS = {m: k for k, g in GG.GATES.items() for m in g['maps']}
LOW_MAP, HIDDEN = 200, '4'


def _low_tips():
    """The alien types LoW spawns (data/low.json: its waves, escort and boss)."""
    import json, os
    try:
        with open(os.path.join(os.path.dirname(QU.__file__), 'data', 'low.json'), encoding='utf8') as fh:
            text = json.dumps(json.load(fh))
    except (OSError, ValueError):
        return set()
    return {t for t in K.NPC['types'] if '"%s"' % t in text}


LOW_TIPS = _low_tips()


def ore_maps(t):
    """The maps where ore t spawns (items.json ores.maps: by name, else by map class)."""
    om = W.ITEMS['ores']['maps']
    return [m for m in ALL_MAPS if str(t) in (om.get(H.name(m)) or om.get(H.map_class(m)) or {})]


def raw_of(t):
    """A refined ore's raw ores to harvest -> {ore: units per refined unit} (Xenomit, which does not spawn, kept apart)."""
    if t not in RECIPES:
        return {t: 1}
    out = {}
    for k, v in RECIPES[t].items():
        for r, n in raw_of(k).items():
            out[r] = out.get(r, 0) + v * n
    return out


def droppers(loot):
    """loot -> the alien types whose destruction drops it (npc.json extra_reward, or the ore in their cargo box)."""
    ore = ORE_ID.get(loot)
    out = []
    for tip, t in K.NPC['types'].items():
        spec = (t.get('extra_reward') or {}).get(loot)
        p = spec.get('probability', 1) if isinstance(spec, dict) else spec
        if p or (ore is not None and (t.get('cargo') or {}).get(str(ore))):
            out.append(tip)
    return out


class Quests:
    def quest_book(self):
        return getattr(self.session, 'quest', None)

    # ------------------------------------------------------------ conditions
    def reach(self, m):
        """The ship is on map m or can fly there through the portals (bot/catalog.route: no paid or keyed portal; a map out of the
        route, such as 5-x or the Blacklight maps, counts only while the ship is on it)."""
        return int(m) == self.map_id() or (self.can_enter(m) and self.route(m) is not None)

    def spec_maps_all(self, specs):
        out = []
        for spec in specs:
            try:
                out += [int(m) for m in QU.maps_for(str(spec).lstrip('@'), self.company())]
            except (KeyError, ValueError, TypeError):
                pass
        return list(dict.fromkeys(out))

    def spec_maps(self, specs):
        """"own X-3" / "@4-5" / "any X-BL" ... -> the map ids within reach (quest.maps_for, by the player's company)."""
        return [m for m in self.spec_maps_all(specs) if self.reach(m)]

    def can_cloak(self):
        """A cloak CPU with uses left is fitted (CombatItems.cloak), or the ship is cloaked already."""
        import combat_items as CIT
        import extras as EX
        loot = CIT.cloak_loot(self.p)
        return bool(self.p.d.get('cpu_hidden')) or bool(loot and EX.uses(self.p, loot) > 0)

    def gate_ok(self, key):
        """Whether gate `key` can be played now (built, ready, or buildable with the spins allowed): Pilot.attach puts the Galaxy gate
        settings' check here (tasks/gates.can_build)."""
        return False

    def gate_goal(self, keys, out, aliens=None):
        """The first of the gates `keys` that can be played -> a 'gate' goal, or None."""
        key = next((k for k in keys if k in GG.GATES and self.gate_ok(k)), None)
        return dict(out, kind='gate', gate=key, aliens=aliens, maps=None) if key else None

    def rules(self):
        """The active quests' restrictions -> dict(forbid: alien types never to destroy, no_laser, no_rocket, no_death)."""
        q = self.quest_book()
        out = dict(forbid=set(), no_laser=False, no_rocket=False, no_death=False)
        if q is None:
            return out
        for key in list(q.st['active']):
            for f in QU.QUESTS.get(int(key), {}).get('failed', []):
                if f['type'] == 'kills':
                    out['forbid'].update(t for i in f['npc'] for t in BQ.npc_types(i))
                elif f['type'] == 'ammunition':
                    out['no_laser'] |= f['ammo_class'] in NO_LASER
                    out['no_rocket'] |= f['ammo_class'] in NO_ROCKET
                elif f['type'] == 'death':
                    out['no_death'] = True
        return out

    def cond_goal(self, c, value=0, forbid=()):
        """What the bot does for condition c (value: its progress) -> dict(kind, aliens, maps, point, ore, box) or None when it cannot
        play it. maps None: anywhere (the map it is on)."""
        subs = c.get('subConditions', [])
        misc = [s['matches'][:1] for s in subs if s['type'] == MISCELLANEOUS]
        if any(s['type'] not in PLAYED_SUBS for s in subs) or (misc and (c['type'] not in TRAVEL or misc not in ([[RADIATION]], [[HIDDEN]]))
                                                                  or (misc == [[HIDDEN]] and not self.can_cloak())):
            return None                                     # in the radiation zone / cloaked (a cloak CPU) while flying: played
        specs = [spec for s in subs if s['type'] == ON_MAP for spec in s['matches']]
        on = self.spec_maps(specs)
        out = dict(kind=None, aliens=None, maps=on or None, point=None, ore=None, box=None, harvest=None, refine=None, gate=None, pvp=None,
                   need=c['targetValue'] - value, sell=False, upgrade=None, action=None, radiation=misc == [[RADIATION]],
                   hidden=misc == [[HIDDEN]])
        t, m = c['type'], [str(x) for x in c.get('matches', [])]
        if specs and not on:                                # a gate's maps (@Epsilon Gate): its waves, else out of reach
            gates = [GATE_MAPS[x] for x in self.spec_maps_all(specs) if x in GATE_MAPS]
            ids = [i for i in (m if t in KILL else GT.counted(m) if t == DAMAGE_NPCS else []) if i != '0']
            return self.gate_goal(gates, out, sorted({x for i in ids for x in BQ.npc_types(i)}) or None) if gates else None
        maps = on or None
        if t == FINISH_GATES:
            return self.gate_goal([n.lower() for n in GT.counted(m)], out)
        if t in (KILL_PLAYERS, DAMAGE_PLAYERS):
            return self.pvp_goal(c, m, maps, out)
        if t == STEAL:
            import settings as SET
            if not SET.get('cargo_ownership'):
                return None                                 # without box ownership nothing is anyone's: nothing to steal
            g = self.pvp_goal(dict(c, type=DAMAGE_PLAYERS), m, maps, out)
            return g and dict(g, box='steal')
        if t == SELL_ORE:
            loot = OLD_ORE.get(m[0], 'resource_ore_prometium') if m else 'resource_ore_prometium'
            g = self.loot_goal(loot, out['need'], maps, out)
            return g and dict(g, sell=True, ore=ORE_ID[loot])
        if t == ORE_UPDATE and len(m) == 2 and m[0] in UPDATE_ITEMS:
            loot = 'resource_ore_' + m[1].lower()
            if loot not in ORE_ID:
                return None
            if self.p.ore_count(ORE_ID[loot]) > 0:
                return dict(out, kind='act', action=('upgrade', UPDATE_ITEMS[m[0]], ORE_ID[loot]))
            g = self.loot_goal(loot, out['need'], maps, out)
            return g and dict(g, upgrade=UPDATE_ITEMS[m[0]], ore=ORE_ID[loot])
        if t == SLOT_BAR and len(m) >= 2:
            return dict(out, kind='act', action=('slot', m[0], m[-1]))
        if t == SKYLAB and m and getattr(self.session, 'skylab', None) is not None:
            return dict(out, kind='act', action=('skylab', m[0], c['targetValue']))
        if t == ASSET and m:
            return dict(out, kind='asset', maps=[self.home_map()], action=int(m[0]))
        if t == STARTER_GATE:
            return dict(out, kind='egate', gate=STARTER_KEY, maps=[self.home_map()])
        if t == DIE:
            return dict(out, kind='die')
        if t == AMMUNITION and m and m[0] == '3':
            return dict(out, kind='mine')
        if t == AMMUNITION and m and m[0] == '2':
            return dict(out, kind='grind', action='rockets')
        if t == SALVAGE:
            ore = m[4] if len(m) > 4 else '0'
            if any(x not in ('', '0') for x in m[:3]):
                return None
            if ore in ('', '0'):
                return dict(out, kind='grind', box='cargo', sell=True)
            g = self.loot_goal(OLD_ORE.get(ore, ''), out['need'], maps, out, harvest=False)
            return g and g['kind'] == 'kill' and dict(g, sell=True)
        if t == BUILT_RECIPE:
            r = self.craftable(m, out['need'])
            return dict(out, kind='act', action=('craft', r, out['need'])) if r else None
        if t in KILL or t == DAMAGE_NPCS:
            ids = [i for i in (m if t in KILL else GT.counted(m)) if i != '0']
            known = {x for i in ids for x in BQ.npc_types(i)}
            types = sorted(known - set(forbid))
            if not ids:
                return dict(out, kind='grind')
            if not known:                                   # not in npc.json: a galaxy gate's own alien, else unknown
                return self.gate_goal([k for i in ids for k in GATE_NPCS.get(i, [])], out)
            if not types:
                return None                                 # forbidden aliens
            if maps is None:
                maps = [x for x in NPC_MAPS if any(v['tip'] in types for v, _ in K.map_npcs(x)) and self.reach(x)]
            if not maps and set(types) & LOW_TIPS and self.reach(LOW_MAP):
                maps = [LOW_MAP]                            # LoW's own aliens: a LoW run (everything there is fought)
            if maps:
                return dict(out, kind='kill', aliens=types, maps=maps)
            return self.gate_goal([k for i in ids for k in GATE_NPCS.get(i, [])], out, types)    # only in galaxy gates' waves
        if t == VISIT_MAP:
            maps = self.spec_maps(c.get('matches', []))
            if not maps:
                return None
            coord = next((s['matches'] for s in subs if s['type'] == COORDINATES), None)
            if coord:
                return dict(out, kind='point', maps=maps[:1], point=(int(coord[0]), int(coord[1]), int(coord[2])))
            return dict(out, kind='visit', maps=maps[:1])
        if t == GIVER:
            return dict(out, kind='giver', maps=None)
        if t in TRAVEL:
            return dict(out, kind='travel')
        if t == ENDURANCE:
            return dict(out, kind='stay')
        if t == BONUS:
            return dict(out, kind='boxes', box='bonus')
        if t == CARGO:
            return dict(out, kind='grind', box='cargo')
        if t in (TAKE_DAMAGE, LEVEL) or (t == AMMUNITION and m and m[0] in ('0', '1')):
            return dict(out, kind='grind')
        if t == LOOT and len(m) == 1:
            return self.loot_goal(m[0], c['targetValue'] - value, maps, out, forbid)
        return None

    def pvp_goal(self, c, m, on, out):
        """Destroy / damage pilots of another company: the player bots (act/players.py). KILL_PLAYERS matches [ship count, ships ...,
        company count, companies ...]; a quest naming ships cannot be told apart (its ship ids are not the bots' ship items)."""
        if not self.pvp_on():
            return None
        companies = []
        if c['type'] == KILL_PLAYERS and m:
            n = int(m[0])
            if n:
                return None
            rest = m[1 + n:]
            companies = rest[1:1 + int(rest[0])] if rest else []
        me = str(self.company())
        if companies and all(x == me for x in companies):
            return None
        maps = on or [x for x in self.pvp_maps(companies) if self.reach(x)]
        return dict(out, kind='pvp', maps=maps or None, pvp=companies)

    def craftable(self, recipes, need):
        """An Assembly recipe of the list (empty: any) whose materials for one build are at hand -> its key or None."""
        a = getattr(self.session, 'assembly', None)
        if a is None:
            return None
        import assembly as AS
        for key in (recipes or sorted(a.visible())):
            if key in AS.T and key in a.visible() and a.limit_left(key) != 0 and (key in a.st['production'] or not AS.INV.missing(self.p, a.cost(key, 1))):
                return key
        return None

    def loot_goal(self, loot, need, on, out, forbid=(), harvest=True):
        """Collect `need` of loot: harvest it (a raw ore that spawns within reach; Palladium beyond the cargo is traded at the 5-2 trader),
        else harvest its raw ores and refine them (Shop.refine), else destroy the aliens that drop it and take their cargo boxes."""
        ore = ORE_ID.get(loot)
        if ore is not None and harvest:
            raw = raw_of(ore)
            need_x = raw.pop(XENOMIT, 0) * need
            spawn = None
            for r in raw:
                ok = {x for x in ore_maps(r) if self.reach(x) and (not on or x in on)}
                spawn = ok if spawn is None else spawn & ok
            spawn = sorted(spawn or ())
            room = self.p.cargo_free() + sum(self.ore_counts().values())       # the sellable ores make room at the station
            fits = ore != PALLADIUM or need <= room or self.reach(int(W.PIRATE_MARKET))
            if spawn and fits and self.p.ore_count(XENOMIT) >= need_x:
                return dict(out, kind='ore', maps=spawn, ore=ore, harvest=sorted(raw), refine=ore if ore in RECIPES else None)
        tips = sorted(set(droppers(loot)) - set(forbid))
        maps = [x for x in NPC_MAPS if (not on or x in on) and any(v['tip'] in tips for v, _ in K.map_npcs(x)) and self.reach(x)]
        if not maps:
            return None
        return dict(out, kind='kill', aliens=tips, maps=maps, box='cargo')

    def quest_goals(self, only=None, now=None, skip=()):
        """The open conditions the bot can play, the quest to play first in front -> [dict(qid, cid, name, kind, aliens, maps, point,
        ore, box)]. Quests against the clock come first (least time left first); inside a quest the conditions in their order, the return
        to the quest giver last (an unordered quest has it open from the start)."""
        q = self.quest_book()
        if q is None:
            return []
        now = time.time() if now is None else now
        forbid = self.rules()['forbid']

        def left(item):
            d, vals = item[1], item[2]
            return d['duration_sec'] - (now - vals.get(QU.START, now)) if d.get('duration_sec') else math.inf

        quests = [(int(k), QU.QUESTS[int(k)], v) for k, v in list(q.st['active'].items()) if int(k) in QU.QUESTS and (not only or int(k) == only)]
        out = []
        for qid, d, vals in sorted(quests, key=left):
            states = QU.evaluate(d['root'], vals)[0]
            mine, giver = [], []
            for c in QU.conditions(d['root']):
                active, done = states.get(c['id'], (False, False))
                if not active or done or not c.get('mandatory', True) or (qid, c['id']) in skip:
                    continue
                g = self.cond_goal(c, vals.get(str(c['id']), 0), forbid)
                if g is not None:
                    (giver if g['kind'] == 'giver' else mine).append(dict(g, qid=qid, cid=c['id'], name=d.get('name', str(qid))))
            out += mine or giver
        return out

    def quest_goal(self, only=None, now=None, skip=()):
        """The goal to play now (quest_goals' first) with the aliens of every open kill condition on its maps (map -> types: one trip
        clears all of them), or None."""
        goals = self.quest_goals(only, now, skip)
        if not goals:
            return None
        g = dict(goals[0])
        if g['kind'] == 'kill':
            by_map = {}
            for o in goals:
                if o['kind'] == 'kill':
                    for m in o['maps']:
                        if m in g['maps']:
                            by_map.setdefault(m, set()).update(o['aliens'])
            g['by_map'] = {m: sorted(v) for m, v in by_map.items()}
        return g

    def playable(self, qid):
        """Whether the bot can play the whole quest (every mandatory condition, none of its restrictions in the way)."""
        d = QU.QUESTS.get(qid)
        if not d:
            return False
        if any(f['type'] == 'ammunition' and f['ammo_class'] in NO_LASER for f in d.get('failed', [])):
            return False
        forbid = {t for f in d.get('failed', []) if f['type'] == 'kills' for i in f['npc'] for t in BQ.npc_types(i)}
        return all(self.cond_goal(c, 0, forbid) is not None for c in QU.conditions(d['root']) if c.get('mandatory', True))

    def active_quests(self):
        """The accepted quests for the panel's choice: [{id, name, playable (the bot can play its open condition)}]."""
        q = self.quest_book()
        if q is None:
            return []
        out = []
        for key in list(q.st['active']):
            qid = int(key)
            if qid in QU.QUESTS:
                out.append(dict(id=qid, name=QU.QUESTS[qid].get('name', str(qid)), playable=bool(self.quest_goals(qid))))
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

    # ------------------------------------------------------------ the quest giver
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
        """At a quest giver: the highest-level starter / main quest the bot can play from start to end, not against the clock, that can
        be taken now (level, previous quests, a free slot: quest.Quests.accept checks them) -> its id or None."""
        q, w = self.quest_book(), self.w
        if q is None or not w.near_giver or not q.free_slots():
            return None
        offer = QU.offered()
        cands = sorted((-d.get('level', 0), qid) for qid, d in QU.QUESTS.items() if d.get('kinds') in ACCEPT_KINDS and not d.get('duration_sec'))
        for _, qid in cands:
            if q.status(qid)[0] != QU.NOT_STARTED or not q.visible(qid, offer) or not self.playable(qid):
                continue
            msgs = q.accept(qid)
            if str(qid) in q.st['active']:
                extra = getattr(self.session, 'quest_state_events', None)
                self.session.send(msgs + (extra() if extra else []), 'auto mode: quest accepted')
                return qid
        return None

    # ------------------------------------------------------------ one-off quest actions
    def ore_upgrade(self, item, ore, n):
        """The laboratory's upgrade of a part with ore from the cargo (Shop.upgrade; item 0 laser, 1 rocket, 2 speed, 3 shield)."""
        shop = getattr(self.session, 'shop', None)
        n = min(n, self.p.ore_count(ore))
        if shop is None or n <= 0:
            return False
        msgs = shop.upgrade({'itemToUpdate': {'itemValue': item}, 'updateWith': {'oreType': {'typeValue': ore}, 'count': n}})
        if msgs:
            self.session.send(msgs, 'auto mode: laboratory')
        return True

    def slot_put(self, bar, item):
        """Puts an item on a slot bar (Profile.slot_bar_set, the first free slot, else the last) and lets the quests read the bars."""
        import sys
        game = sys.modules.get('game') or sys.modules.get('__main__')          # game.py runs as the main script
        entry = getattr(getattr(game, 'TEMPLATE', None), 'entry', {}) or {}
        tpl = next((m for m in entry.get('ready', []) if m['_m'] == 'MenuInitializationCommand'), None)
        bars = tpl['slotBars'] if tpl else []
        cur = self.p.slot_bar_state(bars)
        if (bar, item) in set(cur.get('items', ())):
            return self.state_events()
        used = (self.p.d.get('shortcuts') or {}).get(bar, {})
        slot = next((str(i) for i in range(1, 11) if str(i) not in used), '10')
        self.p.slot_bar_set({'menuItemId': item, 'slotBarIdFrom': '', 'slotBarIdTo': bar, 'slotIdFrom': '', 'slotIdTo': slot}, bars)
        return self.state_events()

    def state_events(self):
        """The quests' state conditions read again (slot bars, Skylab levels: game.py quest_state_events)."""
        f = getattr(self.session, 'quest_state_events', None)
        msgs = f() if f else []
        if msgs:
            self.session.send(msgs, 'auto mode: quest state')
        return True

    def skylab_up(self, module, level):
        """A Skylab module up to `level`: its upgrade (credits and Skylab ores) when it is not on the way already."""
        sk = getattr(self.session, 'skylab', None)
        if sk is None:
            return False
        if sk.levels().get(module, 0) < level and sk.state(module) != 'UPGRADE':       # not already on the way up
            msgs = sk.action({'construction': module, 'subaction': 'upgrade'}) or []
            if msgs:
                self.session.send(msgs, 'auto mode: Skylab')
        return self.state_events()

    def lay_mine(self, now):
        """A mine where the ship is (CombatItems.place_mine), bought first when none is in stock -> whether one was laid."""
        import combat_items as CIT
        p, w = self.p, self.w
        loot = next((m for m in CIT.MINES if m.startswith('ammunition_mine_') and p.ammo(m) > 0), None)
        if loot is None:
            if not self.buy(MINE, 10):
                return False
            loot = MINE
        before = p.ammo(loot)
        w.items.place_mine(loot, now)
        return p.ammo(loot) < before

    def asset_spot(self, kind):
        """The station object of this type on this map (World.assets / asset_types) -> (x, y) or None."""
        w = self.w
        return next(((x, y) for a, x, y, tip in w.assets if w.asset_types.get(a) == kind), None)

    def event_gate_portal(self, key):
        return next((g for g in self.w.gates if g.get('gate') == key and g.get('event_gate')), None)

    def hand_in(self):
        """At a quest giver: the "return to the quest giver" condition (game.py QuestGiverApproachedRequest)."""
        q = self.quest_book()
        if q is None or not self.w.near_giver:
            return False
        msgs = q.event('giver')
        if msgs:
            self.session.send(msgs, 'auto mode: quest giver')
        return True
