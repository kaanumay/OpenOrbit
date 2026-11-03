"""Auto Mode's adapters to the server: the only package that reads or drives world.World and the session's systems (shop, gates, P.E.T.,
quests) and builds the panel's live map (radar). Each area has its own mixin; Actions puts them together. Everything here is called under
the world lock (an RLock: World methods that take it again are fine); none of it may be called while holding the profile's lock (not
reentrant)."""
from .base import Base
from .combat import Combat
from .economy import Economy
from .gates import Gates
from .players import Players
from .quests import Quests
from .radar import Radar
from .travel import Travel


class Actions(Base, Travel, Combat, Economy, Players, Quests, Gates, Radar):
    pass
