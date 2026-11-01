"""Galaxy Trek (Space Search; yol haritası Ö3; veri data/extra_events.json 'galaxy_trek').

İstemci (menü öğesi space_search, pencere 134, UISpaceSearchSystem; görevler ve ödüller UIActivityWindowSystem):
  - Pencere açılırken unityApi/events/spaceSearch.php XML'ini indirir: kök/planets/<planet planetId resKey/>, kök/planetEvents/<event
    eventId resKey degree><reward lootId amount/></event>; olay metni GetText(resKey) + " (" + GetText(degree) + ")"
    (SS_result_lowEvents_N / SS_result_event_low …). Ödül sekmesi unityApi/events/ssRewards.php: kök/rangeBoundPackageEntry
    [special, name]/package/{range from; item lootId amount; title name} (SpaceSearchRewardsDate: Time = from).
  - SpaceSearchRequest {id, action, count}: 0 pencere -> SpaceSearchInfoCommand {planetIndex, planetPct, quantity, lootId, cost};
    1 keşif (count 1/5/10) -> SpaceSearchEventsCommand {rewards [RewardModule], eventIds [EventCommand {eventId, planetId}], planets
    [PlanetCommand {planetId, planetPct, increase}]}; 2 ödül sekmesi -> SpaceSearchSectorRewardsCommand {rewards
    [SpaceSearchSectorRewards {unlock, count, range, received}]}; 3 ödülü al (count = from; id 0); 4 görevler -> SpaceSearchMissionListCommand
    {missions [EventQuestDefinitionModule {module, completed, claimed}]}. UpdateSpaceSearchKeyCommand {quantity} anahtar sayısı.
Kurallar (resmî SSS, darkorbitwiki): 40 gezegen (8 bölge); her keşif 1 FTL Key (resource_ftl-key); olay Simple %50 (+%3), Moderate %30
(+%5), Difficult %20 (+%9) ve türünün ödül paketi (sabit + alt paket çekilişi); gezegen %100 olunca sıradaki açılır; 13 ödül basamağı
tamamlanan gezegen sayısıyla (unvanlar 16 ve 36'da); günde 10 görev (1 sabit giriş, 9 rastgele) FTL Key verir; etkinlik bitince
anahtarlar silinir.
Profilde: galaxy_trek {donem, gezegen (1-40), yuzde, tamam, alinan [basamak], gun, gorevler [kimlik], deger {kimlik: koşul
değerleri}, biten [kimlik]}.
"""
import datetime, json, os, random, time
from xml.sax.saxutils import quoteattr

import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('galaxy_trek', {})
EVENT = 'galaxy_trek'
KEY = D.get('anahtar', 'resource_ftl-key')
PLANETS = D.get('planet', 40)
QUEST_BY_ID = {q['definition']['id']: q for q in D.get('quests', [])}


def active(now=None):
    return EVENT in CAL.active(now)


def all_events():
    """[(olay kimliği, tür kaydı)]."""
    return [(i, e) for e in D.get('events', []) for i in e['ids']]


# ------------------------------------------------------------ web (web.py)
def planets_xml():
    ev = []
    for i, e in all_events():
        rewards = ''.join('<reward lootId=%s amount="%d"/>' % (quoteattr(l), n) for l, n in e['fixed'])
        ev.append('<event eventId="%d" resKey=%s degree=%s>%s</event>' % (i, quoteattr(e['metin'] % i), quoteattr(e['grade']), rewards))
    planets = ''.join('<planet planetId="%d" resKey="SS_planet_name_%d"/>' % (i, i) for i in range(1, PLANETS + 1))
    return '<?xml version="1.0" encoding="UTF-8"?><spaceSearch><planets>%s</planets><planetEvents>%s</planetEvents></spaceSearch>' % (
        planets, ''.join(ev))


def rewards_xml():
    out = []
    for t in D.get('steps', []):
        rows = ''.join('<item lootId=%s amount="%d"/>' % (quoteattr(l), n) for l, n in t['esyalar'])
        title = '<title name=%s/>' % quoteattr(t['title']) if t.get('title') else ''
        out.append('<rangeBoundPackageEntry special="0" name="%d"><package><range from="%d"/>%s%s</package></rangeBoundPackageEntry>'
                   % (t['required'], t['required'], rows, title))    # satır anahtarı: gereken gezegen sayısı (metin ve al isteği)
    return '<?xml version="1.0" encoding="UTF-8"?><ssRewards>%s</ssRewards>' % ''.join(out)


def mod(name, **f):
    f['_'] = name
    return f


class GalaxyTrek:
    REQUESTS = ('SpaceSearchRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.titles = None                        # ödül unvanı (oturum bağlar: başarımın unvan listesine)
        self.on = None                            # etkinlik sürüyor mu (tick'te saniyede bir)
        if shop is not None:
            shop.on_bought.append(self.bought)

    def bought(self, loot, amount):
        """Mağazadan FTL Key paketi: açık pencerenin sayacı (UISpaceSearch.Quantity) yalnız UpdateSpaceSearchKeyCommand'la değişir;
        pencerenin Shop düğmesinden (GoShop) alınca eski sayı kalıyordu (oyuncu bildirimi 2026-10-28: 150'lik paket 50 gibi görünüyordu)."""
        if any(g == KEY for g, n in self.m.contents(loot, amount) or []):
            return [self.key_cmd()]
        return []

    @property
    def st(self):
        d = self.p.d.setdefault('galaxy_trek', {})
        for k, v in (('planet', 1), ('yuzde', 0), ('tamam', 0), ('claimed', []), ('value', {}), ('finished', []), ('quests', [])):
            d.setdefault(k, v)
        return d

    def keys(self):
        return self.p.resource(KEY)

    # ------------------------------------------------------------ dönem
    def roll_period(self, now=None):
        """Yeni koşu: ilerleme sıfırlanır (kaynakta düşük güven: her koşu baştan)."""
        p = CAL.period(EVENT, now)
        period = int(p[0]) if p else 0
        if self.p.d.get('galaxy_trek', {}).get('donem') != period:
            with self.p.lock:
                self.p.d['galaxy_trek'] = {'donem': period}
                self.p.dirty = True

    def roll_day(self, now=None):
        """Günün görevleri: 1 sabit (giriş) + rastgele 9."""
        day = datetime.date.fromtimestamp(time.time() if now is None else now).isoformat()
        st = self.st
        if st.get('gun') == day and st['quests']:
            return
        fixed = [q['definition']['id'] for q in D.get('quests', []) if q.get('fixed')]
        rest = [q['definition']['id'] for q in D.get('quests', []) if not q.get('fixed')]
        pick = fixed + random.sample(rest, max(0, min(len(rest), D.get('daily', 10) - len(fixed))))
        with self.p.lock:
            st.update(gun=day, quests=pick, value={}, finished=[])
            self.p.dirty = True

    # ------------------------------------------------------------ komutlar
    def info_cmd(self):
        st = self.st
        return ('SpaceSearchInfoCommand', dict(planetIndex=min(st['planet'], PLANETS), planetPct=int(st['yuzde']), quantity=self.keys(),
                                               lootId=KEY, cost=D.get('cost', 1)))

    def key_cmd(self):
        return ('UpdateSpaceSearchKeyCommand', {'quantity': self.keys()})

    def sector_cmd(self):
        st = self.st
        return ('SpaceSearchSectorRewardsCommand', {'rewards': [
            mod('SpaceSearchSectorRewards', unlock=st['tamam'] >= t['required'], count=min(st['tamam'], t['required']),
                range=t['required'], received=t['kimlik'] in st['claimed']) for t in D.get('steps', [])]})
        # istemci satırda "(count/range)" yazar: count biten gezegen, range hedef (canlı: basamak numarası hedef sanılıyordu)

    def missions_cmd(self):
        import quest_tracker as GT
        st = self.st
        out = []
        for qid in st['quests']:
            q = QUEST_BY_ID.get(qid)
            if q:
                done = qid in st['finished']
                out.append(mod('EventQuestDefinitionModule', module=GT.with_state(q['definition'], st['value'].get(str(qid), {}), done),
                               completed=done, claimed=done))
        return ('SpaceSearchMissionListCommand', {'missions': out})

    def login_msgs(self):
        if not active():
            return []
        self.roll_period()
        self.roll_day()
        msgs = self.event('login', {})               # görev listesi gönderilmez: istemci onu alınca pencereyi açıyor
        return msgs + [self.key_cmd()]

    def tick(self, now):
        """Koşu bitti: anahtarlar silinir (istemcinin metni); yeni günde görevler."""
        self.on = active(now)                     # olaylar sık gelir: etkinlik durumu saniyede bir
        if not self.on:
            st = self.p.d.get('galaxy_trek')
            if st and st.get('donem') is not None:
                n = self.keys()
                msgs = []
                if n:
                    self.p.add_resource(KEY, -n)
                    msgs = self.m.resource_msgs(KEY, 0, -n)
                    self.log('   Galaxy Trek bitti: %d FTL Key silindi' % n)
                with self.p.lock:
                    self.p.d['galaxy_trek'] = {}
                    self.p.dirty = True
                return msgs
            return []
        day = datetime.date.fromtimestamp(now).isoformat()
        if self.st.get('gun') != day:
            self.roll_period(now)
            self.roll_day(now)
        return []

    # ------------------------------------------------------------ istekler
    def handle(self, name, f):
        if not active():
            return []
        self.roll_period()
        self.roll_day()
        action = int(f.get('action') or 0)
        if action == 0:
            return [self.info_cmd(), self.key_cmd()]
        if action == 1:
            return self.explore(max(1, min(10, int(f.get('count') or 1))))
        if action == 2:
            return [self.sector_cmd()]
        if action == 3:
            return self.claim(int(f.get('count') or 0))      # istemci: {action 3, id 0, count = range from}
        if action == 4:
            return [self.missions_cmd()]
        return []

    def explore(self, count):
        st = self.st
        if st['tamam'] >= PLANETS:
            return [self.info_cmd()]
        count = min(count, self.keys() // max(1, D.get('cost', 1)))
        if count <= 0:
            self.log('   Galaxy Trek: FTL Key yok')
            return [self.info_cmd(), self.key_cmd()]
        self.p.add_resource(KEY, -count * D.get('cost', 1))
        events, planets, got = [], [], {}
        kinds = D.get('events', [])
        for _ in range(count):
            if st['tamam'] >= PLANETS:
                break
            e = random.choices(kinds, [k['chance'] for k in kinds])[0]
            eid = random.choice(e['ids'])
            planet = st['planet']
            events.append(mod('EventCommand', eventId=eid, planetId=planet))
            for l, n in e['fixed']:
                got[l] = got.get(l, 0) + n
            for rows in e['spin']:
                l, n, _ = random.choices(rows, [r[2] for r in rows])[0]
                got[l] = got.get(l, 0) + n
            with self.p.lock:
                st['yuzde'] = min(100, st['yuzde'] + e['progress'])
                inc = e['progress']
                if st['yuzde'] >= 100:
                    st['tamam'] += 1
                    if st['planet'] < PLANETS:
                        st['planet'] += 1
                    st['yuzde'] = 0
                self.p.dirty = True
            if planets and planets[-1]['planetId'] == planet:
                planets[-1]['increase'] += inc
                planets[-1]['planetPct'] = 100 if st['planet'] != planet or st['tamam'] >= PLANETS else st['yuzde']
            else:
                planets.append(mod('PlanetCommand', planetId=planet, increase=inc,
                                   planetPct=100 if st['planet'] != planet or st['tamam'] >= PLANETS else st['yuzde']))
        msgs = self.m.resource_msgs(KEY, self.keys(), -count)
        for l, n in sorted(got.items()):
            msgs += self.m.prize(l, n)
        self.log('   Galaxy Trek: %d keşif, gezegen %d (%%%d), tamam %d' % (count, st['planet'], st['yuzde'], st['tamam']))
        return [('SpaceSearchEventsCommand', dict(rewards=[mod('RewardModule', lootId=l, amount=n) for l, n in sorted(got.items())],
                                                  eventIds=events, planets=planets)),
                self.info_cmd(), self.key_cmd()] + msgs + self.m.money_msgs()

    def claim(self, tier):
        st = self.st
        t = next((t for t in D.get('steps', []) if t['required'] == tier), None)     # al isteğinin count'u = range from
        if not t or t['kimlik'] in st['claimed'] or st['tamam'] < t['required']:
            return [self.sector_cmd()]
        tier = t['kimlik']
        with self.p.lock:
            st['claimed'].append(tier)
            self.p.dirty = True
        msgs = []
        for l, n in t['esyalar']:
            msgs += self.m.prize(l, n)
        if t.get('title') and self.titles:
            msgs += self.titles(t['title'])
        self.log('   Galaxy Trek ödülü %d: %s %s' % (tier, t['esyalar'], t.get('title') or ''))
        return [self.sector_cmd()] + msgs + self.m.money_msgs()

    # ------------------------------------------------------------ görevler
    def event(self, kind, kw):
        """Oyun olayı (oturumun başarım/görev olayları): günün görevleri ilerler; biten görevin FTL Key'i hemen verilir."""
        if not (self.on if self.on is not None else active()):
            return []
        import quest_tracker as GT
        st = self.st
        msgs = []
        for qid in list(st['quests']):
            q = QUEST_BY_ID.get(qid)
            if not q or qid in st['finished']:
                continue
            vals = st['value'].setdefault(str(qid), {})
            _, done = GT.advance(self.p, q['definition']['rootCase'], vals, kind, kw, map_id=self.p.d['position'].get('mapId'), notify=False)
            if done:
                with self.p.lock:
                    st['finished'].append(qid)
                    self.p.dirty = True
                for r in q['definition']['rewards']:
                    msgs += self.m.prize(r['lootId'], r['amount'])
                self.log('   Galaxy Trek görevi bitti: %s' % q['ad'])
        if msgs:
            msgs.append(self.key_cmd())                 # liste (SpaceSearchMissionListCommand) pencereyi açar: yalnız istekle
        return msgs
