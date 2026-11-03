"""Auto Mode: travelling between maps, the death screen's repair, the base station.
Routes: the portals of the company maps and 4-X (bot/catalog's) plus the pirate maps (4-5 -> 5-1 -> 5-2 -> 5-3 -> 4-4, one way; 5-2 <-> 5-4
through the Silver Booty Key portal, World.pay_key) and the Blacklight maps (X-8 <-> BL-n). The key portal is taken only with a key in
storage or 25 Darksilver Coins to build one in the Assembly (recipe_blueprint-booty-key-silver). LoW and the Cubikon Graveyard (???) are not
destinations (a mode of their own / a random wormhole)."""
import functools
import heapq

import map_links as H
import settings as SET
import world as W
from bot import catalog as K

JUMP_RETRY_SEC = 15.0         # a refused jump (level, key, PvP on 4-X) is not asked again at every step (the client shows why each time)
LOW = 200                     # LoW: entered from X-3, left only by finishing it (or a death): a destination, never a way through
ROUTE_MAPS = frozenset(K.MAPS) | {91, 92, 93, 94, 306, 307, 308, LOW}
KEY_FEE, KEY_ITEM, KEY_RECIPE, KEY_COIN, KEY_COINS = ('silver_key', 'resource_booty-key-silver', 'recipe_blueprint-booty-key-silver',
                                                      'resource_collectable_darksilver-coin', 25)
KEY_HOPS = 6                  # a key portal counts as this many jumps (the key is spent): taken when it is the only way


@functools.lru_cache(maxsize=4096)
def _route(src, dst, company, level, keys, _free):
    """Cheapest portal route [src, ..., dst] over ROUTE_MAPS (Dijkstra; a key portal costs KEY_HOPS and only with keys) or None."""
    if src == dst:
        return (src,)
    best, prev, todo = {src: 0}, {src: None}, [(0, src)]
    while todo:
        d, m = heapq.heappop(todo)
        if m == dst:
            out = [m]
            while prev[out[-1]] is not None:
                out.append(prev[out[-1]])
            return tuple(out[::-1])
        if d > best.get(m, 1e9):
            continue
        for g in H.gates(m, company):
            n, fee = g['target'], g.get('fee')
            if (n not in ROUTE_MAPS or g.get('hidden') or g.get('gate') or g.get('event_gate') or (g.get('low') and n != dst)
                    or (fee and (fee != KEY_FEE or not keys)) or not K.can_enter(n, company, level)):
                continue
            nd = d + (KEY_HOPS if fee else 1)
            if nd < best.get(n, 1e9):
                best[n], prev[n] = nd, m
                heapq.heappush(todo, (nd, n))
    return None


class Travel:
    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def level(self):
        return int(self.p.d['pilot'].get('level', 1))

    def map_id(self):
        return int(self.w.map_id)

    def can_enter(self, map_id):
        return K.can_enter(int(map_id), self.company(), self.level())

    def keys(self):
        """Silver Booty Keys at hand: in storage, plus the ones 25 Darksilver Coins each would build."""
        p = self.p
        return p.resource(KEY_ITEM) + p.resource(KEY_COIN) // KEY_COINS

    def route(self, dest):
        r = _route(self.map_id(), int(dest), self.company(), self.level(), self.keys() > 0, bool(SET.get('no_level_limit')))
        return list(r) if r is not None else None

    def hops(self, dest):
        r = self.route(dest)
        return len(r) - 1 if r else None

    def portal_to(self, next_map):
        """The portal of this map that leads to next_map (not a gate/mode portal, not a hidden one; the company's own first: on the
        pirate maps every company's portal works)."""
        c = self.company()
        out = [g for g in self.w.gates if g.get('target') == next_map and not g.get('gate') and not g.get('hidden')
               and not g.get('event_gate')]
        return min(out, key=lambda g: g.get('only_company') not in (None, c)) if out else None

    def key_ready(self, now):
        """Before a Silver Booty Key portal: a key in storage, else one built from 25 Darksilver Coins (Assembly) -> whether there is one."""
        if self.p.resource(KEY_ITEM) > 0:
            return True
        return self.craft(KEY_RECIPE, 1, now) == 'done' and self.p.resource(KEY_ITEM) > 0

    def craft(self, recipe, amount, now):
        """An Assembly recipe (Assembly.build, then collect once its time is up) -> 'done' | 'busy' | 'no' (not buildable)."""
        a = getattr(self.session, 'assembly', None)
        if a is None:
            return 'no'
        b = a.st['production'].get(recipe)
        if b is None:
            msgs = a.build({'recipeLootId': recipe, 'amount': amount})
            if msgs:
                self.session.send(msgs, 'auto mode: assembly')
            return 'busy' if recipe in a.st['production'] else 'no'
        if now < b['end_time']:
            return 'busy'
        msgs = a.collect({'recipeLootId': recipe}, now)
        if msgs:
            self.session.send(msgs, 'auto mode: assembly')
        return 'done'

    def enter_portal(self, g, now):
        """Fly to portal g and jump once there -> 'moving' | 'jumping' | 'blocked'."""
        w = self.w
        self.portal_goal = (g.get('gateId'), now)             # the panel's map marks the portal the ship is heading for
        if w.near_gate == g['gateId']:
            if now - self.last_jump_try < JUMP_RETRY_SEC:
                return 'blocked'
            self.last_jump_try = now
            w.jump()
            return 'jumping' if w.jumping else 'blocked'
        self.move_to(g['x'], g['y'], now)
        return 'moving'

    def travel_to(self, dest, now):
        """One step toward map dest -> 'here' | 'moving' | 'jumping' | 'blocked' | 'no_route'."""
        dest = int(dest)
        if self.map_id() == dest:
            return 'here'
        r = self.route(dest)
        if not r or len(r) < 2:
            return 'no_route'
        self.route_goal = (r, now)                             # the maps on the way, for the panel
        g = self.portal_to(r[1])
        if g is None:
            return 'no_route'
        if g.get('fee') == KEY_FEE and self.w.near_gate == g['gateId'] and not self.key_ready(now):
            return 'blocked'                                   # the key is being built (or cannot be)
        return self.enter_portal(g, now)

    def heading(self, now, fresh=2.0):
        """Where the ship is going between maps, for the panel: {'portal': gateId, 'route': [map names]} (orders of the last seconds)."""
        out = {}
        if self.portal_goal and now - self.portal_goal[1] <= fresh:
            out['portal'] = self.portal_goal[0]
        if self.route_goal and now - self.route_goal[1] <= fresh:
            out['route'] = [H.name(m) for m in self.route_goal[0]]
        return out

    def home_map(self):
        """The company's base map (X-1)."""
        return K.ev(self.company())

    def nearest_of(self, maps):
        """The map of the list with the shortest route (the current one if it is in the list)."""
        best = None
        for m in maps:
            n = 0 if int(m) == self.map_id() else self.hops(m)
            if n is not None and (best is None or n < best[0]):
                best = (n, int(m))
        return best[1] if best else None

    def go_to_station(self, now, maps=None):
        """Toward the company's own station (this map's if it has one, else the nearest of maps, default X-1) -> 'here' when at the
        station, else the travel state."""
        w = self.w
        s = w.home_station()
        if s:
            if w.at_station():
                return 'here'
            self.move_to(s['posX'], s['posY'], now)
            return 'moving'
        dest = self.nearest_of(maps or [self.home_map()])
        return self.travel_to(dest, now) if dest is not None else 'no_route'

    # ------------------------------------------------------------ death
    def revive(self):
        """The death screen's free repair at the base (World.kill_screen_repair; on a map without the company's station the server
        sends the ship to its home map) -> whether it was offered."""
        w = self.w
        if W.REPAIR_BASE not in w.repair_offers():
            return False
        w.kill_screen_repair({'selection': {'repairTypeValue': W.REPAIR_BASE}})
        return True

    def map_list(self):
        """The maps the player can enter (the panel's list)."""
        c, lv = self.company(), self.level()
        return [dict(id=m, name=H.name(m)) for m in K.MAPS if H.name(m) != str(m) and K.can_enter(m, c, lv)]
