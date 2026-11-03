"""Auto Mode: ore (World.harvest / sell_ore, the cargo), ammo purchases (Shop.buy, silent like the auto-buy CPUs)."""
import world as W
from bot import catalog as K

SELL_ORES = tuple(sorted(K.CARGO_ORE - {8}))     # ores that fill the cargo (not Xenomit); Palladium goes to the 5-2 trader as gate energy
RECIPES = {int(t): {int(k): v for k, v in r.items()} for t, r in W.ITEMS['lab']['recipes'].items()}     # laboratory: refined ore -> ores


class Economy:
    def cargo_free(self):
        return self.p.cargo_free()

    def ore_counts(self):
        out = {}
        for t in SELL_ORES:
            n = self.p.ore_count(t)
            if n > 0:
                out[t] = n
        return out

    def harvest(self, h, now):
        """Fly onto ore h and harvest it once there (Base.arrived; World.harvest takes it within ores.harvest_distance) -> whether the
        harvest started."""
        w = self.w
        o = w.ores.get(h)
        if not o or o.get('busy'):
            return False
        if self.arrived(o['x'], o['y'], now, W.ITEMS['ores']['harvest_distance'] - 50):
            w.harvest({'itemHash': h})
            return bool(o.get('busy'))
        self.move_to(o['x'], o['y'], now)
        return False

    def refine(self, t):
        """The laboratory's refining (Shop.refine) of as much ore t as the cargo allows, its refined ingredients first -> the amount made."""
        shop, recipe = self.shop(), RECIPES.get(t)
        if shop is None or not recipe:
            return 0
        for k in recipe:
            if k in RECIPES:
                self.refine(k)
        n = min(self.p.ore_count(k) // v for k, v in recipe.items())
        if n <= 0:
            return 0
        msgs = shop.refine({'toProduce': {'oreType': {'typeValue': t}, 'count': n}})
        if msgs:
            self.session.send(msgs, 'auto mode: refining')
        return n

    def trade_palladium(self, now):
        """Palladium to the pirate trader of 5-2 (World.sell_ore -> trade_palladium: gate energy) -> 'here' once traded, else a travel
        state ('no_route' when 5-2 or its trader is out of reach)."""
        w = self.w
        if str(w.map_id) != W.PIRATE_MARKET:
            st = self.travel_to(int(W.PIRATE_MARKET), now)
            return 'no_route' if st == 'here' else st
        if not w.at_trade():
            spot = next(((x, y) for a, x, y, tip in w.assets if tip == 'ttip_ore_trade'), None)
            if spot is None:
                return 'no_route'
            self.move_to(spot[0], spot[1], now)
            return 'moving'
        w.sell_ore({'toSell': {'oreType': {'typeValue': W.PALLADIUM}, 'count': self.p.ore_count(W.PALLADIUM)}})
        return 'here'

    def sell_maps(self):
        return list(K.sell_maps(self.company()))

    def sell_all(self):
        """At the station: every cargo ore -> the credits earned."""
        w = self.w
        if not w.at_trade():
            return 0
        before = self.p.d['pilot'].get('credits', 0)
        for t, n in self.ore_counts().items():
            w.sell_ore({'toSell': {'oreType': {'typeValue': t}, 'count': n}})
        return self.p.d['pilot'].get('credits', 0) - before

    # ------------------------------------------------------------ shop
    def shop(self):
        return getattr(self.session, 'shop', None)

    def buy_price(self, loot):
        """-> ('credits' | 'uridium', unit price) or None."""
        s = self.shop()
        return s.buy_price(loot) if s is not None else None

    def money(self, currency):
        return self.p.d['pilot'].get(currency, 0)

    def buy(self, loot, n):
        """A silent purchase (no window) -> whether it went through."""
        s = self.shop()
        if s is None:
            return False
        before = self.ammo_count(loot)
        msgs = s.buy(loot, n, quick=True)
        if msgs:
            self.w.send(msgs)
        return self.ammo_count(loot) > before

    def economy_catalog(self):
        s = self.shop()
        ammo = [a for a in list(W.ITEMS['laser_ammo']) + list(W.ITEMS.get('rockets', {})) if s is not None and s.price(a)]
        return dict(ores=[dict(id=int(t), loot=l) for t, l in W.ITEMS['ores']['kinds'].items()], buy_ammo=ammo,
                    cargo_free=self.cargo_free())
