"""The bots' game-setting profile: separate from the player's game settings (settings.py). Even if the player picks easy settings for themselves, bots go by the pack's
profile (user request 2026-10-29).

Profile (the pack's 'game_setting' setting): {'profile': 'standard' | 'player' | <a preset in SET.PRESETS> | 'special', 'values': {...}}
  standard  the game's own values (default)
  player    the player's current game settings (not like the old behavior: bots used no multiplier at all before)
  casual, fast, hard ...  the values of SET.PRESETS
  special   the values in the panel (FIELDS)
multiplier(key, source) like SET.multiplier: parent multiplier x the source's sub-multiplier (ep x ep_npc).
"""
import settings as SET

FIELDS = ('ep', 'credits', 'uridium', 'honor', 'npc_hp', 'npc_damage', 'shop_price', 'repair_cost')   # Fields editable in the special profile
PROFILES = ('standard', 'player', 'casual', 'fast', 'hard', 'special')


class Profile:
    def __init__(self, setting=None):
        setting = setting if isinstance(setting, dict) else {}
        self.name = setting.get('profile') if setting.get('profile') in PROFILES else 'standard'
        if self.name == 'special':
            self.d = {k: float(v) for k, v in (setting.get('values') or {}).items() if k in SET.DEFAULTS}
        elif self.name in SET.PRESETS:
            self.d = dict(SET.PRESETS[self.name]['values'])
        else:
            self.d = {}

    def get(self, key):
        if self.name == 'player':
            return SET.get(key)
        return self.d.get(key, SET.DEFAULTS.get(key, 1.0))

    def multiplier(self, key, source=None):
        sub = SET.SUB.get((key, source))
        try:
            return float(self.get(key)) * (float(self.get(sub)) if sub else 1.0)
        except (TypeError, ValueError):
            return 1.0


STANDARD = Profile()
