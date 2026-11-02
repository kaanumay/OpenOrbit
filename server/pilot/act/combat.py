"""Auto Mode: combat support. Ship abilities (ship_ability.py, World.abilities), technologies (technology.py, World.tech), the config
switch (Shop.switch_config, as game.py's "S|CFG|n" handler does it) and the P.E.T. (pet.py, World.pet)."""
import pet as PETM
import ship_ability as SA
import technology as TECH

RETRY_SEC = 5.0               # an item that refused (useless now, conditions not met) is not tried again at every step
GEARS = {PETM.PASSIVE: 'Passive', PETM.GUARD: 'Guard', PETM.AUTO_LOOT: 'Auto-looter', PETM.AUTO_RESOURCE: 'Auto-resource collector',
         PETM.ENEMY_LOCATOR: 'Enemy locator', PETM.RESOURCE_LOCATOR: 'Resource locator', PETM.REPAIR_PET: 'P.E.T. repairer',
         PETM.KAMIKAZE: 'Kamikaze', PETM.COMBO_REPAIR: 'Combo ship repair', PETM.COMBO_GUARD: 'Combo guard'}


class Combat:
    # ------------------------------------------------------------ abilities and technologies
    def owned_abilities(self):
        return [i for i in SA.ship_items(self.p) if i in SA.ABILITIES]

    def owned_techs(self):
        return [i for i in TECH.ITEMS if TECH.count(self.p, i) > 0]

    def item_ready(self, item, now):
        """Owned, not running (a toggle that is on counts as running) and its cooldown over."""
        p = self.p
        if item.startswith('ability_'):
            if item not in SA.ship_items(p) or SA.is_active(p, item, now):
                return False
            return SA.timer_fields(p, item, now)['activatable']
        if item.startswith('tech_'):
            return TECH.count(p, item) > 0 and TECH.timer_fields(p, item, now)['activatable']
        return False

    def use_item(self, item, now):
        """Fire an ability / technology -> whether it started."""
        if now - self.tried.get(item, 0) < RETRY_SEC or not self.item_ready(item, now):
            return False
        w = self.w
        ok = w.abilities.activate(item) if item.startswith('ability_') else w.tech.activate(item, now)
        if not ok:
            self.tried[item] = now
        return bool(ok)

    # ------------------------------------------------------------ configs
    def active_config(self):
        return int(self.p.ship().get('active_config', 1))

    def saved_shield(self, cid):
        """The shield the other config kept when the ship left it (each config keeps its own; never used: 0)."""
        return int((self.p.ship().get('shield_generators') or {}).get(str(cid), 0))

    def switch_config(self, n):
        """Like the client's config button (game.py "S|CFG|n"): the shop switches, the flight under way takes the new speed."""
        shop, w = self.shop(), self.w
        if shop is None:
            return False
        before = self.p.d['ship'].get('speed')
        msgs = shop.switch_config(n)
        if not msgs or self.active_config() != int(n):
            return False
        moves = w.respeed_flight(before)
        if moves and w.shared:
            w.shared.mirror(w, moves)
        self.session.send(msgs + moves, 'auto mode: config switch')
        return True

    # ------------------------------------------------------------ P.E.T.
    def pet(self):
        pet = self.w.pet
        return pet if pet is not None and pet.owned else None

    def pet_gears(self):
        pet = self.pet()
        return [g for g, lv, usable in pet.gear_list() if usable] if pet else []

    def pet_state(self):
        pet = self.pet()
        if pet is None:
            return None
        return dict(active=bool(pet.active), destroyed=bool(pet.d.get('destroyed')), gear=pet.d.get('gear'), fuel=pet.d.get('fuel', 0),
                    relaunch=bool(getattr(pet, 'relaunch', False)), repair_cost=pet.repair_cost())

    def pet_launch(self, gear):
        pet = self.pet()
        if pet is None or gear not in self.pet_gears():
            return False
        pet.launch_into(gear)
        return bool(pet.active)

    def pet_gear(self, gear):
        pet = self.pet()
        if pet is None or not pet.active or gear not in self.pet_gears() or pet.d.get('gear') == gear:
            return False
        pet.select(gear)
        return pet.d.get('gear') == gear

    def pet_repair(self):
        pet = self.pet()
        if pet is None or not pet.d.get('destroyed'):
            return 0
        cost = pet.repair_cost()
        pet.repair()
        return cost if not pet.d.get('destroyed') else None

    def combat_catalog(self):
        pet = self.pet()
        return dict(abilities=self.owned_abilities(), techs=self.owned_techs(),
                    pet_gears=[dict(id=g, name=GEARS.get(g, str(g))) for g in self.pet_gears()] if pet else [],
                    has_pet=pet is not None, configs=sorted(int(c) for c in self.p.ship().get('configs', {})))
