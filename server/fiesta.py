"""Fiesta Gate (Birthday 2025 penceresi; yol haritası Ö3; veri data/extra_events.json 'fiesta').

İstemci (menü öğesi birthday_2025, UI19thBirthdayGateSystem ve UI19thGateTipsSystem):
  - Puan penceresi: Birthday2025PointRewardRequest {openWindow} -> Birthday2025PointRewardCommand {openWindow, curRewardLevel (ulaşılan
    seviye), curPoints / curLevelPoints (sıradaki seviyenin ilerlemesi), lootShowCommandList [EventLootShowCommand {lootId,
    lootAmount, bg}] (50 seviyenin ödülü; öğe = sıra + 1), claimedIndexes [alınan seviyeler]}; Birthday2025ClaimRequest {rewardLevel;
    0 = alınabilenlerin hepsi}.
  - Giriş penceresi (X-1'deki portala atlayınca): Birthday2025GateWindowCommand {curLevel (açık en yüksek zorluk: 1, 2, 4, 8, 16),
    curLootAmount (kupon), commandList [Birthday2025GateRewardCommand {level, costAmount, costLootId, lootProbabilityModuleList
    [{lootId, minLootAmount, maxLootAmount, probabilityPercentage}], lootShowCommandList}]}; "Go Now" düğmesi level <= curLevel iken
    açık; Birthday2025GateEnterRequest {level}. Metinler bday2025_*, ttip_jumpgate_bday2025.
Kurallar (resmî SSS): X-1'den Galaxy Coupon'la; zorluklar sırayla açılır (Tranquil 1 kupon / 5 AP … Mythic 23 / 160); tek can;
başarısız olunca kupon gider, oyuncu X-1'e döner; kapı bitince AP; AP 50 seviyelik ödül çizgisini doldurur.
Kapılar etkinlik kapısı motorunda (event_gate.py): her zorluk bir kapı (fiesta_1..5, haritalar 494-498); burada kaydedilir.
Profilde: fiesta {ap, alinan [seviye], acik (açık en yüksek zorluk), donem}.
"""
import json, os, time

import event_gate as EKP
import event_calendar as CAL
from galaxy_gates import screen

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('fiesta', {})
EVENT = 'fiesta'
COUPON = D.get('kupon', 'resource_collectable_galaxy-coupon')
BY_LEVEL = {z['seviye']: z for z in D.get('zorluklar', [])}
BY_GATE = {z['kapi']: z for z in D.get('zorluklar', [])}
PORTAL_ID = EKP.PORTAL_BASE + 90                  # X-1'deki tek Fiesta portalı (pencereli)
TITLE_TRANQUIL = 'title_fiestagate_dec2025'      # "Epoch Lit" (istemci metni): Tranquil seviyesini tamamlayınca

# kapılar etkinlik kapısı motoruna (game.py EKP.register_npcs'den önce içe aktarılır: uzaylı türleri de kaydedilir)
for _k, _g in (D.get('kapilar') or {}).items():
    EKP.GATES[_k] = _g
    for _m in _g['haritalar']:
        EKP.BY_MAP[int(_m)] = _k


def active(now=None):
    return EVENT in CAL.active(now)


def mod(name, **f):
    f['_'] = name
    return f


class Fiesta:
    REQUESTS = ('Birthday2025PointRewardRequest', 'Birthday2025ClaimRequest', 'Birthday2025GateEnterRequest')

    def __init__(self, profile, shop, event_gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, event_gates, log
        self.change_map = None                    # oturum bağlar: (hedef, portal, konum)
        self.titles = None                        # oturum bağlar: unvan_avi.grant_title (Epoch Lit)
        event_gates.finish_hooks.append(self.on_finish)

    @property
    def st(self):
        d = self.p.d.setdefault('fiesta', {})
        for k, v in (('ap', 0), ('alinan', []), ('acik', 1)):
            d.setdefault(k, v)
        return d

    # ------------------------------------------------------------ ödül çizgisi
    def level(self):
        """(ulaşılan seviye, sıradaki seviyedeki puan, sıradaki seviyenin puanı)."""
        ap, lv = self.st['ap'], 0
        for row in D.get('cizgi', []):
            if ap < row['ap']:
                return lv, ap, row['ap']
            ap -= row['ap']
            lv += 1
        last = D['cizgi'][-1]['ap'] if D.get('cizgi') else 1
        return lv, last, last

    def point_cmd(self, open_window):
        lv, cur, need = self.level()
        shows = [mod('EventLootShowCommand', lootId=r['esyalar'][0][0] if r['esyalar'] else '', bg='',
                     lootAmount=r['esyalar'][0][1] if r['esyalar'] else 0) for r in D.get('cizgi', [])]
        return ('Birthday2025PointRewardCommand', dict(openWindow=bool(open_window), curRewardLevel=lv, curPoints=cur,
                                                       curLevelPoints=need, lootShowCommandList=shows,
                                                       claimedIndexes=sorted(self.st['alinan'])))

    def claim(self, level):
        lv = self.level()[0]
        todo = [l for l in range(1, lv + 1) if l not in self.st['alinan']] if level == 0 else \
            ([level] if 1 <= level <= lv and level not in self.st['alinan'] else [])
        msgs = []
        for l in todo:
            row = D['cizgi'][l - 1]
            with self.p.lock:
                self.st['alinan'].append(l)
                self.p.dirty = True
            for loot, n in row['esyalar']:
                msgs += self.m.prize(loot, n)
        if todo:
            self.log('   Fiesta Gate ödül çizgisi: %s' % todo)
        return [self.point_cmd(False)] + msgs + self.m.money_msgs()

    # ------------------------------------------------------------ giriş
    def gate_cmd(self):
        cmds = []
        for z in D.get('zorluklar', []):
            g = D['kapilar'][z['kapi']]
            o = g['odul']
            probs = [mod('LootProbabilityModule', lootId=l, minLootAmount=n, maxLootAmount=n, probabilityPercentage=round(c * 100, 3))
                     for l, n, c in o.get('sans', [])]
            shows = [mod('EventLootShowCommand', lootId=l, lootAmount=n, bg='') for l, n in o.get('esyalar', [])]
            if o.get('ep'):
                shows.insert(0, mod('EventLootShowCommand', lootId='currency_experience', lootAmount=o['ep'], bg=''))
            cmds.append(mod('Birthday2025GateRewardCommand', level=z['seviye'], costAmount=z['kupon'], costLootId=COUPON,
                            lootProbabilityModuleList=probs, lootShowCommandList=shows))
        return ('Birthday2025GateWindowCommand', dict(curLevel=self.st['acik'], curLootAmount=self.p.resource(COUPON), commandList=cmds))

    def portals(self, map_id, station):
        """X-1'deki pencereli Fiesta portalı (etkinlik sürerken)."""
        import map_links as H
        if not active() or H.map_class(map_id) != 'X-1' or not station:
            return []
        import galaxy_gates as KAPI
        sx, sy = station['posX'], station['posY']
        cx, cy = KAPI.MAP_W // 2, KAPI.MAP_H // 2         # istasyondan haritanın ortasına doğru, üretici kapılarından uzakta
        x, y = int(sx + (cx - sx) * 0.3), int(sy + (cy - sy) * 0.3 + 900)
        return [dict(gateId=PORTAL_ID, x=x, y=y, hedef=0, designId=D.get('portal_tasarim', 15), pencere='fiesta',
                     ipucu=D.get('ipucu', 'ttip_jumpgate_bday2025'))]

    def portal_window(self, g, w, go):
        """Portala atlandı (dünya kilidi altında): giriş penceresi."""
        w.send([self.gate_cmd()])

    def enter(self, level):
        z = BY_LEVEL.get(int(level))
        if not z or not active():
            return [self.gate_cmd()]
        if z['seviye'] > self.st['acik']:
            return [self.gate_cmd(), screen('Clear the previous difficulty first.')]
        if self.p.resource(COUPON) < z['kupon']:
            return [self.gate_cmd(), screen('key:bday2025_entry_info')]
        self.p.add_resource(COUPON, -z['kupon'])
        self.k.enter(z['kapi'])
        self.log('   Fiesta Gate %s: %d kupon' % (z['ad'], z['kupon']))
        msgs = self.m.resource_msgs(COUPON, self.p.resource(COUPON), -z['kupon'])
        if self.change_map:
            self.change_map(z['harita'], {'event_gate': True, 'kapi': z['kapi'], 'varis': EKP.center(z['harita'])}, None)
        return msgs

    def on_finish(self, key):
        """Kapı bitti (etkinlik_kapi.finish): AP ve sıradaki zorluk açılır."""
        z = BY_GATE.get(key)
        if not z:
            return []
        before = self.level()[0]
        with self.p.lock:
            self.st['ap'] += z['ap']
            nxt = z['seviye'] * 2
            if nxt in BY_LEVEL and self.st['acik'] < nxt:
                self.st['acik'] = nxt
            self.p.dirty = True
        lv = self.level()[0]
        self.log('   Fiesta Gate %s bitti: +%d AP (toplam %d, seviye %d)' % (z['ad'], z['ap'], self.st['ap'], lv))
        msgs = [screen('+%d Activity Points' % z['ap'], big=True)]
        if z['sira'] == 1 and self.titles:          # wiki: "Epoch Lit: Complete the Tranquil level"
            msgs += self.titles(TITLE_TRANQUIL)
        if lv > before:
            msgs.append(self.point_cmd(False))
        return msgs

    # ------------------------------------------------------------ istekler
    def handle(self, name, f):
        if name == 'Birthday2025PointRewardRequest':
            return [self.point_cmd(f.get('openWindow'))] if active() or f.get('openWindow') else []
        if name == 'Birthday2025ClaimRequest':
            return self.claim(int(f.get('rewardLevel') or 0))
        if name == 'Birthday2025GateEnterRequest':
            return self.enter(f.get('level'))
        return []
