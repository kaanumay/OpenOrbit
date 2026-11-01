"""Infiltration (yol haritası Ö3; veri data/extra_events.json 'sizma').

İstemci: menü öğesi infiltration (pencere 87, "Infiltration Game") InfiltrationStatusCommand {currentNpcs (kalan), maxNpcs,
secondsRemaining} gösterir ("Infiltrators killed: %COUNT%"). Metinler (flashres): msg_infiltration_spawned_map_single (%MAP%),
msg_infiltration_success, msg_infiltration_defeat. Gizli gemi ShipCreateCommand.cloaked ile; görünür olması 0|n|INV|<kimlik>|0.
Kurallar (resmî SSS 2013, fandom): rastgele bir firma haritasında (X-1'de değil) gizli bir komando takımı çıkar; 10 dakikada bulunup
yok edilmeli, yoksa kaçar. Komandolar ateş etmez, mini haritada sarı nokta; vurulunca (ya da EMP'yle) görünür olurlar; olağan
uzaylıdan fazla ödül verirler (2x; kaynaklar 2x/4x diyor). Akşam saatlerinde (19-22) turlar ardı ardına; Şükran Günü haftası.
Tek oyunculu uyarlama: takım oyuncunun firmasının X-2..X-8 haritalarından birinde; oyuncu o haritadaysa (ya da sonradan gelirse)
kalan komandolar haritanın rastgele bir yerinde doğar. Takım boyu, tur arası ve uzaylı türleri veride (_uyarlama); turun
'gizli_patron' olasılığıyla komandolardan biri gizli Boss Kristallon'dur (Uber Kristallon'un ganimeti; fandom Infiltration).
Şirket sıralaması (resmî Türk forumu Sızma SSS: "yan çubukta belirecek"; takımı yok eden şirketine puan): UpdateEventSummaryScoreCommand
{scoreCommandList: [EventSummaryScoreCommand {score, factionModule}], eventEnd, eventType 'Infiltration'} (istemcinin UIScoreSystem'i
bu türde sidebar_infiltration_title_long başlığını gösterir; il2cpp 1.1.115). Oyuncunun firması yok ettiği her takımla +1; öteki
firmalar sanal: her tur sonunda %50 olasılıkla +1 (uyarlama). Puanlar profilde, etkinlik dönemi başına; turlar oturumluk.
"""
import json, os, random, time

import map_links as H
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('sizma', {})
EVENT = 'infiltration'


def active(now=None):
    return EVENT in CAL.active(now)


def in_slot(now=None):
    t = time.localtime(time.time() if now is None else now)
    h = t.tm_hour + t.tm_min / 60.0
    return any(a <= h < b for a, b in D.get('saatler', [[19, 22]]))


class Infiltration:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.round = None                          # {harita, sinif, turler, adet, olen, bitis, dogdu}
        self.next_round = 0.0
        self.outside = 0                          # ortak haritada öteki oyuncuların öldürdüğü komandolar (on_kill; tick sayar)

    def faction(self):
        return self.p.d['pilot'].get('factionId', 2)

    def scores(self, now=None):
        """Bu etkinlik döneminin şirket puanları {'1','2','3'} (dönem değişince sıfır)."""
        span = CAL.period(EVENT, now)
        d = self.p.d.setdefault('sizma', {})
        if span and d.get('donem') != int(span[0]):
            d.update(donem=int(span[0]), puan={'1': 0, '2': 0, '3': 0})
            self.p.dirty = True
        return d.setdefault('puan', {'1': 0, '2': 0, '3': 0})

    def score_cmd(self, now=None):
        s = self.scores(now)
        return ('UpdateEventSummaryScoreCommand', {'eventType': 'Infiltration', 'eventEnd': False, 'scoreCommandList': [
            {'_': 'EventSummaryScoreCommand', 'score': int(s[f]), 'factionModule': {'_': 'FactionModule', 'faction': int(f)}}
            for f in ('1', '2', '3')]})

    def round_over(self, won, now=None):
        """Tur bitti: kazanılırsa oyuncunun firmasına +1; öteki firmalar sanal (%50) -> yan çubuk."""
        s = self.scores(now)
        with self.p.lock:
            if won:
                s[str(self.faction())] = int(s.get(str(self.faction()), 0)) + 1
            for f in ('1', '2', '3'):
                if f != str(self.faction()) and random.random() < 0.5:
                    s[f] = int(s.get(f, 0)) + 1
            self.p.dirty = True
        return [self.score_cmd(now)]

    def status_cmd(self, now=None):
        r = self.round
        now = time.time() if now is None else now
        if not r:
            return ('InfiltrationStatusCommand', {'currentNpcs': 0, 'maxNpcs': 0, 'secondsRemaining': 0})
        # currentNpcs = kalan komando (istemci "killed" sayısını maxNpcs - currentNpcs yazar; canlı)
        return ('InfiltrationStatusCommand', {'currentNpcs': r['adet'] - r['killed'], 'maxNpcs': r['adet'],
                                              'secondsRemaining': max(0, int(r['bitis'] - now))})

    def map_for(self, cls):
        return next((m for m, n in H.NAMES.items() if H.map_class(m) == cls and H.company(m) == self.faction()), 0)

    def start_round(self, now):
        cls = random.choice(D.get('haritalar', ['X-2', 'X-3', 'X-4', 'X-5', 'X-6', 'X-7', 'X-8']))
        pool = D.get('kinds', ['75', '73', '76', '78', '81'])
        n = D.get('adet', 6)
        kinds = [random.choice(pool) for _ in range(n)]
        boss = D.get('hidden_boss')
        if boss and random.random() < boss['probability']:      # gizli Boss Kristallon: bir komandonun yerine (Uber Kristallon'un ganimeti)
            kinds[random.randrange(n)] = boss['tur']
        self.round = dict(harita=self.map_for(cls), sinif=cls, kinds=kinds, adet=n, killed=0,
                          bitis=now + D.get('sure_sn', 600), spawned=False)
        self.log('   Infiltration: komando takımı %s (%d)' % (H.name(self.round['harita']), n))
        msgs = [legacy('0|A|STM|msg_infiltration_spawned_map_single|%%MAP%%|%s' % H.name(self.round['harita'])), self.status_cmd(now)]
        if self.world and int(self.world.map_id) == self.round['harita']:
            self.spawn(self.world)
        return msgs

    def spawn(self, w):
        """Takımın kalan komandoları bu haritada (dünya kilidi altında ya da attach'te)."""
        r = self.round
        if not r or r['spawned'] or int(w.map_id) != r['harita']:
            return
        r['spawned'] = True
        mw, mh = H.map_size(w.map_id)
        cx, cy = random.randint(int(mw * 0.15), int(mw * 0.85)), random.randint(int(mh * 0.15), int(mh * 0.85))
        r['ids'] = []
        for tip in r['kinds'][r['killed']:]:
            if tip not in w.CFG_TYPES:
                continue

            def prep(n):
                n.hidden = True
                n.reward_multiplier = D.get('reward_multiplier', 2)
                n.infiltration = self                     # takımın sahibi (arkadaş sunucusunda öteki oyuncu da vurabilir)
                n.passive = True                     # komandolar ateş etmez (resmî SSS 2013)
                n.summoned = tip == D.get('hidden_boss', {}).get('tur')       # gizli patron ölünce yeniden doğmaz (etkinlik harita kontrolü de silmez)
            n = w.spawn_npc_at(tip, cx + random.randint(-400, 400), cy + random.randint(-400, 400), prep=prep)
            if n is not None:
                n.engaged = False
                r['ids'].append(n.id)

    def attach(self, world):
        self.world = world
        if self.round and active():
            self.spawn(world)
            return [self.status_cmd(), self.score_cmd()]
        return [self.score_cmd()] if active() else []

    def login_msgs(self):
        return [self.status_cmd(), self.score_cmd()] if active() else []

    def on_kill(self, w, npc, x, y):
        owner = getattr(npc, 'infiltration', None)
        if owner is not self:
            if owner is not None:                # öteki oyuncunun takımı: sayaç onun, mesajları onun turunda (tick)
                owner.outside += 1
            return []
        return self.killed()

    def killed(self):
        r = self.round
        if not r:
            return []
        r['killed'] += 1
        if r['killed'] >= r['adet']:
            r['bitis'] = time.time()             # sayaç durur, pencere son durumu (n/n) gösterir
        msgs = [self.status_cmd()]
        if r['killed'] >= r['adet']:
            self.log('   Infiltration: takım yok edildi')
            msgs.append(legacy('0|A|STM|msg_infiltration_success'))
            self.round = None
            self.next_round = time.time() + D.get('ara_sn', 120)
            msgs += self.round_over(True)
        return msgs

    def tick(self, now):
        msgs = []
        while self.outside > 0:
            self.outside -= 1
            msgs += self.killed()
        if msgs:
            return msgs
        if not active(now):
            self.round = None
            return []
        r = self.round
        if r and now >= r['bitis']:
            self.log('   Infiltration: takım kaçtı (%d/%d)' % (r['killed'], r['adet']))
            msgs = [legacy('0|A|STM|msg_infiltration_defeat')]
            w = self.world
            if w and r.get('ids'):
                with w.lock:
                    for uid in r['ids']:
                        n = w.npcs.get(uid)
                        if n and n.alive:
                            w.send(w.remove_npc(n))        # takım kaçtı
            self.round = None
            self.next_round = now + D.get('ara_sn', 120)
            return msgs + [self.status_cmd(now)] + self.round_over(False, now)
        if not r and in_slot(now) and now >= self.next_round:
            return self.start_round(now)
        return []
