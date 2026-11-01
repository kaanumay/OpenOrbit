"""Save and panel paths (management panel, panel/): profile, web settings, game settings.

  save/slots/<id>/profile.json           the save slot's profile (the game server writes it)
  save/slots/<id>/web_settings.json      the login screen's language (web.py, next to the profile)
  save/slots/<id>/slot.json              the slot's name, note, dates (panel)
  save/slots/<id>/backups/               backups (panel)
  save/panel.json                        panel settings: active slot, client folder, display, backups …
  save/settings.json                     game settings (settings.py)
Login templates (login.json, maps.json, responses.json): the ones extracted from your own record are in data/ (not committed to git),
otherwise the shareable copy in the repository is in data/defaults/ (tools/template_sharing.py; account and player ids masked): template().
The active slot is panel.json's 'active_save'. The old layout (save/profile.json) is moved to the 'main' slot when the panel first opens; if
it was not moved or there is no active slot, the profile path is the old file (when game.py / web.py run without --profile).
Standard library only: web.py, game.py and the panel use it together.
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE = os.environ.get('OO_SAVE_DIR') or os.path.join(HERE, 'save')      # tests provide a temporary folder
SAVES = os.path.join(SAVE, 'slots')
TRASH = os.path.join(SAVE, 'trash')
PANEL = os.path.join(SAVE, 'panel.json')
SETTINGS = os.path.join(SAVE, 'settings.json')
LEGACY_PROFILE = os.path.join(SAVE, 'profile.json')
LOGS = os.environ.get('OO_LOG_DIR') or os.path.join(HERE, 'logs')
DATA = os.path.join(HERE, 'data')
TEMPLATES = ('login.json', 'maps.json', 'responses.json')
DEFAULT_TEMPLATE = os.path.join(DATA, 'defaults')

# Save format v1 (Turkish names) -> v3, once, before anything reads the saves (save_migration.py: backup, lock, resumable).
# A failure is kept here instead of raised: the panel shows it and does not start the servers; game.py / web.py exit with it.
MIGRATION_ERROR = None
try:
    import save_migration as _SM
    _SM.ensure(SAVE, DATA, log=lambda m: None)
except Exception as _e:                                    # disk full, permissions, a broken file: never half-start on v1 data
    MIGRATION_ERROR = '%s: %s' % (type(_e).__name__, _e)


def template(name):
    """Path of the login template: the one extracted from your own record (data/<name>) if present, otherwise the shareable copy
    (data/defaults/<name>); None if neither exists."""
    for p in (os.path.join(DATA, name), os.path.join(DEFAULT_TEMPLATE, name)):
        if os.path.isfile(p):
            return p
    return None


def panel_config(path=PANEL):
    try:
        with open(path, encoding='utf8') as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def slot_dir(slot, root=SAVES):
    return os.path.join(root, slot)


def active_slot(path=PANEL):
    s = panel_config(path).get('active_save')
    return s if isinstance(s, str) and s and os.path.isdir(slot_dir(s)) else None


def profile_path(slot=None):
    """The slot's profile file (the active slot's if not given); the old save/profile.json if there is no slot."""
    slot = slot or active_slot()
    return os.path.join(slot_dir(slot), 'profile.json') if slot else LEGACY_PROFILE


def settings_path(slot=None):
    """The slot's game settings (the active slot's if not given) (per save; the panel creates it on first launch); the old
    save/settings.json if absent."""
    slot = slot or active_slot()
    p = os.path.join(slot_dir(slot), 'settings.json') if slot else None
    return p if p and os.path.isfile(p) else SETTINGS
