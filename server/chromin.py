"""Chromin Rush (yol haritası Ö3; veri data/extra_events.json 'chromin' <- tools/extra_events.py).

İstemci: menü öğesi chrominEvent (pencere 67, UIChrominRushSystem) ChrominUpdateCommand {currentAmt, maxAmt} gösterir; "GET NOW"
düğmesi web ödeme sayfası (tek oyunculuda mağazanın Chromin paketleri uridyumla). Metinler (chromin_ttip): Chromin Galaksi Kapısı
uzaylılarından düşer, en çok 160.000 tutulur; etkinlik sürerken sınırı aşan kısım krediye çevrilir (history_chromin_compensation),
etkinlik bitince kalan Chromin onura (history_msg_event_chromin_honor_converted). Chromin'le Assembly'nin 49 etkinlik tarifi
(ON_SCHEDULE; takvimin 'para'sı, assembly.event_recipes) yapılır.

Kaynaklar: Delta, Epsilon, Zeta, Kappa ve Kronos kapılarının (galaxy_gates.py) uzaylıları ölünce bir olasılıkla Chromin kutusu düşer
(CHROMIN_BOX_1..3, miktara göre küçük/orta/büyük; istemcinin kutu adları "Chromin"). Miktar kapı başına toplamın (wiki ~2.700)
uzaylının gücüne (can + kalkan) oranı; kapının bütün uzaylıları öldürülünce beklenen toplam o kadar. Bütün Chromin girişleri (kutu,
paket, görev, GM) mağazanın ödül yolundan geçer: sınır orada uygulanır (gain).
Profilde: chromin {donem: etkinliğin başladığı zaman damgası, tavan_uyarisi: bool}.
"""
import json, os, random, time

import settings as SET
import galaxy_gates as KAPI
import ranks as RT
import event_calendar as CAL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('chromin', {})
LOOT = 'resource_collectable_chromin'
EVENT = 'chromin'
CAP = D.get('azami', 160000)
CREDITS_PER = D.get('kredi_orani', 1)          # sınırı aşan Chromin başına kredi
HONOR_PER = D.get('onur_orani', 0.05)          # etkinlik sonunda kalan Chromin başına onur


def active(now=None):
    return EVENT in CAL.active(now)


def box_for(npc, gate):
    """Kapı uzaylısının Chromin kutusu -> (kutu türü, miktar) ya da None (kapı Chromin kapısı değil)."""
    total = (D.get('kapilar') or {}).get(gate)
    if not total:
        return None
    strength = npc.d.get('hp', 0) + npc.d.get('kalkan', 0)
    n = max(1, int(round(D.get('kapi_basina', 2700) * strength / float(total) / max(0.01, D.get('olasilik', 1.0)))))
    kind = 'CHROMIN_BOX_1'
    for k, at in D.get('kutu_esikleri', []):
        if n >= at:
            kind = k
    return kind, n


class Chromin:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        return self.p.d.setdefault('chromin', {})

    def amount(self):
        return self.p.resource(LOOT)

    def update_cmd(self):
        return ('ChrominUpdateCommand', {'currentAmt': int(self.amount()), 'maxAmt': CAP})

    def login_msgs(self):
        return [self.update_cmd()] if active() or self.amount() else []

    def gain(self, n):
        """Chromin girişi (mağazanın ödül yolu): sınıra kadar depoya, fazlası etkinlik sürerken krediye (istemcinin metni)."""
        have = self.amount()
        room = max(0, CAP - have)
        got, extra = min(n, room), max(0, n - room)
        msgs = []
        if got:
            total = self.p.add_resource(LOOT, got)
            msgs += self.m.resource_msgs(LOOT, total, got)
        if active() and self.st.get('donem') is None:
            with self.p.lock:
                self.st['donem'] = CAL.period(EVENT)[0] if CAL.period(EVENT) else time.time()
                self.p.dirty = True
        if extra:
            cr = int(extra * CREDITS_PER)
            tot = self.p.gain(kredi=cr, neden='chromin_compensation')
            msgs += self.m.money_msgs() + [legacy('0|LM|ST|CRE|%d|%d' % (cr, tot['kredi']))]
            RT.note(self.p, 'history_chromin_compensation', count=cr)    # istemci %AMOUNT%'a count'u koyuyor (canlı tur 2)
            self.log('   Chromin sınırı: %d fazlası %d krediye' % (extra, cr))
        if have + got >= CAP and not self.st.get('cap_warning'):
            with self.p.lock:
                self.st['cap_warning'] = True
                self.p.dirty = True
            msgs.append(legacy('0|A|STM|msg_event_chromin_max_quantity_reached'))
        return msgs + [self.update_cmd()]

    def on_kill(self, w, npc, x, y):
        """Galaksi Kapısı uzaylısı öldü (dünya kilidi altında): etkinlik sürerken Chromin kutusu."""
        if not active() or int(w.map_id) not in KAPI.BY_MAP or npc.d.get('uncounted'):
            return []
        b = box_for(npc, KAPI.BY_MAP[int(w.map_id)])
        if not b or random.random() >= SET.chance('dusme', D.get('olasilik', 1.0), 'etkinlik'):
            return []
        kind, n = b
        h = w.drop_box(kind, x, y, None, D.get('omur_sn', 300))
        w.boxes[h]['etk'] = {'tur': kind, 'mod': 'hepsi', 'kesin': [[LOOT, n]]}
        return []

    def tick(self, now):
        """Etkinlik bitti: kalan Chromin onura (bir kez); sınır uyarısı yeni etkinlikte yeniden."""
        if active(now) or self.st.get('donem') is None:
            return []
        n = self.amount()
        msgs = []
        if n:
            hon = int(n * HONOR_PER)
            self.p.add_resource(LOOT, -n)
            tot = self.p.gain(onur=hon, neden='chromin_honor')
            msgs += self.m.resource_msgs(LOOT, 0, -n) + [legacy('0|LM|ST|HON|%d|%d' % (hon, tot['onur']))]
            RT.note(self.p, 'history_msg_event_chromin_honor_converted', count=hon)
            self.log('   Chromin Rush bitti: %d Chromin -> %d onur' % (n, hon))
        with self.p.lock:
            self.st.clear()
            self.p.dirty = True
        return msgs + [self.update_cmd()]
