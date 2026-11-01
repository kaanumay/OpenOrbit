"""Etkinlik kapıları (yol haritası Aşama 7b; veri data/event_gates.json <- tools/event_gates.py).

Üreticideki kapılardan farkı: parça yok; etkinliği (event_calendar.py) sürerken giriş haritasında (X-1, X-4, X-8) portalı durur. Portaldan
girince kapı kurulur (canlar, dalga sırası, başlangıç zamanı); dalgalar, alt gruplar, canlar, kalıcı patronlar ve çok haritalı akış
kapi.Kosu'nunkiyle aynı (dalga biçimi gates.json'unki). Kurallar ('kural'):
  gunluk          günde bir giriş (aynı 'grup'taki kapılar birlikte: Gauntlet of Plutus Easy ya da Normal)
  bekleme_sn      bittikten ya da canlar tükendikten sonra bekleme (Trial of Terrors 12 saat)
  yillik          yılda bir (Birthday Gate)
  cpu             portalı yalnız CPU açar (Quarantine Zone: Immunizer CPU, X-7; Permafrost Fissure: Subglacial CPU, X-1; pve_modes.py);
                  cpu_can: kapı açıkken CPU kullanılırsa eklenen can (Subglacial CPU +2; istemci metni)
  gorev           yalnız bu görev (kimliği) sürerken girilir (Devolarium Attack: "Preemptive Strike Force" 20012; bitince görevin
                  FINISH_STARTER_GATE koşulu için kapi_turu STARTER_GATE); konum: {firma kimliği: [x, y]} X-1'deki portalın kaynaklı yeri
                  (Devolarium Attack'in wiki koordinatı; yoksa portallar haritanın ortasında yayda dizilir)
  seviye, bir_kez en düşük seviye; bir kez tamamlanabilir (Compromising Invasion; The Breach Hard 16+)
  rastgele        her haritanın dalgaları kendi aralarında rastgele sırayla ('sabit' dalga, Plutus, sonda; Gauntlet of Plutus)
  portallar       harita geçişinde bu kadar portal (hepsi rastgele sıradaki haritaya) ve solda üsse dönüş; haritalar da karışık,
                  son harita sonda (Trial of Terrors 3)
  sure            bitiş süresi ölçülür (ölü geçen süre dahil); en iyi süreler profilde (Gauntlet of Plutus'un kişisel rekoru)
'secenek' grubundaki dalgalardan (Vortex'in "ya da" dalgaları) girişte biri seçilir. Dalga uzaylısının 'kutu'su ölünce düşer
(event_maps.py: Plutus Box, Demon Drone Box …); 'ek_turler' dalga dışı türler (Plutus'un Warhead'leri).
Ödüller ('odul'): EP, onur, kredi, uridyum ve eşyalar (mağazanın ödül işleviyle).
Profilde: etkinlik_kapilari {kapı: {hazir, dalga, can, sira, bas, tamam, son_gun, son_yil, son_bitis, en_iyi_sn, sureler}}.
Gauntlet of Plutus'un göstergesi istemcinin PlutusInfoCommand / PlutusStatusCommand'ıyla (can, mod, kalan süre, en iyi süreler).
Takvimsiz kapılar ('etkinlik' yok): Quarantine Zone ve Compromising Invasion (yol haritası Aşama 8), Permafrost Fissure (Subglacial CPU
ile açılır, 45 dalga, UFO ve Ufonit Proxium kutusu düşürür: etkinlik_harita.roll) ve Devolarium Attack (başlangıç kapısı, görevle).
The Breach (Cold Wave 2014, Easy 77 / Hard 78) kış etkinliğine ('kis') bağlı.
Frozen Labyrinth ayrı (labyrinth.py); X-1'deki giriş portalı burada.
"""
import datetime, json, math, os, random, time

import map_links as H
import galaxy_gates as KAPI
import rankings as RK
import event_calendar as CAL
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'event_gates.json'), encoding='utf8'))
GATES = D['kapilar']
DARK_MAPS = {int(m) for g in GATES.values() if g.get('karanlik') for m in g['haritalar']}      # el feneri (dunya.map_effect_msgs)
BY_MAP = {m: k for k, g in GATES.items() for m in g['haritalar']}
LAB = D['labirent']
PORTAL_BASE = 151900000                 # + kimlik (giriş), + 50 + kimlik (eve dönüş), + 100 + kimlik (sonraki harita)
LAB_ENTRY = PORTAL_BASE + 99            # X-1'deki Frozen Labyrinth portalı
# PlutusStatusCommand.mode: pencerenin durum satırı (istemci PlutusUIData.UpdateStatus): 0/1 bugün bitti ("Next Gauntlet opens in",
# geri sayım), 2 açık ("Time left to defeat Plutus", geri sayım), 3 sürüyor ("Time spent in the Gauntlet", ileri sayım), 4 etkinlik
# bitti ("Rankings will be tallied in"). Önce kolay/normal sanılıyordu: koşu sürerken "bugün bitirdin" yazıyordu (canlı test H48)
PLUTUS_DONE, PLUTUS_OPEN, PLUTUS_RUNNING = 1, 2, 3


def poi(pid, x, y, r, ptype=4, design=6):
    """MapAddPOICommand (dunya_patronu.poi'nin biçimi; ptype 4 / design 6: yeşil iyileşme dairesi)."""
    return ('MapAddPOICommand', dict(inverted=False, poiTypeSpecification='', poiType=KAPI.mod('POITypeModule', typeValue=ptype), shape=0,
                                     active=True, design=KAPI.mod('POIDesignModule', designValue=design), poiId=pid,
                                     shapeCoordinates=[int(x), int(y), int(r)]))


def npc_type(key, wave, i):
    return 'eg_%s_%d_%d' % (key, wave, i)


def extra_type(key, name):
    return 'eg_%s_ek_%s' % (key, name)


def time_score(secs):
    """Plutus süre skoru (forum 143902: skor süreye bağlı, 60 dk üstü puansız; formül kaynakta yok: uyarlama)."""
    return max(0, int(round(1000 * (3600 - secs) / 3600.0)))


def _tip(a, key=None, aggressive=True):
    d = dict(ad=a['gorunen_ad'], model=str(a['tur']), hp=a['hp'], kalkan=a['kalkan'], hasar=a['hasar'], hiz=a['hiz'],
             saldirgan=a.get('saldirgan', aggressive), odul=dict(a['odul']), kargo=dict(a.get('kargo', {})), npc_kimlik=a['npc_kimlik'])
    if key:
        d['kapi'] = key
    for k in ('kutu', 'davranis', 'anahtar', 'dusme', 'yeniden_sn', 'puan', 'ek_odul', 'cpu_artis', 'radyoaktif', 'menzil', 'isabet',
              'kalkan_emme', 'kacak', 'guclendir'):
        if a.get(k):
            d[k] = a[k]
    return d


# etkinlik puanının başarımdaki etkinlik adı (basarim.py EventScore: "bir Gauntlet of Plutus etkinliğinde 1.000 / 5.000 / 10.000 puan")
SCORE_EVENTS = {'plutus': 'GauntletOfPlutus'}


def register_npcs(types):
    """Kapı ve labirent uzaylılarını NPC türleri olarak ekler (kapi.register_npcs'in biçimi)."""
    for key, g in GATES.items():
        for n, w in enumerate(g['waves']):
            for i, a in enumerate(w['uzaylilar']):
                types[npc_type(key, n, i)] = _tip(a, key)
        for name, a in g.get('extra_kinds', {}).items():
            types[extra_type(key, name)] = _tip(a, key)
        for k in [k for k in types if k.startswith(('eg_%s_' % key))]:
            types[k].setdefault('kalkan_emme', KAPI.GATE_ABSORB)      # kapı uzaylıları %50 (kapi.GATE_ABSORB)
    for k, a in LAB['uzaylilar'].items():
        types[k] = _tip(a, aggressive='meteoroid' not in k and 'synk' not in k)


def center(map_id):
    w, h = H.map_size(map_id)
    return w // 2, h // 2


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()


def fmt_time(secs):
    m, s = divmod(int(secs), 60)
    return '%d:%02d:%02d' % (m // 60, m % 60, s) if m >= 60 else '%d:%02d' % (m, s)


class EventGates:
    """kapi.Kapilar'ın arayüzü (gate, finish, exit_portal, next_portal, home, p) etkinlik kapıları için."""

    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                       # mağaza (eşya ödülleri)
        self.finish_hooks = []              # kapı bitince (anahtar) -> mesajlar (Fiesta Gate'in AP'si: fiesta.py)
        self.wave_hooks = []                # dalga bitince (anahtar, toplam dalga) -> mesajlar (eski Invasion: istila.py)

    @property
    def d(self):
        return self.p.d.setdefault('event_gates', {})

    def gate(self, key):
        return self.d.setdefault(key, dict(hazir=False, dalga=0, can=GATES[key]['can'], tamam=0))

    def home(self):
        return KAPI.HOME_MAP.get(self.p.d['pilot'].get('factionId'), 5)

    # ------------------------------------------------------------ giriş
    def allowed(self, key, now=None):
        """-> (girilebilir mi, neden)."""
        now = time.time() if now is None else now
        g, G = GATES[key], self.gate(key)
        if G.get('hazir'):
            return True, 'sürüyor'
        if g.get('etkinlik') and not CAL.is_active(g['etkinlik'], now):
            return False, 'etkinlik yok'
        rule = g.get('kural', {})
        if SET.get('giris_siniri_yok'):                       # panel: günlük/yıllık/bir kez ve bekleme süresi yok
            rule = {k: v for k, v in rule.items() if k not in ('bir_kez', 'gunluk', 'yillik', 'bekleme_sn')}
        if rule.get('cpu'):
            return False, 'CPU ile açılır'            # Quarantine Zone, Permafrost Fissure: CPU kapıyı kurar (pve_modlari.py)
        if rule.get('gorev') and str(rule['gorev']) not in (self.p.d.get('gorevler') or {}).get('aktif', {}):
            return False, 'görev gerekli'             # Devolarium Attack: yalnız "Preemptive Strike Force" görevi sürerken
        if rule.get('seviye') and self.p.d['pilot'].get('level', 1) < rule['seviye']:
            return False, 'seviye %d gerekli' % rule['seviye']
        if rule.get('azami_seviye') and self.p.d['pilot'].get('level', 1) > rule['azami_seviye']:
            return False, 'seviye en çok %d' % rule['azami_seviye']          # eski Invasion: seviye aralığına göre kapı
        if rule.get('firma') and rule['firma'] != self.p.d['pilot'].get('factionId'):
            return False, 'başka firmanın kapısı'
        if rule.get('bir_kez') and G.get('tamam', 0) > 0:
            return False, 'tamamlandı'
        if rule.get('gunluk'):
            group = [k for k, x in GATES.items() if x.get('kural', {}).get('grup', k) == rule.get('grup', key)]
            if any(self.gate(k).get('last_day') == today(now) for k in group):
                return False, 'bugün girildi'
        if rule.get('yillik') and G.get('last_year') == today(now)[:4]:
            return False, 'bu yıl girildi'
        if rule.get('gunluk') and 0 < 86400 - (now - time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))) < 300:
            return False, 'günlük sıfırlamaya 5 dk kaldı'                # forum 143902
        if rule.get('donem') and not CAL.forced(g.get('etkinlik')) and not CAL._span_at(rule['donem'], datetime.datetime.fromtimestamp(now)):
            return False, 'kapı dönemi dışında'                            # The Breach: 11 Aralık - 1 Ocak (forum 134831)
        if rule.get('bekleme_sn') and now < G.get('last_end', 0) + rule['bekleme_sn']:
            return False, 'bekleme %d sn' % (G['last_end'] + rule['bekleme_sn'] - now)
        return True, ''

    def here(self, want, map_id):
        if want == 'X-1':
            return int(map_id) == self.home()
        return H.map_class(map_id) == want and H.company(map_id) == self.p.d['pilot'].get('factionId')

    def entry_portals(self, map_id, station, now=None):
        """Bu haritadaki etkinlik kapısı portalları (etkinlik sürerken ve girilebilirken) ve X-1'de Frozen Labyrinth'inki."""
        now = time.time() if now is None else now
        out = []
        for key in sorted(GATES):
            g = GATES[key]
            if g.get('kural', {}).get('pencere'):
                continue                    # pencereli giriş (Fiesta Gate: tek portal, zorluğu pencere seçer; fiesta.py)
            if not self.here(g['giris'], map_id) or not self.allowed(key, now)[0]:
                continue
            dest = self.dest(key)
            out.append(dict(gateId=PORTAL_BASE + g['kimlik'], x=0, y=0, hedef=dest, designId=g['portal'], kapi=key,
                            event_gate=True, varis=center(dest)))
        if self.here(LAB['giris'], map_id) and CAL.is_active(LAB['etkinlik'], now):
            import labyrinth as LB
            dest = random.choice(LAB['baslangic'])
            out.append(dict(gateId=LAB_ENTRY, x=0, y=0, hedef=dest, designId=LAB['portal'], kapi='labirent',
                            varis=LB.arrival_spot(dest)))
        # açık portallar haritanın ortasının üst yanında, yay üzerinde yan yana (wiki: Level Invasion kapıları haritanın ortasında;
        # resmî sunucu kaydı: 2-1'deki etkinlik portalları orta sütunda, (10700, 3000) ile (11210, 6310) arası). Önceden üssün
        # arkasında köşeye doğru diziliyordu.
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2
        for i, g in enumerate(out):
            a = -math.pi / 2 + (i - (len(out) - 1) / 2.0) * 0.55
            g['x'], g['y'] = int(cx + math.cos(a) * 2400), int(cy + math.sin(a) * 2400)
            pos = (GATES.get(g['kapi'], {}).get('position') or {}).get(str(self.p.d['pilot'].get('factionId')))
            if pos:
                g['x'], g['y'] = pos                    # kaynaklı konum (Devolarium Attack: wiki'nin firma başına X-1 koordinatı)
        return out

    def enter(self, key, now=None):
        """Portaldan girildi: kurulu değilse kapı kurulur (canlar, dalga sırası, süre)."""
        now = time.time() if now is None else now
        g, G = GATES[key], self.gate(key)
        if G.get('hazir'):
            return
        waves = g['waves']
        groups = {}
        for i, w in enumerate(waves):
            if w.get('option'):
                groups.setdefault(w['option'], []).append(i)
        pick = {s: random.choice(v) for s, v in groups.items()}       # "ya da" dalgalarından biri
        order = [i for i, w in enumerate(waves) if not w.get('option') or pick[w['option']] == i]
        if g.get('kural', {}).get('rastgele'):        # aynı haritanın dalgaları kendi aralarında karışır
            by_map = {}
            for i in order:
                by_map.setdefault(waves[i]['harita'], []).append(i)
            order = []
            maps = sorted(by_map, key=lambda m: min(by_map[m]))
            if g['kural'].get('portals'):          # Trial of Terrors: haritalar da karışık, son harita (patron) sonda
                head = maps[:-1]
                random.shuffle(head)
                maps = head + maps[-1:]
            for m in maps:
                part = by_map[m]
                rest = [i for i in part if not waves[i].get('sabit')]
                random.shuffle(rest)
                order += rest + [i for i in part if waves[i].get('sabit')]
        with self.p.lock:
            G.update(hazir=True, dalga=0, can=SET.count('kapi_can', g['can']), sira=order, bas=now, last_day=today(now),
                     last_year=today(now)[:4])                   # panel: kapı canı
            self.p.dirty = True
        self.log('   %s kuruldu (%d dalga, %d can)' % (g['ad'], len(order), G['can']))

    def dest(self, key):
        """Kapıya girince inilecek harita: süren kapıda sıradaki dalganınki, kurulmamışsa ilk dalganınki."""
        G, g, order = self.gate(key), GATES[key], self.order(key)
        return g['waves'][order[min(G['dalga'], len(order) - 1)]]['harita'] if G.get('hazir') else g['waves'][0]['harita']

    def order(self, key):
        G = self.gate(key)
        return G.get('sira') or list(range(len(GATES[key]['waves'])))

    # ------------------------------------------------------------ portallar
    def exit_portal(self, key, map_id, side=False):
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + 50 + GATES[key]['kimlik'], x=x - 1500 if side else x, y=y, hedef=self.home(), designId=1,
                    kapi=key, cikis=True, varis='istasyon')

    def next_portal(self, key, map_id, dest):
        x, y = center(map_id)
        return dict(gateId=PORTAL_BASE + 100 + GATES[key]['kimlik'], x=x, y=y, hedef=dest, designId=GATES[key]['portal'], kapi=key,
                    varis=center(dest))

    def next_portals(self, key, map_id, dest):
        """Sonraki haritanın portalları: kuralın 'portallar' sayısı kadar (Trial of Terrors 3; hepsi rastgele sıradaki haritaya: fandom
        Vortex of Terror "dalgalar portallarla rastgele, hangi portalın hangi dalgaya götürdüğü bilinmez"; oyuncu bildirimi 2026-10-27:
        3 portal, solda üsse dönüş) ya da tek portal."""
        n = GATES[key].get('kural', {}).get('portals', 1)
        one = self.next_portal(key, map_id, dest)
        return [dict(one, gateId=one['gateId'] + 200 * j, y=one['y'] + (j - (n - 1) / 2.0) * 1400) for j in range(n)]

    # ------------------------------------------------------------ bitiş
    def end(self, key, now=None):
        now = time.time() if now is None else now
        with self.p.lock:
            G = self.gate(key)
            G.update(hazir=False, dalga=0, can=GATES[key]['can'], last_end=now)
            G.pop('sira', None)
            G.pop('cpu_artis', None)
            self.p.dirty = True

    def finish(self, key, reward_msgs=None):
        """Son dalga bitti: ödüller, süre (en iyi), kapı kapanır -> (mesajlar, bilgi)."""
        g, G, now = GATES[key], self.gate(key), time.time()
        o = g.get('odul', {})
        msgs = []
        cbs = self.p.cbs_mods() if getattr(self.p, 'cbs_mods', None) else {}
        currency = {k: SET.amount(k, int(o[k] * (1 + cbs.get(k, 0))) if k in ('ep', 'onur') else o[k], 'kapi')
                for k in ('ep', 'onur', 'kredi', 'uridyum') if o.get(k)}      # panelin çarpanları
        if currency:
            tot = self.p.gain(neden='galaxy_gate_done', **currency)
            msgs += reward_msgs(tot, **currency) if reward_msgs else []
        for loot, n in o.get('esyalar', []):
            n = random.randint(*n) if isinstance(n, list) else n          # aralık (Indoctrine Oil 0-20)
            if n > 0 and self.m:
                msgs += self.m.prize(loot, n, 'kapi')        # panel: kapı/mod ödülü çarpanı
        if o.get('biri') and self.m:                       # olasılık ağırlıklı biri (Quarantine Box'ın mühimmat paketi)
            loot, n, _ = random.choices(o['biri'], weights=[w for _, _, w in o['biri']])[0]
            msgs += self.m.prize(loot, random.randint(*n) if isinstance(n, list) else n, 'kapi')
        for loot, n, chance in o.get('sans', []):          # şanslı ödül (Quarantine Box'ın LF-4'ü)
            if random.random() < SET.chance('dusme', chance, 'kapi') and self.m:
                msgs += self.m.prize(loot, n, 'kapi')
        if o.get('rolls') and self.m:                     # Karantina: Indoctrine Oil ruloları (forum 140274)
            loot, rows = o['rolls']
            n = sum(random.randint(*a) if isinstance(a, list) else a for a, c in rows if random.random() < SET.chance('dusme', c, 'kapi'))
            msgs += self.m.prize(loot, n, 'kapi') if n else []
        bp = o.get('big_pack')
        if bp and self.m and random.random() < SET.chance('dusme', bp['probability'], 'kapi'):     # %0,001 Büyük Ödül Paketi
            for loot, n in bp['esyalar']:
                if loot == 'premium_30':
                    self.p.d['pilot']['premium'] = True        # tek oyunculuda Premium hep açık: yalnız kayıt
                    continue
                msgs += self.m.prize(loot, n, 'kapi')
        c = g.get('cpu')
        if c and self.m and random.random() < SET.chance('dusme', c['taban'] + G.get('cpu_artis', 0.0), 'kapi'):
            msgs += self.m.prize(c['esya'], 1, 'kapi')     # Bountiful Alien CPU: temel şans, öldürülen Aura Dun Jig başına artar
        secs = int(now - G.get('bas', now))
        best = G.get('best_sec')
        with self.p.lock:
            G['tamam'] = G.get('tamam', 0) + 1
            if g.get('kural', {}).get('sure') and g.get('mod') != 'kolay' and secs <= 3600:   # forum 143902: yalnız Normal, 60 dk altı
                if best is None or secs < best:
                    G['best_sec'] = secs
                G['durations'] = sorted(G.get('durations', []) + [secs])[:5]
            self.p.dirty = True
        self.end(key, now)
        for fn in self.finish_hooks:
            msgs += fn(key)
        self.p.ach('gate', tur=g.get('gate_kind') or '%s_GATE' % key.upper())    # istemcinin GalaxyGateType'ı (Birthday: BIRTHDAY)
        record = G.get('best_sec') == secs and best != secs
        if record:
            self.p.ach('rekor_plutus')               # şampiyon başarımı (Gauntlet of Plutus; süreli tek kapı): kişisel rekor
        self.log('   %s tamamlandı: %s%s' % (g['ad'], fmt_time(secs), ' (yeni rekor)' if record else ''))
        return msgs, dict(yeni={'parcalar': []}, kronos=None, sure=secs)

    # ------------------------------------------------------------ etkinlik puanı (Gauntlet of Plutus)
    def score(self, key, now=None):
        """Bu etkinlik dönemindeki puan kaydı {donem, puan}: Easy ve Normal birlikte; yeni dönemde sıfırdan."""
        ev = GATES[key].get('etkinlik') or key
        p = CAL.period(ev, now) if ev in CAL.EVENTS else None
        period = int(p[0]) if p else 0
        rec = self.d.setdefault('puan', {}).get(ev)
        if not rec or rec.get('donem') != period:
            rec = self.d['puan'][ev] = {'donem': period, 'puan': 0}
        return rec

    def add_points(self, key, n, now=None):
        """Uzaylının etkinlik puanı (kaynak: uzaylı başına aralık, forum 2019) -> PlutusPointsUpdateCommand; başarım olayı."""
        with self.p.lock:
            rec = self.score(key, now)
            rec['puan'] += n
            self.p.dirty = True
        ev = GATES[key].get('etkinlik')
        if ev in SCORE_EVENTS:
            self.p.ach('event_score', etkinlik=SCORE_EVENTS[ev], deger=rec['puan'])
        G = self.gate(key)
        entries = [dict(_='PlutusScoreEntryModule', score=time_score(s), timeInSeconds=int(s)) for s in G.get('durations', [])]
        return [('PlutusPointsUpdateCommand', dict(scoreEntriesList=entries, score=rec['puan']))]

    # ------------------------------------------------------------ Gauntlet of Plutus göstergesi
    def plutus_cmds(self, key, now=None):
        g = GATES.get(key, {})
        if not g.get('kural', {}).get('sure'):
            return []
        now = time.time() if now is None else now
        G = self.gate(key)
        group = [k for k, x in GATES.items() if x.get('kural', {}).get('grup') == g.get('kural', {}).get('grup')] or [key]
        done_today = any(self.gate(k).get('last_day') == today(now) and not self.gate(k).get('hazir') for k in group)
        if G.get('hazir') and G.get('bas'):
            mode, t = PLUTUS_RUNNING, now - G['bas']                     # geçen süre
        elif done_today:
            tomorrow = datetime.datetime.combine(datetime.date.fromtimestamp(now) + datetime.timedelta(days=1), datetime.time())
            mode, t = PLUTUS_DONE, tomorrow.timestamp() - now            # yarına kalan
        else:
            mode, t = PLUTUS_OPEN, CAL.time_left(g['etkinlik'], now)      # etkinliğin kalan süresi
        status = dict(_='PlutusStatusCommand', lifes=int(G.get('can', g['can'])), mode=mode, timeLeft=int(max(0, t)))
        entries = [dict(_='PlutusScoreEntryModule', score=time_score(s), timeInSeconds=int(s)) for s in G.get('durations', [])]
        return [('PlutusInfoCommand', dict(playerPoints=int(self.score(key, now)['puan']), scoreEntriesList=entries, status=status,
                                           playerRanges=RK.ranges(RK.PLUTUS),          # ödül sekmesinin aralıkları (Ö1)
                                           filename=''))]


class Run(KAPI.Run):
    """Etkinlik kapısı haritasında dalgalar: kapi.Kosu, EtkinlikKapilari'nın dalga sırası, bitişi ve canlarıyla."""

    def __init__(self, event_gate, world, key):
        self.k, self.w, self.key = event_gate, world, key
        self.g = GATES[key]
        self.map = int(world.map_id)
        G = event_gate.gate(key)
        self.npcs, self.keep = set(), set()
        self.guards = set()           # kalıcı patronu koruyanlar (dalganın doğan uzaylıları; çağrılanlar değil: Plutus'un Warhead'leri)
        self.rad, self.rad_next = None, 0.0     # süren radyoaktif alan (radio_tick) ve bir sonrakinin en erken zamanı
        self.sub, self.counted, self.left, self.exposed, self.boss = 0, None, None, False, ''
        now = time.time()
        if not G['hazir'] or G['can'] <= 0:
            self.phase, self.t = 'void', now
            world.add_gate(event_gate.exit_portal(key, self.map))
        elif self.cur_map() != self.map:
            self.phase, self.t = 'void', now
            for g in event_gate.next_portals(key, self.map, self.cur_map()):
                world.add_gate(g)
            world.add_gate(event_gate.exit_portal(key, self.map, side=True))
        else:
            wait = self.g.get('kural', {}).get('entry_sec')         # Plutus: Normal 1 sn, Kolay 15 sn (forum 143902)
            self.phase, self.t = 'intro', now + (KAPI.pace('giris_bekleme_sn') if wait is None else wait * SET.multiplier('dalga_bekleme'))
            world.send(self.say('devam' if G['dalga'] else 'giris') + self.k.plutus_cmds(key, now))
        world.log('   %s: dalga %d/%d, can %d (%s)' % (self.g['ad'], G['dalga'] + 1, self.wave_count(), G['can'], self.phase))

    def messages(self):
        return dict(KAPI.K['mesajlar'], **self.g.get('mesajlar', {}))

    def points(self, n):
        """Bu kapının uzaylısı öldü (dunya.kill): türün puan aralığından etkinlik puanı (Plutus)."""
        if n.d.get('kapi') != self.key or not n.d.get('puan'):
            return []
        if n.d.get('cpu_artis'):                                      # Aura Dun Jig: Bountiful Alien CPU şansı (EtkinlikKapilari.finish)
            with self.k.p.lock:
                G = self.k.gate(self.key)
                G['cpu_artis'] = G.get('cpu_artis', 0.0) + n.d['cpu_artis']
                self.k.p.dirty = True
        return self.k.add_points(self.key, random.randint(*n.d['puan']))

    # ------------------------------------------------------------ Space Uncertainty (kalkanı biten patronun radyoaktif alanı)
    def tick(self, now):
        super().tick(now)
        self.radio_tick(now)

    def radio_tick(self, now):
        """Kalıcı patronun (npc türünün 'radyoaktif'i; Plutus) kalkanı bitince radyoaktif alan: uyarıdan sonra sure_sn boyunca her
        saniye yeşil dairelerin dışındaki oyuncu hasar alır (azami canın azami_oran'ından fazla değil), içindeki iyileşir; alan
        bitince bekleme_sn sonra (kalkan hâlâ 0'sa) yenisi (darkorbitwiki "Space Uncertainty", fandom)."""
        w, r = self.w, self.rad
        boss = self.boss_npc() if self.phase == 'fight' else None
        spec = boss.d.get('radyoaktif') if boss else None
        if r and (not spec or w.hero_dead or w.jumping):
            self.radio_end(now)
        elif not r:
            if spec and boss.shield <= 0 and now >= self.rad_next and not w.hero_dead and not w.jumping:
                self.radio_start(boss, spec, now)
        else:
            if now >= r['next']:
                r['next'] += 1.0
                self.radio_pulse(boss, spec, now)
            if now >= r['bitis']:
                self.radio_end(now)

    def radio_start(self, boss, spec, now):
        w = self.w
        hx, hy = w.hero_pos(now)
        a0, circles = random.uniform(0, 2 * math.pi), []
        for i in range(spec['circle']):          # biri yakın (uyarı süresinde ulaşılır), ötekiler uzak
            a = a0 + i * 2 * math.pi / spec['circle']
            d = random.uniform(*spec['distance']) if i else spec['distance'][0]
            m = spec['yaricap']
            circles.append((min(max(m, hx + math.cos(a) * d), w.map_w - m), min(max(m, hy + math.sin(a) * d), w.map_h - m)))
        self.rad = dict(circles=circles, bitis=now + spec['warning_sec'] + spec['sure_sn'], next=now + spec['warning_sec'])
        w.send([KAPI.screen('Plutus: Space Uncertainty! Get into a green circle!', big=True)]
               + [poi('plutusSpaceUncertainty%d' % i, x, y, spec['yaricap']) for i, (x, y) in enumerate(circles)])
        w.log('   %s: radyoaktif alan (%d daire, %d sn)' % (self.g['ad'], len(circles), spec['sure_sn']))

    def radio_pulse(self, boss, spec, now):
        """Saniyelik nabız: dairenin içindeyse iyileşme, dışındaysa hasar."""
        w = self.w
        hx, hy = w.hero_pos(now)
        g = w.p.d['gemi']
        if any(math.hypot(hx - x, hy - y) <= spec['yaricap'] for x, y in self.rad['circles']):
            hp0 = g.get('hitPoints', 0)
            w.p.set_hull(hp=hp0 + spec['heal_sec'])
            w.send([w.hp_msg()] + w.heal_msgs(hp0))
        else:
            w.send(w.hurt_hero(min(spec['hasar_sn'], int(g.get('hitMax', 1) * spec['max_ratio'])), boss, atype=0, now=now,
                               source_asset=True))

    def radio_end(self, now):
        r, self.rad = self.rad, None
        spec = next((n.d.get('radyoaktif') for n in (self.w.npcs.get(i) for i in self.keep) if n and n.d.get('radyoaktif')), None)
        self.rad_next = now + (spec['bekleme_sn'] if spec else 0)
        if r:
            self.w.send([('MapRemovePOICommand', {'poiId': 'plutusSpaceUncertainty%d' % i}) for i in range(len(r['circles']))])

    def wave_count(self):
        return len(self.k.order(self.key))

    def say(self, event, **extra):
        """kapi.Kosu.say, dalga sayısı seçilen sırayla."""
        G = self.k.gate(self.key)
        n = min(G['dalga'], self.wave_count() - 1)
        vals = dict(kapi=self.g['ad'], dalga=n + 1, toplam=self.wave_count(), can=G['can'], anahtar=self.key,
                    gruplar=len(self.wave()['gruplar']), sure='')
        vals.update(extra)
        m = self.messages().get(event, {})
        return [KAPI.screen(m[kind].format(**vals), big=kind == 'buyuk', NAME=self.g['ad'], WAVE='%d/%d' % (vals['dalga'], vals['toplam']))
                for kind in ('buyuk', 'kisa') if kind in m]

    def cur_map(self):
        return self.wave()['harita']

    def wave(self):
        G = self.k.gate(self.key)
        order = self.k.order(self.key)
        return self.g['waves'][order[min(G['dalga'], len(order) - 1)]]

    def wave_msgs(self):
        return self.k.plutus_cmds(self.key)

    def sub_msgs(self):
        return []

    def spawn_one(self, i, group, x, y):
        """kapi.Kosu.spawn_one'ın etkinlik kapısı türleriyle (eg_*) olanı: kalıcı patron koruyucuları doğup ölmeden hasar almaz."""
        w, G = self.w, self.k.gate(self.key)
        a = self.wave()['uzaylilar'][i]
        # "oyuncu" görünümlü (Compromising Invasion 7. dalga Evil You) oyuncunun gemisiyle: türün modeli "oyuncu" istemcide çizilmiyor,
        # gemi görünmüyor ve seçilemiyordu, roketleri vuruyordu (oyuncu bildirimi 2026-10-30)
        model = self.k.p.ship_look() if a['tur'] == 'oyuncu' else None
        n = w.spawn_npc_at(npc_type(self.key, self.k.order(self.key)[G['dalga']], i), x, y, model=model, wave=True)
        n.gate, n.hunt = True, True
        self.npcs.add(n.id)
        group.add(n.id)
        if a.get('permanent'):
            self.keep.add(n.id)
            n.invulnerable = lambda: bool(self.queue) or any(j in self.w.npcs for j in self.guards)
            self.boss = a['gorunen_ad']
            w.send(self.say('koruma', ad=a['gorunen_ad']))
        else:
            self.guards.add(n.id)
        return n

    def wave_done(self, now):
        G = self.k.gate(self.key)
        label = self.wave()['ad']
        with self.k.p.lock:
            G['dalga'] += 1
            self.k.p.dirty = True
        self.npcs.clear()
        self.keep.clear()
        self.guards.clear()
        with self.k.p.lock:
            G['total_waves'] = G.get('total_waves', 0) + 1
            self.k.p.dirty = True
        for fn in self.k.wave_hooks:
            self.w.send(fn(self.key, G['total_waves']))
        if G['dalga'] >= self.wave_count() and self.g.get('kural', {}).get('infinite'):
            with self.k.p.lock:
                G['dalga'] = 0                      # sonsuz kapı (eski Invasion): son dalgadan sonra baştan
                self.k.p.dirty = True
        if G['dalga'] >= self.wave_count():
            self.complete()
            return
        nxt = self.cur_map()
        if nxt != self.map:
            for g in self.k.next_portals(self.key, self.map, nxt):
                self.w.add_gate(g)
            self.w.add_gate(self.k.exit_portal(self.key, self.map, side=True))
            self.w.send(self.say('sonraki_harita', dalga=G['dalga']) + self.k.plutus_cmds(self.key))
            self.phase = 'move'
            self.w.log('   %s: dalga %s bitti; sonraki harita %s' % (self.g['ad'], label, nxt))
            return
        self.counted = None
        self.w.add_gate(self.k.exit_portal(self.key, self.map))
        self.w.send(self.say('dalga_bitti', dalga=G['dalga'], sn=KAPI.pace('dalga_molasi_sn')) + self.k.plutus_cmds(self.key))
        self.phase, self.t = 'break', now + KAPI.pace('dalga_molasi_sn')
        self.w.log('   %s: dalga %s bitti' % (self.g['ad'], label))

    def complete(self):
        k, w = self.k, self.w
        msgs, info = k.finish(self.key, w.reward_msgs)
        w.add_gate(k.exit_portal(self.key, self.map))
        msgs += self.say('tamam', sure=fmt_time(info['sure'])) + k.plutus_cmds(self.key)
        w.send(msgs)
        self.phase = 'done'

    def on_death(self):
        """Can 1 azalır; kalmazsa kapı kapanır (bekleme süresi başlar)."""
        if self.phase in ('void', 'done'):
            return None
        k, G = self.k, self.k.gate(self.key)
        with k.p.lock:
            if not SET.get('sonsuz_can'):                    # panel: kapıda can harcanmaz
                G['can'] = max(0, G['can'] - 1)
            left = G['can']
            k.p.dirty = True
        if left <= 0:
            k.end(self.key)
        self.w.send([KAPI.screen('%s: you lost a life.' % self.g['ad']), KAPI.stm('lifes_left', '%!', left)] + k.plutus_cmds(self.key))
        self.w.log('   %s: can kaybedildi, kalan %d%s' % (self.g['ad'], left, ' (kapı kapandı)' if left <= 0 else ''))
        self.before_death = self.phase
        self.phase = 'void' if left <= 0 else 'dead'
        return left
