"""A team PvP mode match (Team Deathmatch: team_deathmatch.py, Sector Control: sector_control.py).

pvp_match: the bot is in a match. Drafted into the player's match (the mode sets the goal directly, it is never chosen by the brain): on
the mode's map the match steers the ship (its bot_think: start phase, objectives, enemies); while it waits to respawn or once the match is
over it does nothing abstract: the match sends it home. Or in its own match (modes.pvp_tick started it, plan 'abstract'): it sits on the
mode map until the match's end, then modes.pvp_settle pays the result and sends it home.
pvp_event: while a team mode's event is on and the bot's band has a match, a PvP-minded pilot queues for one (modes.pvp_join) and keeps
grinding while it waits, as a player in the queue does; it gives up after a few minutes. The player's lobby can draft it from the queue.
"""
from ..brain import Goal, target
from .. import abstract_sim as S
from .. import catalog as K
from .. import modes as MD

CTX_SEC = 5.0                      # how often a drafted bot's view of its match (score, tickets, teammates) is refreshed
QUEUE_PULL = 1.0                   # how much a queue's appeal (modes._appeal, 0..~3.7) multiplies the wish to play (behaviour weight)


@target
class PvpMatch(Goal):
    name = 'pvp_match'
    permission = 'pvp'
    min_sec = 3600

    def eligible(self, bot, b):
        return False                       # only a mode (or modes.pvp_tick) puts a bot in a match

    def concrete(self, bot, g, w, now):
        m = getattr(w, 'gate', None)
        if m is None or not getattr(m, 'team_mode', False):
            m = getattr(w, 'mode_brain', None)          # a mode on an ordinary map (Capture the Beacon's raider on X-2)
        if m is None or not hasattr(m, 'bot_think'):
            return False
        if now >= bot.__dict__.get('_match_ctx_t', 0):
            bot._match_ctx_t = now + CTX_SEC
            bot._match_ctx = _ctx(bot, m, w)
        return m.bot_think(w, g, now)

    def abstract(self, bot, dt, y):
        if bot.plan.get('abstract') and not bot.plan.get('finished') and y.now >= bot.plan.get('end', 0):
            MD.pvp_settle(bot, y, y.now)

    def finished(self, bot, b):
        # safety beside the mode's own release: off the match's map, or past the draft's longest hold (a match that was never closed
        # kept its bots on the mode map forever); manager.bot_tick then sends the bot home
        m = bot.plan.get('match')
        if (m is not None and bot.game_map != int(m)) or b.now - bot.goal_start > bot.plan.get('min', self.min_sec):
            bot.plan['finished'] = True
        return bot.plan.get('finished', False)


def _ctx(bot, m, w):
    """What the drafted bot knows of its match for after_match: the mode, the score (TDM) or tickets (SC), its teammates, the player."""
    st = getattr(m, 'stats', None) or {}
    return dict(drafted=True, mode=getattr(m, 'key', None), company=bot.company,
                score=dict(getattr(m, 'score', None) or {}) if getattr(m, 'key', None) == 'tdm' else None,
                tickets=dict(getattr(m, 'tickets', None) or {}) or None, out=list(getattr(m, 'out', None) or ()),
                mates=[s['name'] for u, s in st.items() if isinstance(s, dict) and s.get('company') == bot.company and u != bot.uid][:8],
                player=w.p.d['pilot'].get('userName', ''), player_company=int(w.p.d['pilot'].get('factionId') or 0))


@target
class PvpEvent(Goal):
    name = 'pvp_event'
    permission = 'pvp'
    min_sec = 600

    def eligible(self, bot, b):
        if bot.level < 8:
            return False
        from .. import weapons as WP
        return WP.has_laser(bot) and bool(MD.pvp_modes(bot, b.now))

    def points(self, bot, b):
        """PvP-minded and sociable pilots like the team modes; one or two matches an hour, then something else (not the same pilots again
        and again); tired or shaken pilots less; the evening's rush hour more."""
        from .. import playstyle as PL
        o = bot.traits
        p = (0.12 + 0.5 * o['aggression'] * (0.4 + o['rivalry']) + 0.15 * o['sociability'] + 0.1 * o['ambition']
             + (0.2 if bot.archetype == 'hunter' else 0))
        p *= (0.6 + 0.6 * bot.mood['confidence']) * (1 - 0.6 * bot.mood['fatigue']) * PL.like(bot, 'pvp') ** 0.8
        p /= 1 + 0.9 * MD.recent_matches(bot, b.now)
        if b.y is not None and b.y.prime(b.now):
            p *= 1.3
        appeal = MD.pvp_join(bot, MD.pvp_modes(bot, b.now), b.now, look=True)
        return p * (1 + QUEUE_PULL * appeal)           # a queue with pilots, close to starting, with friends in it draws (the lobby window)

    def start(self, bot, b):
        prefer = ((bot.k.get('intent') or {}).get('plan') or {}).get('lobby')      # a company mate's call (modes._recruit)
        key = MD.pvp_join(bot, MD.pvp_modes(bot, b.now), b.now, prefer=tuple(prefer) if prefer else None)
        if key is None:
            bot.plan['finished'] = True
            return
        L = MD.LOBBY.get(key) or {}
        bot.plan.update(lobby=key, joined=b.now, joins=L.get('joins', 0), until=b.now + bot.r.uniform(*MD.QUEUE_SEC))
        bot.event('pvp_queue', b.now, mode=key[0], band=key[1], waiting=sum(len(v) for v in (L.get('teams') or {}).values()))

    def abstract(self, bot, dt, y):
        MD.pvp_tick(y, y.now)
        if bot.target is not self or bot.plan.get('finished'):
            return                                     # the match started (pvp_match) or it was drafted
        plan = bot.plan
        L = MD.LOBBY.get(plan.get('lobby')) or {}
        if L.get('joins', 0) > plan.get('joins', 0):   # the queue grew: worth waiting a bit more (never past QUEUE_MAX_SEC in all)
            plan['joins'] = L['joins']
            plan['until'] = min(plan['joined'] + MD.QUEUE_MAX_SEC, max(plan['until'], y.now + MD.QUEUE_GROW_SEC))
        if y.now >= plan.get('until', 0):
            MD.pvp_leave(bot, plan.get('lobby'))
            plan['finished'] = True                    # waited long enough: something else
            bot.event('pvp_queue_left', y.now, mode=plan['lobby'][0], band=plan['lobby'][1], waited=int(y.now - plan['joined']))
            return
        if not S.journey(bot, y) and bot.game_map in K.MAPS and K.map_npcs(bot.game_map):
            S.farm(bot, dt, y)                         # grinds while it waits in the queue

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
