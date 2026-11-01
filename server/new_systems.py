"""Bu istemcideki yeni sistemlerin oturum düzeyi (yol haritası Aşama 9): N.O.V.A. kaptanları (nova.py), Armory Unlock (armory.py),
Quantum Fluid Core ve Hyperforge (qfc.py), Omega AutoTactic (autopilot.py).

Oturum bağlar: istekler (REQUESTS), girişteki kayıtlı yanıtların yerine profildekiler (login_replace: N.O.V.A. kadrosu, Evocation
Chip sayısı, göstergedeki enerji; login_msgs: QFC listesi), mağazanın ödül yolu (reward: N.O.V.A. ve QFC eşyaları), profilin
bonusları (mods: takılı N.O.V.A.), dünya (attach: istasyonda mı, lazer menzili). Echo sandıkları Deep Space Echoes'un patron
seviyelerinde düşer (echoes.py, qfc.py).
Aşama 9b: Synthesis penceresi (synthesis.py), top/kırıcı/sürücü/mercek ödülleri ve depodan taşıma, sürücü/merceklerin alt nitelik
yenilemesi (LockAttributeItemRerollRequest; particle.py). Uçuştaki atış dünyanın kendi modülünde (parcacik.Atis).
"""
import armory as AU
import nova as NV
import autopilot as OP
import particle as PC
import qfc as QF
import synthesis as SY

LOCK_REQUESTS = {'LockAttributeItemRerollRequest'}            # sürücü/merceğin alt nitelikleri (parcacik.py)
REQUESTS = AU.REQUESTS | NV.REQUESTS | OP.REQUESTS | QF.REQUESTS | SY.REQUESTS | LOCK_REQUESTS


class NewSystems:
    def __init__(self, profile, shop, log=print):
        self.p, self.log = profile, log
        self.nova = NV.Nova(profile, log)
        self.armory = AU.Armory(profile, log)
        self.qfc = QF.Qfc(profile, log)
        self.autopilot = OP.Autopilot(profile, log)
        self.synthesis = SY.Synthesis(profile, log)                  # Aşama 9b: Synthesis penceresi
        for x in (self.nova, self.armory, self.qfc, self.synthesis):
            x.m = shop
        self.m = shop
        self.world = None
        moved = PC.migrate(profile)                                  # depodaki top, kırıcı, sürücü, mercek -> envanter (Aşama 9b)
        if moved:
            log('   parçacık eşyaları depodan envantere: %d' % moved)
        healed = self.qfc.heal()                                    # kaydı olmayan QFC'ler (bağlı gemi, nitelik)
        if healed:
            log('   kaydı olmayan QFC: %d' % len(healed))

    def attach(self, world):
        self.world = world
        self.nova.at_station = world.in_station
        # bot range: a share of the real laser range (menzil_orani), so it does not fight at the very edge
        self.autopilot.laser_range = lambda: world.laser_range() * OP.D['range_ratio']
        self.autopilot.maps = world.omega_maps                   # seçim listeleri: harita -> orada çıkan uzaylılar

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
            self.log('   Singularity Drive yenileme: %s %s' % (self.p.d['esyalar'].get(str(iid)), 'tamam' if ok else 'olmadı'))
            from inventory import update_msgs
            K = PC.D['lock']
            return [('LockAttributeItemRerollCommand', {'result': ok}), PC.lock_list_cmd(self.p)] + \
                (update_msgs(self.m, self.p, [K['renewal_item'], K['lock_item']]) if ok else [])
        return []

    def reward(self, loot, n):
        """Mağazanın ödül yolu: N.O.V.A. (captain_*) kadroya, QFC (equipment_core_*) bağlı gemisiyle envantere; değilse None."""
        if loot.startswith('captain_'):
            return self.nova.hire(loot, n)
        if loot.startswith(QF.PREFIX):
            return self.qfc.grant(loot, n)
        if PC.is_item(loot):
            return self.particle(loot, n)
        return None

    def particle(self, loot, n):
        """Top, kırıcı, sürücü, mercek: ek nitelikleriyle envantere (takılmaz: tür kuralı hangarda)."""
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
        """Giriş demetindeki kayıtlı mesajın yerine profilinki (yoksa None)."""
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
        """Harita yüklenince (hazır demeti): QFC listesi, Synthesis tarifleri, sürücü/merceklerin alt nitelikleri, N.O.V.A. ipucu."""
        return [self.qfc.list_cmd(), self.synthesis.list_cmd(), PC.lock_list_cmd(self.p), self.nova.perk_update_cmd()]
