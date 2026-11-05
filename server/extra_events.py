"""The events of Ö3 and the big PvE content of Ö4 (roadmap Ö3, Ö4; data in data/extra_events.json <- tools/extra_events.py,
data/major_content.json <- tools/major_content.py): the session-level container.

Every system carries the same face (all optional): REQUESTS (the requests it handles), handle(name, f) -> messages, login_msgs() (in the ready
bundle), login_replace(n, f) (replaces a recorded message in the login bundle; None: leave it), tick(now) -> messages, on_kill(w, npc, x, y)
(under the world lock, while the alien reward is given) -> messages, attach(w) (map opened).
window(item) (window opened: UIButtonTriggerRequest).
Systems: Chromin Rush (chromin.py), Hitac Word Puzzle and Capsule Lottery (hitac_lottery.py), Fever (fever.py), Pursuit of Prestige
(title_hunt.py), Galaxy Trek (galaxy_trek.py), Fiesta Gate (fiesta.py), Infiltration (infiltration.py), Urgent Missions (urgent_quests.py),
the old Invasion (invasion.py), coins left over at the end of an event go to honor (event_end.py); Ö4: Vortex of Greed (vortex.py), Treacherous
Domain / World Boss 2025 (world_boss.py), Mimesis Mutiny (mimesis.py). Those of Ö4 set up the world's gate on the map (waves, death screen, radiation hooks).
1.1.115: Kristallon Apotheosis (apotheosis.py; gate on the boss map), Recall Battle Pass (return_pass.py).
Plutus' Experiments (plutus_experiments.py; beacon tower on maps X-1 / X-5 / 4-4, box by damage tier; Tarnom and Opitite).
Event points, progress thresholds and end-of-event ranking/participation rewards (event_points.py: Hatching Out, Blacklight Surge, Pirate
Raid, Europa; official Turkish forum).
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
import galactic_strife as GS
import team_deathmatch as TDM
import sector_control as SCM
import refraction_zone as RZ
import spaceball as SB
import capture_beacon as CTB
import monthly_rankings as MR


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
        self.end = ES.EventEnd(profile, shop, log)                   # E3: leftover coins go to honor
        self.vortex = VG.Vortex(profile, shop, event_gates, log)                  # Ö4
        self.boss = WB.WorldBoss(profile, shop, event_gates, log)
        self.mimesis = MM.Mimesis(profile, shop, event_gates, log)
        self.apo = APO.Apotheosis(profile, shop, event_gates, log)                # 1.1.115
        self.rbp = RP.ReturnPass(profile, shop, log)
        self.experiment = PEX.PlutusExperiment(profile, shop, log)                       # Plutus' Experiments
        self.points = OP.EventPoints(profile, shop, log)                           # event points (forum: Hatching Out, Blacklight Surge ...)
        self.strife = GS.GalacticStrife(profile, shop, log)                        # Galactic Strife reputation (PvP Summer window)
        self.tdm = TDM.TeamDeathmatch(profile, shop, log)                          # Team Deathmatch with bot teams
        self.sc = SCM.SectorControl(profile, shop, log)                            # Sector Control with bot companies
        self.rzone = RZ.RefractionZone(profile, shop, log)                         # R-Zone standby (the record's answers)
        self.spaceball = SB.Spaceball(profile, shop, log)                          # Spaceball on 4-4
        self.ctb = CTB.CaptureBeacon(profile, shop, log)                           # Capture the Beacon on the X-2 maps
        self.monthly = MR.MonthlyRankings(profile, shop, log)                     # Astral / EBL monthly ranking payouts
        for s in (self.vortex, self.boss, self.mimesis, self.apo, self.points):
            s.titles = self.title.grant_title
        self.boss.send = lambda msgs: self.send(msgs)
        self.systems = [self.chromin, self.hitac, self.fever, self.title, self.trek, self.infiltration, self.urgent, self.end] + \
            [s for s in (self.fiesta, self.invasion) if s] + [self.vortex, self.boss, self.mimesis, self.apo, self.rbp, self.experiment,
                                                            self.points, self.strife, self.tdm, self.sc, self.rzone, self.spaceball, self.ctb, self.monthly]
        self.send = lambda msgs: None            # bound per session
        self.world = None
        self.requests = {}
        for s in self.systems:
            for r in getattr(s, 'REQUESTS', ()):
                self.requests.setdefault(r, []).append(s)      # RankingsEventsInfoRequest: Title Frenzy (3) and World Boss (0/1/2)

    def add(self, system):
        """A system added afterwards (Clan Battle Station: cbs.py; the session sets it up)."""
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
                self.log('   extra events: request error (%s):\n%s' % (name, traceback.format_exc()))
        return out

    def _each(self, meth, *a):
        out = []
        for s in self.systems:
            fn = getattr(s, meth, None)
            if fn:
                try:
                    out += fn(*a) or []
                except Exception:
                    self.log('   extra events: %s error (%s):\n%s' % (meth, type(s).__name__, traceback.format_exc()))
        return out

    def login_msgs(self):
        return self._each('login_msgs')

    def on_ready(self):
        """Map loaded (a ReadyRequest other than the first login)."""
        return self._each('on_ready')

    def event(self, kind, kw):
        """Game event (the session's achievement and quest events): event quests (Galaxy Trek ...)."""
        return self._each('event', kind, kw)

    def window(self, item):
        """Window opened (UIButtonTriggerRequest itemId)."""
        return self._each('window', item)

    def window_update(self, f):
        """The window's state (UIWindowUpdateRequest {itemId, maximized, ...}): on opening, moving, closing."""
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
        """The map's Ö3 portals (Fiesta Gate's X-1 portal)."""
        return self._each('portals', map_id, station)

    def attach(self, world):
        self.world = world
        world.kill_hooks.append(lambda w, n, x, y: self._each('on_kill', w, n, x, y))
        return self._each('attach', world)
