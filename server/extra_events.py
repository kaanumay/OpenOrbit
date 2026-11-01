"""Ö3'ün etkinlikleri ve Ö4'ün büyük PvE içerikleri (yol haritası Ö3, Ö4; veri data/extra_events.json <- tools/extra_events.py,
data/major_content.json <- tools/major_content.py): oturum düzeyindeki kap.

Her sistem aynı yüzü taşır (hepsi isteğe bağlı): REQUESTS (karşıladığı istekler), handle(name, f) -> mesajlar, login_msgs() (hazır
demetinde), login_replace(n, f) (giriş demetindeki kayıtlı mesajın yerine; None: dokunma), tick(now) -> mesajlar, on_kill(w, npc, x, y)
(dünya kilidi altında, uzaylı ödülü verilirken) -> mesajlar, attach(w) (harita açıldı).
window(item) (pencere açıldı: UIButtonTriggerRequest).
Sistemler: Chromin Rush (chromin.py), Hitac Word Puzzle ve Capsule Lottery (hitac_lottery.py), Fever (fever.py), Pursuit of Prestige
(title_hunt.py), Galaxy Trek (galaxy_trek.py), Fiesta Gate (fiesta.py), Infiltration (infiltration.py), Urgent Missions (urgent_quests.py),
eski Invasion (invasion.py), etkinlik sonunda kalan paralar onura (event_end.py); Ö4: Vortex of Greed (vortex.py), Treacherous
Domain / World Boss 2025 (world_boss.py), Mimesis Mutiny (mimesis.py). Ö4'ünkiler haritada dünyanın 'kapi'sını kurar (dalgalar, ölüm ekranı, radyasyon kancaları).
1.1.115: Kristallon Apotheosis (apotheosis.py; patron haritasında 'kapi'), Recall Battle Pass (return_pass.py).
Plutus' Experiments (plutus_experiments.py; X-1 / X-5 / 4-4 haritalarında işaret kulesi, hasar kademesine göre kutu; Tarnom ve Opitite).
Etkinlik puanı, ilerleme eşikleri ve etkinlik sonu sıralama/katılım ödülleri (event_points.py: Hatching Out, Blacklight Surge, Korsan
Baskını, Europa; resmî Türk forumu).
"""
import traceback

import chromin as CHR
import hitac_lottery as HP
import fever as FV
import title_hunt as TH
import galaxy_trek as GTR
import fiesta as FS
import infiltration as INF
import urgent_quests as URG
import invasion as IS
import vortex as VG
import world_boss as WB
import mimesis as MM
import event_end as ES
import apotheosis as APO
import return_pass as RP
import plutus_experiments as PEX
import event_points as OP


class ExtraEvents:
    def __init__(self, profile, shop, event_gates=None, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.chromin = CHR.Chromin(profile, shop, log)
        shop.chromin = self.chromin
        self.hitac = HP.HitacLottery(profile, shop, log)
        shop.hitac = self.hitac
        self.fever = FV.Fever(profile, shop, log)
        self.title = TH.TitleHunt(profile, shop, log)
        self.trek = GTR.GalaxyTrek(profile, shop, log)
        self.trek.titles = self.title.grant_title
        self.fiesta = FS.Fiesta(profile, shop, event_gates, log) if event_gates else None
        self.invasion = IS.Invasion(profile, shop, event_gates, log) if event_gates else None
        self.infiltration = INF.Infiltration(profile, shop, log)
        self.urgent = URG.UrgentQuests(profile, shop, log)
        self.end = ES.EventEnd(profile, shop, log)                   # E3: kalan paralar onura
        self.vortex = VG.Vortex(profile, shop, event_gates, log)                  # Ö4
        self.boss = WB.WorldBoss(profile, shop, event_gates, log)
        self.mimesis = MM.Mimesis(profile, shop, event_gates, log)
        self.apo = APO.Apotheosis(profile, shop, event_gates, log)                # 1.1.115
        self.rbp = RP.ReturnPass(profile, shop, log)
        self.experiment = PEX.PlutusExperiment(profile, shop, log)                       # Plutus' Experiments
        self.points = OP.EventPoints(profile, shop, log)                           # etkinlik puanı (forum: Hatching Out, Blacklight Surge …)
        for s in (self.vortex, self.boss, self.mimesis, self.apo, self.points):
            s.titles = self.title.grant_title
        self.boss.send = lambda msgs: self.send(msgs)
        self.systems = [self.chromin, self.hitac, self.fever, self.title, self.trek, self.infiltration, self.urgent, self.end] + \
            [s for s in (self.fiesta, self.invasion) if s] + [self.vortex, self.boss, self.mimesis, self.apo, self.rbp, self.experiment,
                                                            self.points]
        self.send = lambda msgs: None            # oturum bağlar
        self.world = None
        self.requests = {}
        for s in self.systems:
            for r in getattr(s, 'REQUESTS', ()):
                self.requests.setdefault(r, []).append(s)      # RankingsEventsInfoRequest: Title Frenzy (3) ve World Boss (0/1/2)

    def add(self, system):
        """Kaba sonradan sistem (Clan Battle Station: cbs.py; oturum kurar)."""
        self.systems.append(system)
        for r in getattr(system, 'REQUESTS', ()):
            self.requests.setdefault(r, []).append(system)

    def handles(self, name):
        return name in self.requests

    def handle(self, name, f):
        out = []
        for s in self.requests[name]:
            try:
                out += s.handle(name, f) or []
            except Exception:
                self.log('   Ö3 isteği hatası (%s):\n%s' % (name, traceback.format_exc()))
        return out

    def _each(self, meth, *a):
        out = []
        for s in self.systems:
            fn = getattr(s, meth, None)
            if fn:
                try:
                    out += fn(*a) or []
                except Exception:
                    self.log('   Ö3 %s hatası (%s):\n%s' % (meth, type(s).__name__, traceback.format_exc()))
        return out

    def login_msgs(self):
        return self._each('login_msgs')

    def on_ready(self):
        """Harita yüklendi (ilk giriş dışındaki ReadyRequest)."""
        return self._each('on_ready')

    def event(self, kind, kw):
        """Oyun olayı (oturumun başarım ve görev olayları): etkinlik görevleri (Galaxy Trek …)."""
        return self._each('event', kind, kw)

    def window(self, item):
        """Pencere açıldı (UIButtonTriggerRequest itemId)."""
        return self._each('window', item)

    def window_update(self, f):
        """Pencerenin durumu (UIWindowUpdateRequest {itemId, maximized, …}): açılınca, taşınınca, kapanınca."""
        return self._each('window_update', f)

    def login_replace(self, n, f):
        for s in self.systems:
            fn = getattr(s, 'login_replace', None)
            rep = fn(n, f) if fn else None
            if rep is not None:
                return rep
        return None

    def tick(self, now):
        return self._each('tick', now)

    def portals(self, map_id, station):
        """Haritanın Ö3 portalları (Fiesta Gate'in X-1 portalı)."""
        return self._each('portals', map_id, station)

    def attach(self, world):
        self.world = world
        world.kill_hooks.append(lambda w, n, x, y: self._each('on_kill', w, n, x, y))
        return self._each('attach', world)
