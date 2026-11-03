"""Auto Mode: galaxy gates from the builder to the last wave (galaxy_gates.py: the session's Gates, the gate map's Run, the gate portal on
the company's X-1)."""
import galaxy_gates as GG


class Gates:
    def gate_book(self):
        return getattr(self.session, 'gates', None)

    def gate_run(self):
        """The waves on this map (galaxy_gates.Run, also the event gates' and modes' subclasses) or None."""
        return self.w.gate or None

    def gate_portal(self):
        """In a galaxy gate once the wave is over: the portal to the next wave (galaxy_gates.next_portal, the left one in the middle; the
        right one, exit=True, goes home). None otherwise."""
        run = self.gate_run()
        if run is None or getattr(run, 'phase', None) not in ('move', 'void'):
            return None
        return next((g for g in self.w.gates if g.get('gate') and not g.get('exit')), None)

    def jump_from(self, g):
        """Jump through portal g once the ship is close enough (World.near_gate, set by the world loop)."""
        return self.w.near_gate == g['gateId'] and self.w.jump()

    def in_gate(self, key=None):
        run = self.gate_run()
        return run is not None and (key is None or getattr(run, 'key', None) == key)

    def gate_info(self, key):
        g = self.gate_book()
        if g is None or key not in GG.GATES:
            return None
        G = g.gate(key)
        return dict(key=key, name=GG.GATES[key]['name'], built=bool(g.built(key)), ready=bool(G.get('ready')), lives=int(G.get('hp', 0)),
                    wave=int(G.get('wave', 0)), waves=len(GG.GATES[key]['waves']), parts=len(G.get('parts', [])),
                    need=GG.GATES[key]['part'], life_price=g.life_price(key), lives_bought=int(G.get('lives_bought', 0)),
                    max_bought=len(GG.K['life_prices']), energy=int(g.d['energy']), spin_price=int(g.energy_price()[0]),
                    producible=not GG.GATES[key].get('not_producible'))

    def gate_prepare(self, key):
        """The builder's PREPARE JUMP (Gates.setup): the gate's portal appears on X-1 -> whether the gate is ready."""
        g = self.gate_book()
        msgs = g.setup({'gateId': GG.GATES[key]['uid']})
        self.session.send(msgs, 'auto mode: gate prepared')
        return bool(g.gate(key).get('ready'))

    def gate_spin(self, key, n):
        """n spins in the Galaxy Gate Generator (Gates.spin: free energy first, then uridium; it stops once the gate is built) -> the uridium
        paid, or None when it refused."""
        g = self.gate_book()
        before = g.money()
        msgs = g.spin({'gateId': GG.GATES[key]['uid'], 'spinAmount': n})
        self.session.send(msgs, 'auto mode: gate spins')
        if any(m[0] == 'GalaxyGateBuilderMultiEnergyCommand' and m[1].get('errorCode') for m in msgs if isinstance(m, tuple)):
            return None
        return before - g.money()

    def gate_buy_life(self, key):
        """One more life (Gates.buy_life, uridium) -> the price paid, or None."""
        g = self.gate_book()
        before = g.money()
        msgs = g.buy_life({'gateId': GG.GATES[key]['uid']})
        self.session.send(msgs, 'auto mode: gate life')
        paid = before - g.money()
        return paid if paid > 0 else None

    def gate_home(self):
        g = self.gate_book()
        return g.home() if g is not None else self.home_map()

    def gate_entry(self, key):
        """The gate's portal on this map (X-1, next to the base)."""
        return next((x for x in self.w.gates if x.get('gate') == key and not x.get('exit') and not x.get('event_gate')), None)

    def gates_catalog(self):
        if self.gate_book() is None:
            return []
        return [self.gate_info(k) for k in GG.GATES]
