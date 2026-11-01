"""Etkinlik sonunda kalan paralar onura (yol haritası E3; Chromin chromin.py'de, Infiltrator Fragment world_boss.py'de).

İstemcinin geçmiş metinleri (history_msg_event_*_honor_converted): Battle Pass Key, Candy Corn ve Golden Candy Corn (halloweenoct2020),
Luminium, Styxus ve Charopos Shard (valentine). Oranlar: Candy Corn 1, Golden Candy Corn 20.000 (darkorbitwiki Trial of Terrors),
Luminium 1 ve en çok 10.000 onur (wiki Empyrian March), Battle Pass Key 5.000 (Immortal Union SSS); Valentine parçalarının oranı
bilinmiyor (uyarlama 1). Resmî sunucu 24-48 saat sonra çevirir; burada etkinlik bitince (oturumun ilk adımında).
Byte Remnant (Mimesis Mutiny) onura çevrilmez: etkinlik bittikten 24 saat sonra envanterden silinir (wiki; LATER).
Profilde: etkinlik_sonu {etkinlik: dönemin başladığı zaman damgası} (etkinlik sürerken görülenler); etkinlik_silme {etkinlik: dönemin
bitişi} (LATER'dekiler).
"""
import event_gate as EKP
import ranks as RT
import event_calendar as CAL
from legacy_protocol import legacy

# etkinlik -> [(geçmiş metni, {lootId: onur oranı}, onur sınırı)]
CONVERT = {
    'halloween': [('history_msg_event_halloweenoct2020_honor_converted',
                   {'resource_collectable_candy-corn': 1, 'resource_collectable_golden-candy-corn': 20000}, None)],
    'empyrian': [('history_msg_event_luminium_honor_converted', {'resource_collectable_luminium': 1}, 10000)],
    'immortal_union': [('history_msg_event_valentine_honor_converted',
                        {'resource_collectable_styxus-shard': 1, 'resource_collectable_charopos-shard': 1}, None)],
}
# etkinlik -> bitince envanterden silinen CPU'lar (wiki: "Use your Bountiful Alien CPUs before the event ends as they will be removed")
REMOVE = {}
for _loot, _c in EKP.D.get('cpu', {}).items():
    REMOVE.setdefault(_c['etkinlik'], []).append(_loot)
    CONVERT.setdefault(_c['etkinlik'], [])
# etkinlik -> (bitişten kaç saniye sonra, silinen kaynaklar): darkorbitwiki mimesis-mutiny "Byte Remnant ... removed 24 hours after the event ends"
LATER = {'mimesis_mutiny': (24 * 3600, ['resource_collectable_byte-remnant'])}
# etkinlik -> (unvan, sıra puanı): bitince ilk 10'a giren (puanı > 0) unvanı alır. Frozen Labyrinth Synk avı: Elite Marksman
# (resmî Türk forumu kış SSS 1452398, Donmuş Labirent 2019 1300061)
TITLES = {'labirent': ('title_frozenLabyrinth-marksman', lambda x: int((x.d.get('labirent') or {}).get('hunts', 0)))}
for _k in TITLES:
    CONVERT.setdefault(_k, [])
BPK = ('history_msg_event_battle_pass_key_honor_converted', {'resource_battle-pass-key': 5000}, None)
for _k, _e in CAL.EVENTS.items():                  # Battle Pass'li her etkinlikte kalan anahtarlar (savas_bileti.py; E8)
    if 'BattlePass' in _e.get('kinds', []):
        CONVERT.setdefault(_k, []).append(BPK)


class EventEnd:
    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        return self.p.d.setdefault('event_end', {})

    @property
    def late(self):
        return self.p.d.setdefault('event_cleanup', {})

    def delayed(self, now):
        """LATER: etkinlik sürerken bitiş zamanı yazılır; süre dolunca kaynaklar silinir (onura çevrilmez)."""
        msgs = []
        for ev, (wait, loots) in LATER.items():
            if CAL.is_active(ev, now):
                end = (CAL.period(ev, now) or (now, now))[1]
                if self.late.get(ev) != end:
                    with self.p.lock:
                        self.late[ev] = end
                        self.p.dirty = True
            elif ev in self.late and now >= self.late[ev] + wait:
                for loot in loots:
                    n = self.p.resource(loot)
                    if n > 0:
                        self.p.add_resource(loot, -n)
                        msgs += self.m.resource_msgs(loot, 0, -n)
                        self.log('   %s bitti: %s x%d %d saat sonra silindi' % (CAL.EVENTS[ev]['ad'], loot, n, wait // 3600))
                with self.p.lock:
                    del self.late[ev]
                    self.p.dirty = True
        return msgs

    def tick(self, now):
        msgs = self.delayed(now)
        for ev, rows in CONVERT.items():
            if CAL.is_active(ev, now):
                if ev not in self.st:
                    with self.p.lock:
                        self.st[ev] = (CAL.period(ev, now) or (now,))[0]
                        self.p.dirty = True
                continue
            if ev not in self.st:
                continue
            for text, rates, cap in rows:
                held = {loot: self.p.resource(loot) for loot in rates}
                hon = sum(n * rates[loot] for loot, n in held.items() if n > 0)
                if not hon:
                    continue
                hon = min(hon, cap) if cap else hon
                for loot, n in held.items():
                    if n > 0:
                        self.p.add_resource(loot, -n)
                        msgs += self.m.resource_msgs(loot, 0, -n)
                tot = self.p.gain(onur=hon, neden='event_honor')
                msgs.append(legacy('0|LM|ST|HON|%d|%d' % (hon, tot['onur'])))
                RT.note(self.p, text, count=hon)        # istemci %AMOUNT%'a count'u koyuyor, args'a bakmıyor (canlı tur 2)
                self.log('   %s bitti: %s -> %d onur' % (CAL.EVENTS[ev]['ad'], {k: n for k, n in held.items() if n > 0}, hon))
            for loot in REMOVE.get(ev, ()):
                n = self.p.ammo(loot)
                if n > 0:
                    with self.p.lock:
                        self.p.d['cephane'].pop(loot, None)
                        self.p.dirty = True
                    msgs += self.m.resource_msgs(loot, 0, -n)
                    self.log('   %s bitti: %s x%d silindi' % (CAL.EVENTS[ev]['ad'], loot, n))
            if ev in TITLES:
                title, score = TITLES[ev]
                import community as TP
                top, me = TP.ranking(self.p, score)
                if score(self.p) > 0 and (me[0] or 1) <= 10:
                    RT.grant_title(self.p, title)
                    self.log('   %s bitti: unvan %s' % (CAL.EVENTS[ev]['ad'], title))
            with self.p.lock:
                del self.st[ev]
                self.p.dirty = True
        return msgs
