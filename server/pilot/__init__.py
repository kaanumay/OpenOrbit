"""Auto Mode: the server flies the player's own ship (system.py). Pilot is imported on first use, so the panel can import pilot.config
without loading the game server's modules."""


def __getattr__(name):
    if name == 'Pilot':
        from .system import Pilot
        return Pilot
    raise AttributeError(name)
