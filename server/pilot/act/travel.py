"""Auto Mode: travelling between maps (the bots' portal routes, bot/catalog.route), the death screen's repair, the base station."""
import map_links as H
import world as W
from bot import catalog as K

JUMP_RETRY_SEC = 15.0         # a refused jump (level, key, PvP on 4-X) is not asked again at every step (the client shows why each time)


class Travel:
    def company(self):
        return int(self.p.d['pilot'].get('factionId') or 1)

    def level(self):
        return int(self.p.d['pilot'].get('level', 1))

    def map_id(self):
        return int(self.w.map_id)

    def can_enter(self, map_id):
        return K.can_enter(int(map_id), self.company(), self.level())

    def route(self, dest):
        return K.route(self.map_id(), int(dest), self.company(), self.level())

    def hops(self, dest):
        r = self.route(dest)
        return len(r) - 1 if r else None

    def portal_to(self, next_map):
        """The portal of this map that leads to next_map (not a gate/mode portal, not a hidden one)."""
        return next((g for g in self.w.gates if g.get('target') == next_map and not g.get('gate') and not g.get('hidden')
                     and not g.get('event_gate')), None)

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
