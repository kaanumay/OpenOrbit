"""Quest: take and finish alien-kill / player-kill / map-visit quests from the game's quest chain (quests.json).

The bot takes from the quest giver a quest that fits its level, whose prerequisites are done and that it has not finished; it goes to the conditions' map and
chases the requested alien. The rewards are the quest's own (currency_credits, currency_experience, currency_uridium, currency_honour and items).
When the quest data changes (World Editor) the bots use the new data on their own.
"""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S

KILL_NPC, KILL_PLAYERS, VISIT_MAP, ON_MAP, HOME = 6, 28, 34, 77, 62
SUPPORTED = {KILL_NPC, KILL_PLAYERS, VISIT_MAP, HOME}
_quests = None
_id_type = None


def quests():
    """id -> {level, previous, conditions [{id, type, target, matches, maps (tokens)}], rewards}: only what the bot can do."""
    global _quests, _id_type
    if _quests is None:
        import quest as QU
        _id_type = {}
        for tip, t in K.NPC['types'].items():
            _id_type.setdefault(str(t.get('npc_id', '')), []).append(tip)
        out = {}
        for qid, q in QU.QUESTS.items():
            if q.get('kinds') != [2] or q.get('duration_sec'):
                continue
            conditions = []
            ok = True
            for el in q['root'].get('modifier', []):
                c = el.get('condition')
                if not c or c['type'] not in SUPPORTED:
                    ok = False
                    break
                maps = [m for s in c.get('subConditions', []) if s.get('type') == ON_MAP for m in s.get('matches', [])]
                if any(s.get('type') not in (ON_MAP,) for s in c.get('subConditions', [])):
                    ok = False
                    break
                conditions.append(dict(id=c['id'], type=c['type'], target=int(c.get('targetValue', 1)), matches=list(c.get('matches', [])),
                                maps=maps))
            package = any(str(l).startswith('ship_') or (l == 'currency_uridium' and n >= 10000) for l, n in q.get('rewards', []))
            if ok and conditions and not package:            # welcome package (ship, thousands of uridium): bots start from zero like everyone else
                out[int(qid)] = dict(level=int(q.get('level', 0)), previous=[int(x) for x in q.get('previous', [])], conditions=conditions,
                                     rewards=q.get('rewards', []), name=q.get('name', ''), ordered=q['root'].get('ordered', False))
        _quests = out
    return _quests


def map_list(spec, company):
    import quest as QU
    try:
        return [int(m) for m in QU.maps_for(str(spec).lstrip('@'), company) if int(m) in K.MAPS]
    except (KeyError, ValueError, TypeError):
        return []


def npc_types(uid):
    quests()
    return _id_type.get(str(uid), [])


def eligible(bot):
    """Quests the bot can take now (those close to its level first)."""
    done = set(bot.k['done'])
    deferred = bot.k.get('deferred') or {}
    out = []
    for qid, q in quests().items():
        if qid in done or deferred.get(str(qid), 0) >= bot.level or q['level'] > bot.level or any(x not in done and x in quests() for x in q['previous']):
            continue
        out.append((qid, q))
    out.sort(key=lambda x: (-x[1]['level'], x[0]))
    return out


def next_up(bot):
    """The next unfinished condition of the running quest -> (condition, maps) or None."""
    g = bot.k.get('quest')
    if not g:
        return None
    q = quests().get(g['id'])
    if not q:
        bot.k['quest'] = None
        return None
    for c in q['conditions']:
        if g['conditions'].get(str(c['id']), 0) < c['target']:
            maps = [m for h in c['maps'] for m in map_list(h, bot.company)]
            if c['type'] == VISIT_MAP:
                maps = [m for h in c['matches'] for m in map_list(h, bot.company)]
            elif c['type'] == HOME:
                maps = [K.ev(bot.company)]
            elif c['type'] == KILL_NPC and not maps:
                # no map given: the nearest map where that alien appears and that it can enter
                types = {t for k in c['matches'] for t in npc_types(k)}
                maps = [m for m in K.MAPS if K.can_enter(m, bot.company, bot.level)
                        and any(v['tip'] in types for v, _ in K.map_npcs(m))]
            maps = [m for m in maps if K.can_enter(m, bot.company, bot.level)]
            return c, maps
        if q['ordered']:
            continue
    return None


def advance(bot, kind, n=1, npc_id=None, game_map=None, y=None):
    """An event advances the quest (alien killed while grinding, PvP, map entry) -> whether the quest is done."""
    g = bot.k.get('quest')
    if not g:
        return False
    q = quests().get(g['id'])
    if not q:
        return False
    for c in q['conditions']:
        key = str(c['id'])
        if g['conditions'].get(key, 0) >= c['target']:
            continue
        if c['type'] != kind:
            if q['ordered']:
                break
            continue
        if kind == KILL_NPC and npc_id is not None and str(npc_id) not in c['matches']:
            continue
        maps = [m for h in c['maps'] for m in map_list(h, bot.company)]
        if kind == VISIT_MAP:
            maps = [m for h in c['matches'] for m in map_list(h, bot.company)]
        elif kind == HOME:
            maps = [K.ev(bot.company)]
        if maps and game_map not in maps:
            continue
        g['conditions'][key] = min(c['target'], g['conditions'].get(key, 0) + n)
        if q['ordered']:
            break
    if all(g['conditions'].get(str(c['id']), 0) >= c['target'] for c in q['conditions']):
        finish(bot, q, y)
        return True
    return False


def finish(bot, q, y):
    speed = y.speed(bot) if y is not None else 1.0
    currency = dict(currency_credits='credits', currency_experience='ep', currency_uridium='uridium', currency_honour='honor')
    earned = {}
    for loot, n in q['rewards']:
        if loot in currency:
            earned[currency[loot]] = earned.get(currency[loot], 0) + n
        else:
            bot.add(loot, n)
    bot.reward('quest', speed, **earned)
    bot.k['done'].append(bot.k['quest']['id'])
    bot.k['quest'] = None
    bot.ist('quest')
    bot.mood.it(morale=0.15, boredom=-0.2)
    bot.event('quest_done', name=q['name'])


def deferred(bot):
    """The quest cannot be done for now (it is not strong enough for the requested alien): it is dropped and retried after a level-up (a real
    player also cancels the quest and comes back later)."""
    g = bot.k.get('quest')
    if g:
        bot.k.setdefault('deferred', {})[str(g['id'])] = bot.level
        bot.k['quest'] = None
    bot.plan['finished'] = True


@target
class Quest(Goal):
    name = 'quest'
    permission = 'quest'
    min_sec = 240

    def eligible(self, bot, b):
        if bot.k.get('quest'):
            s = next_up(bot)
            return bool(s and s[1])
        return bool(eligible(bot))

    def points(self, bot, b):
        o = bot.traits
        p = 0.45 + 0.35 * o['ambition'] * o['patience'] + (0.35 if bot.archetype == 'quester' else 0)
        if bot.k.get('quest'):
            p += 0.15                     # takes a half-done quest
        from .. import weapons as WP
        if not WP.has_laser(bot):
            p *= 0.3                                      # most quests ask for kills: it does not progress without ammo
        return p * (1 - 0.3 * bot.mood['boredom'])

    def start(self, bot, b):
        if not bot.k.get('quest'):
            for qid, q in eligible(bot)[:6]:
                bot.k['quest'] = dict(id=qid, conditions={})
                s = next_up(bot)
                if s and s[1]:
                    break
                bot.k['quest'] = None
            if not bot.k.get('quest'):
                bot.plan['finished'] = True
                return
            bot.event('quest_taken', name=quests()[bot.k['quest']['id']]['name'])
        self._head_to(bot, b.y, b.now)

    def _head_to(self, bot, y, now=None):
        s = next_up(bot)
        if not s or not s[1]:
            bot.plan['finished'] = True
            return
        c, maps = s
        types = [t for k in c['matches'] for t in npc_types(k)] if c['type'] == KILL_NPC else []
        if types:
            # maps it is strong enough for (that it dares to kill on); if there are none, the quest waits until it gets stronger
            d = bot.value()
            maps = [m for m in maps if set(types) & set(K.evaluate_map(m, d['dps'], d['ehp'], 0.8)['targets'])]
            if not maps:
                deferred(bot)
                return
        target_map = min(maps, key=lambda m: len(K.route(bot.game_map, m, bot.company, bot.level) or range(99)))
        bot.plan['condition'] = c['id']
        bot.plan['map'] = target_map
        bot.plan['tip'] = next((v['tip'] for v, _ in K.map_npcs(target_map) if v['tip'] in types), None)
        S.go(bot, target_map, y, now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        s = next_up(bot)
        if not s:
            bot.plan['finished'] = True
            return
        c, maps = s
        if c['id'] != bot.plan.get('condition') or bot.game_map not in maps:
            self._head_to(bot, y)
            return
        if c['type'] in (VISIT_MAP, HOME):
            if bot.plan.get('visit') != (c['id'], bot.game_map):        # once on arrival (it used to be counted at every abstract step)
                bot.plan['visit'] = (c['id'], bot.game_map)
                advance(bot, c['type'], game_map=bot.game_map, y=y)
        elif c['type'] == KILL_PLAYERS:
            S.farm(bot, dt, y)             # PvP condition: encounters while roaming the map (manager.pvp_tick) count
        else:
            S.farm(bot, dt, y, target_kind=bot.plan.get('tip'))

    def finished(self, bot, b):
        return bot.plan.get('finished', False) or (not bot.k.get('quest') and 'condition' in bot.plan)
