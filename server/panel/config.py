"""Panel settings (save/panel.json): language and setup, active save slot, client folder and display, backup, server behavior,
the Wine or Proton that launches the client on Linux and macOS.

Unknown keys are preserved (old/new versions can share the same file); a value of the wrong type falls back to the default.
"""
import json, os, threading

import lang as D

DEFAULTS = {
    'lang': None,                    # a code from dil.DILLER; None: not chosen yet (the setup wizard opens with the language choice)
    'setup_done': False,         # the first-run wizard is done (or skipped)
    'active_save': None,            # save/slots/<id>
    'client_folder': None,        # None: automatic (the newest DarkOrbit_Version* folder in the project root)
    'window_mode': 'windowed',      # windowed | fullscreen | borderless
    'width': 1440,
    'height': 900,
    'monitor': 0,                   # 0: the one Unity picks; 1..: -monitor N
    'extra_args': '',            # extra Unity arguments added to the client
    'backup_on_launch': True,         # automatic backup of the active slot on PLAY
    'backup_count': 10,             # automatic backups kept (manual ones are not deleted)
    'backup_interval_min': 30,          # automatic backup interval while the game is open (0: off)
    'when_client_closes': 'close',   # close: the servers the panel opened shut down | on: they stay open
    'rotate_logs': True,          # large logs rotate at startup as .1, .2 ...
    'when_window_closes': 'wait',   # when the panel window closes: wait (if the game is running, closes when it ends) | close (closes everything)
    'update': 'auto',       # new version on GitHub (updater.py): auto install | notify (just notify) | off
    'fast_download': True,          # the client download with CONNECTIONS connections (client_download.py); a single connection when off
    'friend_password': '',            # Play with Friends > Host: join password (empty: no password)
    'friend_max': 4,            # Host: most guests
    'friend_world': '',            # Host: the server's world (World Editor; empty: the active save's default world)
    'friend_last_address': '',        # Join: last address joined
    'multi_client': True,          # multi-client: with at least two saves PLAY opens the server multi-session (multi_client.py)
    'multi_client_max': 3,              # most extra clients (each client ~600 MB of memory)
    'runner': 'auto',      # Linux and macOS: what launches the client: auto | engine | wine | proton | special (client_runner.py)
    'runner_path': '',         # the wine program, Proton folder or custom command (empty: automatic)
    'wine_prefix': '',                # Wine prefix / Proton data folder (empty: save/wine or save/proton)
    'discord_rp': True,             # Discord Rich Presence (discord_rp.py); rp_*: what shows on the profile
    'rp_pilot': False,              # pilot name (privacy: off by default)
    'rp_clan': True,
    'rp_ship': True,
    'rp_level': True,
    'rp_map': True,              # map name and the area's image
    'rp_state': True,               # in combat (target), gate wave, safe zone, ship destroyed
    'rp_company': True,               # the company's emblem
    'rp_duration': True,                # the session's elapsed time
    'rp_group': True,                # Play with Friends: group size
    'rp_buttons': True,            # Discord server and GitHub buttons
    'rp_in_panel': True,             # even when the game is closed (in the panel)
}
CHOICES = {'window_mode': ('windowed', 'fullscreen', 'borderless'), 'when_client_closes': ('close', 'on'),
           'when_window_closes': ('wait', 'close'), 'update': ('auto', 'notify', 'off'),
           'runner': ('auto', 'engine', 'wine', 'proton', 'special')}
LIMITS = {'width': (640, 7680), 'height': (480, 4320), 'monitor': (0, 8), 'backup_count': (1, 200), 'backup_interval_min': (0, 600),
          'friend_max': (1, 16), 'multi_client_max': (1, 8)}


def clean(key, v):
    """Validate the value -> a valid value or ValueError."""
    if key not in DEFAULTS:
        raise ValueError('bilinmeyen ayar: %s' % key)
    d = DEFAULTS[key]
    if key == 'lang':
        return v if v in D.LANGUAGES else None
    if key in CHOICES:
        if v not in CHOICES[key]:
            raise ValueError('%s: geçersiz seçim' % key)
        return v
    if isinstance(d, bool):
        return bool(v)
    if isinstance(d, int):
        v = int(v)
        lo, hi = LIMITS.get(key, (v, v))
        return min(hi, max(lo, v))
    if key in ('active_save', 'client_folder'):
        return str(v) if v else None
    return str(v if v is not None else '')


class PanelConfig:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.d = {}
        self.load()

    def load(self):
        try:
            with open(self.path, encoding='utf8') as fh:
                d = json.load(fh)
            self.d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.d = {}

    def get(self, key):
        v = self.d.get(key, DEFAULTS.get(key))
        try:
            return clean(key, v) if key in DEFAULTS else v
        except (TypeError, ValueError):
            return DEFAULTS[key]

    def all(self):
        return {k: self.get(k) for k in DEFAULTS}

    def update(self, values):
        """Validate the values and write -> the current settings. An invalid value raises ValueError (none is written)."""
        new = {k: clean(k, v) for k, v in values.items()}
        with self.lock:
            self.d.update(new)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
                json.dump(self.d, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        return self.all()
