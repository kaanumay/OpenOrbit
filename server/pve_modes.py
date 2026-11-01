"""Sonsuz ve rogue-lite PvE modlarının oturum düzeyi (yol haritası Aşama 8): portallar, pencereler, istekler, kapı CPU'ları,
girişteki göstergeler ve harita sahipliği.

Modlar: Voyagers' Ascent ve Trinity Trials (arena.py), Astral Ascension (astral.py), Deep Space Echoes (echoes.py), Eternal Black
Light (ebl.py). Quarantine Zone ve Compromising Invasion etkinlik kapısı biçiminde (event_gate.py, takvimsiz).
Pencereli portal (portalın 'pencere'si): atlayınca (J) dünya gate_window'u çağırır; mod penceresini gönderir ya da kendisi harita
değiştirir. Kapı CPU'ları (ammunition_ggportal_*): kısayol çubuğundan; Eternal CPU X-BL'de, Astral CPU X-1'de, Immunizer CPU
X-7'de, Subglacial CPU X-1'de kendi kapısını açar (etkinlik kapılarının kural.cpu'su: gate_cpu; Subglacial açık kapıya 2 can ekler).
"""
import arena as AR
import astral as AS
import echoes as EC
import event_gate as EKP
import map_links as H
import galaxy_gates as KAPI

try:
    import ebl as EB
except ImportError:                   # Eternal Black Light'ın verisi yoksa
    EB = None

WINDOWS = ('voyagers', 'trinityTrials', 'expedition', 'eternal_blacklight', 'rogue_lite')    # özellik çubuğu pencereleri
REQUESTS = {
    'VoyagersUIRequest', 'VoyagersGateEnterRequest', 'VoyagersClaimPassRewardRequest',
    'TrinityTrialsUIRequest', 'TrinityTrialsGateEnterRequest', 'TrinityTrialsDropLevelOptionalRequest', 'TrinityTrialsClaimPassRewardRequest',
    'RogueLiteSelectShipRequest', 'RogueLiteSelectRewardRequest', 'RogueLiteChangeEquipmentRequest',
    'ExpeditionInfoRequest', 'ExpeditionShipListRequest', 'ExpeditionSelectShipRequest', 'ExpeditionActivateShipRequest',
    'ExpeditionBuyTicketRequest', 'ExpeditionJumpTargetLevelRequest', 'ExpeditionResetRequest', 'ExpeditionBackRequest',
    'EternalBlacklightChooseOptionRequest'}


class PveModes:
    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.voyagers = AR.Voyagers(profile, log)
        self.trinity = AR.Trinity(profile, log)
        for a in (self.voyagers, self.trinity):
            a.m = shop
        if shop is not None:
            shop.on_bought.append(self.bought)
        self.astral = AS.Astral(profile, shop, log)
        self.echoes = EC.Echoes(profile, shop, log)
        self.ebl = EB.Ebl(profile, shop, log) if EB else None
        self.send = lambda msgs: None          # oturum bağlar
        self.change_map = None                 # oturum bağlar: (hedef, portal, konum)
        self.world = None
        self.extra_windows = {}                # başka modüllerin pencereli portalları: tür -> (portal, dünya, git)
        self.last_where = 'X-1'                # son açılan kapı penceresinin haritası (günlük giriş sayacı)
        self.maps = {self.voyagers.D['map']: self.voyagers}
        for ids in self.trinity.D['maps'].values():
            self.maps.update({m: self.trinity for m in ids})
        self.maps.update({m: self.astral for m in AS.D['maps']})
        self.maps.update({m: self.echoes for m in [EC.D['hall']] + EC.D['maps']})
        if self.ebl:
            self.maps.update({m: self.ebl for m in self.ebl.maps()})

    def bought(self, loot, amount):
        """Shop purchase (magaza.on_bought): a package with a mode's VIP badge unlocks that pass's VIP track at once,
        so the open window gets the refreshed pass (the client does not ask for it again)."""
        got = {g for g, n in (self.m.contents(loot, amount) or [])}
        return [a.reward_pass.cmd(cmd) for a, cmd in ((self.voyagers, 'VoyagersPassCommand'), (self.trinity, 'TrinityTrialsPassCommand'))
                if a.D.get('vip') in got]

    # ------------------------------------------------------------ dünya
    def portals(self, map_id, station):
        out = self.voyagers.portals(map_id, station) + self.trinity.portals(map_id, station) + self.astral.portals(map_id) \
            + self.echoes.portals(map_id)
        if self.ebl:
            out += self.ebl.portals(map_id)
        return out

    def attach(self, world):
        """Harita açıldı: modun haritasıysa koşusu (dünyanın 'kapi'sı)."""
        self.world = world
        world.portal_cpu = self.portal_cpu
        world.gate_window = self.window
        mode = self.maps.get(int(world.map_id))
        if mode:
            mode.attach(world)
            if mode is self.echoes and int(world.map_id) == EC.D['hall']:
                jump = self.echoes.jump_info_cmd()
                world.send([self.echoes.info_cmd()] + ([jump] if jump[1]['levels'] else []))
        return mode

    def portal_cpu(self, item):
        """Kısayol çubuğundan kapı CPU'su (dünya kilidi altında)."""
        w = self.world
        msgs = None
        if item == AS.D['cpu']:
            msgs = self.astral.use_cpu(w.map_id)
            if msgs:
                for g in self.astral.portals(w.map_id):
                    w.add_gate(g)
        elif self.ebl and item == self.ebl.D['cpu']:
            msgs = self.ebl.use_cpu(w.map_id)
            if msgs:
                for g in self.ebl.portals(w.map_id):
                    w.add_gate(g)
        else:
            key = next((k for k, g in EKP.GATES.items() if g.get('rule', {}).get('cpu') == item), None)
            if key:
                msgs = self.gate_cpu(w, key)
        if msgs is None:
            w.log('   kapı CPU\'su kullanılamaz: %s (%s)' % (item, H.name(w.map_id)))
            msgs = [KAPI.screen('This CPU cannot be used here.')]
        st = self.p.menu_status(item)
        w.send(msgs + ([('MenuItemStatusCommand', st)] if st else []))

    def gate_cpu(self, w, key):
        """Etkinlik kapısının CPU'su (kapının kural.cpu'su): kapının giriş haritasında kapı kurulur ve portalı açılır (Immunizer CPU: X-7'de
        Quarantine Zone, tek can; Subglacial CPU: X-1'de Permafrost Fissure). Kapı açıkken CPU yalnız cpu_can varsa kullanılır: o kadar
        can ekler (Subglacial +2; istemci metni "If it is already open, adds 2 lives")."""
        g, G, item = EKP.GATES[key], self.k.gate(key), EKP.GATES[key]['rule']['cpu']
        if not self.k.here(g['entry'], w.map_id) or (G.get('ready') and not g['rule'].get('cpu_hp')):
            return None
        if self.p.use_ammo(item) is None:
            return None
        if G.get('ready'):
            with self.p.lock:
                G['can'] += g['rule']['cpu_hp']
                self.p.dirty = True
            self.log('   %s: +%d can (%d)' % (g['name'], g['rule']['cpu_hp'], G['can']))
            return [KAPI.screen('%s: %d lives added.' % (g['name'], g['rule']['cpu_hp']), big=True)]
        self.k.enter(key)
        for x in self.k.entry_portals(w.map_id, w.station):
            if x['gate'] == key:
                w.add_gate(x)
        self.log('   %s: %s kapısı' % (item, g['name']))
        return [KAPI.screen('The %s gate has opened.' % g['name'], big=True)]

    # ------------------------------------------------------------ pencereli portallar
    def window(self, g):
        """Dünya kilidi altında: pencereyi gönder ya da haritayı değiştir (zamanlayıcıyla, kilit dışında)."""
        kind = g['windowed']
        w = self.world
        go = lambda dest, pos=None: w.later(0.2, lambda: self.change_map(dest, dict(g, windowed=None), pos))
        if kind in ('voyagers', 'trinity'):
            self.last_where = g.get('entry', 'X-1')
            a = self.voyagers if kind == 'voyagers' else self.trinity
            w.send([a.window(self.last_where)])
        elif kind == 'astral':
            dest, msgs = self.astral.gate_jump()
            w.send(msgs)
            if dest:
                go(dest)
        elif kind == 'astral_reward':
            go(self.astral.choose_gate(g))
        elif kind == 'echoes_entry':
            dest, msgs = self.echoes.enter_hall()
            w.send(msgs)
            if dest:
                go(dest, EC.HALL_ARRIVAL)
        elif kind == 'echoes_start':
            if not self.echoes.st['roster']:
                w.send([KAPI.screen('Choose your ships first (hangar).'), self.echoes.ship_list()])
            else:
                w.send([self.echoes.roster_cmd()])
        elif kind == 'echoes_ship':
            w.send([self.echoes.ship_list()])
        elif kind == 'echoes_exit':
            w.send([('ExpeditionShowUiCommand', dict(type=EC.UI_LEAVE, param0='', param1=''))])
        elif kind == 'ebl' and self.ebl:
            dest, msgs = self.ebl.gate_jump()
            w.send(msgs)
            if dest:
                go(dest)
        elif kind in self.extra_windows:
            self.extra_windows[kind](g, w, go)          # Ö3: Fiesta Gate'in giriş penceresi (fiesta.py)

    def on_jump(self, gate):
        """Oturumun harita değişiminden önce (portal kaydı): Astral'ın çıkışı oyuncunun donanımını geri getirir."""
        if gate and gate.get('astral_exit'):
            self.astral.leaving()

    # ------------------------------------------------------------ istekler
    def handle(self, name, f):
        """Mod istekleri -> mesajlar (harita değişimi gerekiyorsa change_map çağrılır)."""
        v, t, a, e = self.voyagers, self.trinity, self.astral, self.echoes
        if name == 'VoyagersUIRequest':
            return [v.reward_pass.cmd('VoyagersPassCommand')]
        if name == 'VoyagersClaimPassRewardRequest':
            return v.pass_claim(f, 'VoyagersPassCommand')
        if name == 'VoyagersGateEnterRequest':
            dest, msgs = v.enter(f, self.last_where)
            return self.jump(dest) if dest else msgs
        if name == 'TrinityTrialsUIRequest':
            return t.ui(f)
        if name == 'TrinityTrialsClaimPassRewardRequest':
            return t.pass_claim(f, 'TrinityTrialsPassCommand')
        if name == 'TrinityTrialsDropLevelOptionalRequest':
            return t.drop_level_optional(f)
        if name == 'TrinityTrialsGateEnterRequest':
            dest, msgs = t.enter(f, self.last_where)
            return self.jump(dest) if dest else msgs
        if name == 'RogueLiteSelectShipRequest':
            dest = a.select_ship(f)
            return self.jump(dest) if dest else [KAPI.screen('This ship cannot be selected.')]
        if name == 'RogueLiteSelectRewardRequest':
            return a.select_reward(f)
        if name == 'RogueLiteChangeEquipmentRequest':
            return a.change_equipment(f)
        if name == 'ExpeditionInfoRequest':
            # ExpeditionJumpLevelInfoCommand burada değil: istemci onu alınca atlama penceresini açıyor (canlı test H49: Echoes
            # penceresi her açılışta boş bir "Note" penceresi getiriyordu); salona girişte, atlanacak blok varsa
            return [e.info_cmd()]
        if name == 'ExpeditionShipListRequest':
            return [e.ship_list()]
        if name == 'ExpeditionSelectShipRequest':
            return e.select_ships(f)
        if name == 'ExpeditionActivateShipRequest':
            dest, msgs = e.start_level(f)
            return msgs + self.jump(dest) if dest else msgs        # önce pencere kapatma, sonra atlama (H74)
        if name == 'ExpeditionBuyTicketRequest':
            return e.buy_ticket()
        if name == 'ExpeditionJumpTargetLevelRequest':
            return e.jump(f)
        if name == 'ExpeditionResetRequest':
            return e.reset()
        if name == 'ExpeditionBackRequest':
            return self.jump(KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5), 'station')       # Echoes'tan eve: istasyona
        if name == 'EternalBlacklightChooseOptionRequest' and self.ebl:
            return self.ebl.choose(f)
        return []

    def jump(self, dest, pos=None):
        if self.change_map:
            self.change_map(dest, {'gate': 'pve'}, pos)
        return []

    # ------------------------------------------------------------ giriş
    def login_replace(self, name):
        """Kayıttaki giriş mesajı yerine profilinki (yoksa None: olduğu gibi)."""
        if name == 'RogueLiteInfoCommand':
            return [self.astral.info_cmd()]
        if name == 'RogueLiteRankEventInfoCommand':
            return [self.astral.rank_cmd()]
        if name == 'EternalBlacklightInfoCommand' and self.ebl:
            # sıralama listesi kayıtta yok, yalnız koşu bitince gidiyordu: Rank sekmesi "No ranking boards are available" (H76)
            return [self.ebl.info_cmd(), self.ebl.rank_cmd()]
        return None
