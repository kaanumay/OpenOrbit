"""A team PvP mode match (Team Deathmatch: team_deathmatch.py, Sector Control: sector_control.py): the bot was drafted into the player's
match (the mode sets the goal directly, it is never chosen by the brain). On the mode's map the match steers the ship (its bot_think: start
phase, objectives, enemies); while it waits to respawn or once the match is over it does nothing abstract: the match sends it home."""
from ..brain import Goal, target


@target
class PvpMatch(Goal):
    name = 'pvp_match'
    permission = 'pvp'
    min_sec = 3600

    def eligible(self, bot, b):
        return False                       # only a mode drafts a bot

    def concrete(self, bot, g, w, now):
        m = getattr(w, 'gate', None)
        if m is None or not getattr(m, 'team_mode', False):
            m = getattr(w, 'mode_brain', None)          # a mode on an ordinary map (Capture the Beacon's raider on X-2)
        if m is None or not hasattr(m, 'bot_think'):
            return False
        return m.bot_think(w, g, now)

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
