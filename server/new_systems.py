"""Session level of the new systems in this client (roadmap Stage 9): N.O.V.A. captains (nova.py), Armory Unlock (armory.py),
Quantum Fluid Core and Hyperforge (qfc.py), Omega AutoTactic (autopilot.py).

Hooks into the session: requests (REQUESTS), the profile's values in place of the recorded replies at login (login_replace: N.O.V.A.
roster, Evocation Chip count, energy in the indicator; login_msgs: QFC list), the shop's reward path (reward: N.O.V.A. and QFC items),
the profile's bonuses (mods: equipped N.O.V.A.), the world (attach: at the station?, laser range). Echo chests drop at Deep Space Echoes'
boss levels (echoes.py, qfc.py).
Stage 9b: Synthesis window (synthesis.py), cannon/breaker/drive/lens rewards and moving from storage, re-rolling the sub-attributes of
drives/lenses (LockAttributeItemRerollRequest; particle.py). The in-flight shot is in the world's own module (parcacik.Atis).
"""
import armory as AU
import nova as NV
import autopilot as OP
import particle as PC
import qfc as QF
import synthesis as SY

LOCK_REQUESTS = {'LockAttributeItemRerollRequest'}            # sub-attributes of the drive/lens (parcacik.py)
REQUESTS = AU.REQUESTS | NV.REQUESTS | OP.REQUESTS | QF.REQUESTS | SY.REQUESTS | LOCK_REQUESTS


class NewSystems:
    def __init__(self, profile, shop, log=print):
        self.p, self.log = profile, log
        self.nova = NV.Nova(profile, log)
        self.armory = AU.Armory(profile, log)
        self.qfc = QF.Qfc(profile, log)
        self.autopilot = OP.Autopilot(profile, log)
        self.synthesis = SY.Synthesis(profile, log)                  # Stage 9b: Synthesis window
        for x in (self.nova, self.armory, self.qfc, self.synthesis):
            x.m = shop
        self.m = shop
        self.world = None
        moved = PC.migrate(profile)                                  # cannon, breaker, drive, lens in storage -> inventory (Stage 9b)
        if moved:
            log('   particle items from storage to inventory: %d' % moved)
        healed = self.qfc.heal()                                    # QFCs with no record (attached ship, attribute)
        if healed:
            log('   QFC with no record: %d' % len(healed))

    def attach(self, world):
        self.world = world
        self.nova.at_station = world.in_station
        # bot range: a share of the real laser range (menzil_orani), so it does not fight at the very edge
        self.autopilot.laser_range = lambda: world.laser_range() * OP.D['range_ratio']
        self.autopilot.maps = world.omega_maps                   # selection lists: map -> the aliens that appear there

    def handle(self, name, f):
        if name in AU.REQUESTS:
            return self.armory.handle(name, f)
        if name in NV.REQUESTS:
            return self.nova.handle(f)
        if name in QF.REQUESTS:
            return self.qfc.handle(f)
        if name in OP.REQUESTS:
            return self.autopilot.handle(name, f)
        if name in SY.REQUESTS:
            return self.synthesis.handle(name, f)
        if name in LOCK_REQUESTS:
            iid = int(f.get('targetItemId') or 0)
            ok = PC.lock_reroll(self.p, iid, f.get('lockIndexList') or [])
            self.log('   Singularity Drive re-roll: %s %s' % (self.p.d['items'].get(str(iid)), 'done' if ok else 'failed'))
            from inventory import update_msgs
            K = PC.D['lock']
            return [('LockAttributeItemRerollCommand', {'result': ok}), PC.lock_list_cmd(self.p)] + \
                (update_msgs(self.m, self.p, [K['renewal_item'], K['lock_item']]) if ok else [])
        return []

    def reward(self, loot, n):
        """The shop's reward path: N.O.V.A. (captain_*) to the roster, QFC (equipment_core_*) to the inventory with its attached ship;
        otherwise None."""
        if loot.startswith('captain_'):
            return self.nova.hire(loot, n)
        if loot.startswith(QF.PREFIX):
            return self.qfc.grant(loot, n)
        if PC.is_item(loot):
            return self.particle(loot, n)
        return None

    def particle(self, loot, n):
        """Cannon, breaker, drive, lens: to the inventory with their extra attributes (not equipped: the type rule is in the hangar)."""
        from legacy_protocol import legacy
        msgs = []
        for _ in range(n):
            iid = PC.create(self.p, loot)
            msgs += [self.m.inv_item(iid, loot, 1), self.m.pack([self.m.hangar_item(iid, loot, 1)])]
        if loot in PC.DRIVES or loot in PC.LENSES:
            msgs.append(PC.lock_list_cmd(self.p))
        else:
            import ship_module as GM
            msgs.append(GM.list_cmd(self.p))
        return msgs + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]

    def mods(self, map_id):
        return self.nova.mods(map_id)

    def login_replace(self, name):
        """The profile's in place of the recorded message in the login bundle (None if there is none)."""
        if name == 'CaptainRosterListCommand':
            return [self.nova.roster_cmd()]
        if name == 'CaptainGetResourcesBackCommand':
            return [self.nova.chips_cmd()]
        if name == 'QuantumFluidCoreDataListCommand':
            return [self.qfc.list_cmd()]
        if name == 'EnergyUpdateCommand':
            return [self.nova.energy_cmd()]
        return None

    def login_msgs(self):
        """When the map loads (ready bundle): QFC list, Synthesis recipes, sub-attributes of drives/lenses, N.O.V.A. hint."""
        return [self.qfc.list_cmd(), self.synthesis.list_cmd(), PC.lock_list_cmd(self.p), self.nova.perk_update_cmd()]
