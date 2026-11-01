"""Dispatch (yol haritası Aşama 5): toplayıcı gönderimi (Retriever) ve kapı gönderimi (Gate). Veri data/dispatch.json: toplayıcılar
istemcinin kodundan (tools/il2cpp/client_data.py), ödül listeleri, yuva fiyatları ve kurallar wiki'den; adetler uyarlama.

Akış (kayıtta liste isteği ve "kaynak yetmiyor" yanıtı var; ötekiler istemcinin komut ve enum'larından):
  girişte                          DispatchSlotInfoCommand {currentMaxSlotCount, availableSlotCount}
  DispatchGetRetrieverListRequest  {statusType}: 0 gönderilebilenler (toplayıcı tanımları), 1 sürenler (kalan saniye; 0 = toplanabilir)
                                   -> DispatchGetRetrieverListCommand + DispatchActiveEventCommand (1 Dispatch Day: pazartesi, cuma;
                                   2 Galaxy Gate Day: Pazar GG Double Rewards, kayıt 2026-10-25)
  DispatchSendRetrieverRequest     {dispatchId}: boş yuva ve ücret -> DispatchMessageCommand SUCCESS_SEND_RETRIEVER; para yoksa
                                   DispatchLootMessageCommand NO_RESOURCE {eksikler} (kayıttaki yanıt); yuva yoksa ERROR_NO_SLOT
  DispatchCollectRetrieverRequest  {slotId}: süresi bittiyse rastgele ödüller -> DispatchLootMessageCommand COLLECTED
  DispatchInstantCompleteRequest   {slotId}: Prime Coupon (toplayıcının anında bitirme ücreti) -> hemen toplanabilir
  DispatchBuySlotRequest           sonraki yuva (3. 50.000 U, 4.-5. 100.000 U) -> SUCCESS_ADD_SLOT
  DispatchGetRewardPackageRequest  {dispatchId}: olası ödüller (DispatchRewardModule lootId/adet/olasılık)
  DispatchGetGateListRequest       kapılar: kurulu ve dalga 1'deki kapı gönderilebilir (1 GGEU), süren, toplanabilir
  DispatchSendGateRequest / DispatchCollectGateRewardRequest: kapı gönderimi, bitince kapının tamamlama ödülleri
Profilde: dispatch {yuva, gonderilen: {yuva: {id, bitis}}, kapilar: {kapi: bitis}}.
"""
import json, os, random, time

import inventory as INV
import settings as SET
import galaxy_gates as KAPI

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'dispatch.json'), encoding='utf8'))
R = D['collectors']
AVAILABLE, IN_PROGRESS, READY = 0, 1, 2                    # StatusType (istemci)
NO_RESOURCE, COLLECTED = 0, 1                             # DispatchLootMessageCommand.MessageType
(SUCCESS_SEND_RETRIEVER, SUCCESS_SEND_GATE, SUCCESS_ADD_SLOT, ERROR_NO_GATE, ERROR_NO_SLOT, ERROR_NO_RESOURCE, ERROR_NOT_READY,
 ERROR_COLLECT, ERROR_SEND_RETRIEVER, ERROR_SEND_GATE, ERROR_INCOMPLETE_GATE, ERROR_MAX_SLOT) = range(12)   # DispatchMessageCommand
EVENT_NONE, DISPATCH_DAY, GALAXY_GATE_DAY = 0, 1, 2          # DispatchActiveEventCommand.activeEvent (istemci enum'u)


def mod(name, **f):
    f['_'] = name
    return f


def loot(l, n):
    return mod('LootModule', lootId=l, amount=int(n), modifier='')


def dispatch_day(now=None):
    import event_calendar as CAL                       # takvim.py: dispatch_gunu (pazartesi ve cuma)
    return CAL.is_active('dispatch_day', now)


def gate_day(now=None):
    import event_calendar as CAL                       # takvim.py: gg_cift_odul (Pazar GG Double Rewards)
    return CAL.is_active('gg_double_reward', now)


def event_ranges(code, now=None):
    """Süren etkinliklerin bu toplayıcıya (ya da 'kapi' gönderimine) eklediği kalemler: {lootId: [en az, en çok]} (etkinlik_oduller)."""
    import event_calendar as CAL
    return {l: rngs[code] for ev, items in D['event_rewards'].items() if CAL.is_active(ev, now)
            for l, rngs in items.items() if code in rngs}


def event_loot(code, now=None):
    return {l: random.randint(*lohi) for l, lohi in event_ranges(code, now).items()}


class Dispatch:
    def __init__(self, profile, gates=None, log=print):
        self.p, self.k, self.log = profile, gates, log
        self.m = None                    # mağaza (ödüller ve envanter güncellemesi; oturum bağlar)

    @property
    def st(self):
        d = self.p.d.setdefault('dispatch', {})
        d.setdefault('yuva', D['slots']['baslangic'])
        d.setdefault('sent', {})
        d.setdefault('kapilar', {})
        return d

    def free_slot(self):
        return next((s for s in range(1, self.st['yuva'] + 1) if str(s) not in self.st['sent']), None)

    def slot_info(self):
        busy = len(self.st['sent'])
        return ('DispatchSlotInfoCommand', dict(currentMaxSlotCount=self.st['yuva'], availableSlotCount=self.st['yuva'] - busy))

    def slot_costs(self):
        return ('DispatchSlotCostCommand', {'slotCosts': [mod('DispatchSlotModule', slotId=int(s), costList=[loot(l, n) for l, n in c.items()])
                                                          for s, c in sorted(D['slots']['prices'].items())]})

    def event(self, now=None):
        return ('DispatchActiveEventCommand', {'activeEvent': DISPATCH_DAY if dispatch_day(now) else GALAXY_GATE_DAY if gate_day(now) else EVENT_NONE})

    def login_msgs(self):
        return [self.slot_info()]

    # ------------------------------------------------------------ toplayıcılar
    def retriever_list(self, status, now=None):
        now = now or time.time()
        if status == AVAILABLE:
            lst = [mod('DispatchModule', duration=SET.duration(r['sure_sn'], 'dispatch'), id=int(i), slotId=0) for i, r in sorted(R.items(), key=lambda x: int(x[0]))]
        else:
            lst = [mod('DispatchModule', duration=max(0, int(g['bitis'] - now)), id=g['id'], slotId=int(s))
                   for s, g in sorted(self.st['sent'].items())]
        return [('DispatchGetRetrieverListCommand', dict(statusType=status, retrieverList=lst)), self.event(now)]

    def send(self, f):
        rid = str(f.get('dispatchId'))
        r = R.get(rid)
        if not r:
            return [('DispatchMessageCommand', {'messageType': ERROR_SEND_RETRIEVER})]
        slot = self.free_slot()
        if not slot:
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_SLOT})]
        miss = INV.missing(self.p, r['fee'])
        if miss:
            self.log('   Dispatch: %s için yetmiyor %s' % (r['code'], miss))
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        removed = INV.spend(self.p, r['fee'], reason='buy_SPECIAL', detail=r['code'])
        with self.p.lock:
            self.st['sent'][str(slot)] = dict(id=int(rid), bitis=time.time() + SET.duration(r['sure_sn'], 'dispatch'))
            self.p.dirty = True
        self.p.ach('dispatch_send', code=r['code'])
        self.log('   Dispatch: %s gönderildi (yuva %d, %d sn)' % (r['code'], slot, r['sure_sn']))
        # liste gönderilmez: istemci her DispatchGetRetrieverListCommand'da (durumu ne olursa olsun) süren gönderimleri kendi
        # önbelleğinden açık sekmeye çiziyor (DispatchGetRetrieverListUpdateEvent -> CreateUIDispatchProgressItem; yalnız
        # statusType 1 önbelleği yeniler). Süren listesi Available'a çiziliyordu (H34), Available listesi de eski önbelleği: son
        # gönderim görünmüyor, sekme seçili değildi (kullanıcı 2026-10-18). IN PROGRESS sekmesi açılınca istemci listeyi ister.
        return (INV.update_msgs(self.m, self.p, list(r['fee']), removed)
                + [('DispatchMessageCommand', {'messageType': SUCCESS_SEND_RETRIEVER}), self.slot_info()])

    @staticmethod
    def fixed(r):
        """Serinin her dönüşteki kalemleri: kademe tablosu (sabit_kademe; forum 160334) ya da eski sabit x doğrusal kademe."""
        tab = D.get('fixed_tier', {}).get(r['series'])
        if tab:
            return {l: v[r['kademe'] - 1] for l, v in tab.items() if v[r['kademe'] - 1]}
        f_ = 1 + D['tier_increase'] * (r['kademe'] - 1)
        return {l: max(1, int(round(n * f_))) for l, n in D['fixed'][r['series']].items()}

    @staticmethod
    def amount(x, r):
        """Rastgele kalemin kademedeki adedi: kalem x kademe tablosu (kademe_adet), yoksa tekil 1 ya da taban x doğrusal kademe."""
        tab = D.get('tier_count', {}).get(x)
        if tab and r['kademe'] > 1:                  # 1. kademe gerçek kayıttaki taban adetler (R-01: Mucosum 8, yakıt 1.000)
            return tab[r['kademe'] - 1]
        return 1 if x in D['single'] else max(1, int(round(D['base_count'][x] * (1 + D['tier_increase'] * (r['kademe'] - 1)))))

    def rewards(self, rid, now=None):
        """Bir dönüşün ödülleri (kayıt: sabit kalemler + 4 farklı rastgele kalem): serinin sabit kalemleri (Solidus, EXP), listeden
        odul_sayisi farklı eşya (seyrekler düşük ağırlıkla); adet kademeyle artar, Dispatch Day x1,5; süren etkinliğin kalemi eklenir."""
        r = R[str(rid)]
        f = D['dispatch_day_multiplier'] if dispatch_day(now) else 1
        out = {l: max(1, int(round(n * f))) for l, n in Dispatch.fixed(r).items()}
        pool = [x for x in D['rewards'][r['code']] if x not in out]
        extra = sum(1 for l in out if l not in ('currency_experience', 'resource_collectable_solidus'))   # A-01/02 LCB-10, PLT-2026 …
        for _ in range(min(D['reward_count'] - extra, len(pool))):
            weights = [D['sparse'].get(x, 1.0) for x in pool]
            pick = random.choices(pool, weights)[0]
            pool.remove(pick)
            out[pick] = max(1, int(round(Dispatch.amount(pick, r) * f)))
        out.update(event_loot(r['code'], now))
        return out

    def grant(self, items):
        msgs = []
        for l, n in items.items():
            if self.m:
                msgs += self.m.prize(l, n)               # panelin ödül çarpanları
            else:
                self.p.add_resource(l, n)
        return msgs

    def collect(self, f, now=None):
        slot = str(f.get('slotId'))
        g = self.st['sent'].get(slot)
        now = now or time.time()
        if not g:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        if now < g['bitis']:
            return [('DispatchMessageCommand', {'messageType': ERROR_NOT_READY})]
        items = self.rewards(g['id'], now)
        with self.p.lock:
            del self.st['sent'][slot]
            self.p.dirty = True
        self.p.ach('dispatch_collect', code=R[str(g['id'])]['code'])
        self.p.ach('dispatch', olay='DISPATCH_RETRIEVER')            # başarım: "N Retriever Dispatch"
        self.log('   Dispatch: %s toplandı %s' % (R[str(g['id'])]['code'], items))
        return (self.grant(items) + [('DispatchLootMessageCommand', dict(messageType=COLLECTED, loots=[loot(l, n) for l, n in items.items()])),
                                     self.slot_info()] + self.retriever_list(IN_PROGRESS)[:1])

    def instant(self, f):
        slot = str(f.get('slotId'))
        g = self.st['sent'].get(slot)
        if not g:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        cost = R[str(g['id'])]['instant']
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost)
        with self.p.lock:
            g['bitis'] = time.time()
            self.p.dirty = True
        return INV.update_msgs(self.m, self.p, list(cost)) + self.retriever_list(IN_PROGRESS)[:1]

    def buy_slot(self, f=None):
        nxt = self.st['yuva'] + 1
        if nxt > D['slots']['azami']:
            return [('DispatchMessageCommand', {'messageType': ERROR_MAX_SLOT})]
        cost = D['slots']['prices'].get(str(nxt), {})
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost, reason='buy_SPECIAL', detail='dispatch_slot')
        with self.p.lock:
            self.st['yuva'] = nxt
            self.p.dirty = True
        self.log('   Dispatch: %d. yuva açıldı' % nxt)
        return INV.update_msgs(self.m, self.p, list(cost)) + [('DispatchMessageCommand', {'messageType': SUCCESS_ADD_SLOT}), self.slot_info()]

    def reward_package(self, f):
        r = R.get(str(f.get('dispatchId')))
        if not r:
            return []
        fixed = Dispatch.fixed(r)
        pool = [x for x in D['rewards'][r['code']] if x not in fixed]
        total = sum(D['sparse'].get(x, 1.0) for x in pool)
        lst = [mod('DispatchRewardModule', lootId=l, amount=n, chance=100) for l, n in fixed.items()]
        lst += [mod('DispatchRewardModule', lootId=x, amount=Dispatch.amount(x, r),
                    chance=max(1, int(round(100 * D['reward_count'] * D['sparse'].get(x, 1.0) / total)))) for x in pool]
        lst += [mod('DispatchRewardModule', lootId=l, amount=lohi[0], chance=100) for l, lohi in event_ranges(r['code']).items()]
        return [('DispatchGetRewardPackageCommand', dict(name=r['ad'], rewards=lst))]

    # ------------------------------------------------------------ kapılar
    def gate_keys(self):
        return [k for k in KAPI.KAPI if k != 'hades']        # grup kapısı gönderilmez (wiki)

    def gate_list(self, now=None):
        now = now or time.time()
        out = []
        for key in self.gate_keys():
            g = KAPI.KAPI[key]
            if key in self.st['kapilar']:
                left = self.st['kapilar'][key] - now
                out.append(mod('DispatchGateModule', gateId=g['kimlik'], status=IN_PROGRESS if left > 0 else READY, timeLeft=max(0, int(left))))
            else:
                # Her kapı listede; kurulmamış ya da hiç tamamlanmamış kapıyı gönderim reddeder (istemcinin metinleri
                # dispatch_error-no-gate "Please prepare a Gate manually …", dispatch_error-incomplete-gate "… complete the Gate manually
                # at least once …"). Yalnız uygun kapıları listelemek sekmeyi boş bırakıyordu (oyuncu bildirimi 2026-10-28, img3)
                out.append(mod('DispatchGateModule', gateId=g['kimlik'], status=AVAILABLE,
                               timeLeft=SET.duration(D['kapi']['sure_sn'], 'dispatch')))      # gönderilebilirken "Time required" sütunu (canlı test H35)
        return [('DispatchGetGateListCommand', {'gateList': out})]

    def send_gate(self, f):
        key = KAPI.BY_ID.get(f.get('gateId'))
        if not key or key not in self.gate_keys() or key in self.st['kapilar']:
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_GATE})]
        if not self.k.built(key) or self.k.gate(key)['dalga'] != 0:          # kurulu ve 1. dalgada (forum 160334)
            return [('DispatchMessageCommand', {'messageType': ERROR_NO_GATE})]
        if not self.k.gate(key).get('tamam', 0):                                 # en az bir kez elle tamamlanmış
            return [('DispatchMessageCommand', {'messageType': ERROR_INCOMPLETE_GATE})]
        cost = {D['kapi']['ggeu']: 1}
        miss = INV.missing(self.p, cost)
        if miss:
            return [('DispatchLootMessageCommand', dict(messageType=NO_RESOURCE, loots=[loot(l, n) for l, n in miss.items()]))]
        INV.spend(self.p, cost)
        with self.p.lock:
            self.st['kapilar'][key] = time.time() + SET.duration(D['kapi']['sure_sn'], 'dispatch')
            self.k.gate(key)['hazir'] = False
            self.p.dirty = True
        self.log('   Dispatch: %s kapısı gönderildi' % KAPI.KAPI[key]['ad'])
        return INV.update_msgs(self.m, self.p, list(cost)) + [('DispatchMessageCommand', {'messageType': SUCCESS_SEND_GATE})] + self.gate_list()

    def collect_gate(self, f, now=None):
        key = KAPI.BY_ID.get(f.get('gateId'))
        now = now or time.time()
        if not key or key not in self.st['kapilar']:
            return [('DispatchMessageCommand', {'messageType': ERROR_COLLECT})]
        if now < self.st['kapilar'][key]:
            return [('DispatchMessageCommand', {'messageType': ERROR_NOT_READY})]
        with self.p.lock:
            del self.st['kapilar'][key]
            self.p.dirty = True
        self.p.ach('dispatch', olay='DISPATCH_GATE')                 # başarım: "N Gate Dispatch"
        msgs = self.k.dispatch_complete(key, D['dispatch_day_multiplier'] if dispatch_day(now) else 1)     # Sevkiyat Günü kapıda da
        extra = event_loot('kapi', now)                              # Chaos Omen / Protegit: kapı gönderiminden Chaos Fragment
        if extra:
            msgs[-1][1]['loots'] += [loot(l, n) for l, n in extra.items()]       # son ileti DispatchLootMessageCommand
            msgs = self.grant(extra) + msgs
        return msgs + self.gate_list()

    def handle(self, name, f):
        fn = {'DispatchGetRetrieverListRequest': lambda f: self.retriever_list(f.get('statusType', 0)),
              'DispatchSendRetrieverRequest': self.send, 'DispatchCollectRetrieverRequest': self.collect,
              'DispatchInstantCompleteRequest': self.instant, 'DispatchBuySlotRequest': self.buy_slot,
              'DispatchGetRewardPackageRequest': self.reward_package, 'DispatchGetGateListRequest': lambda f: self.gate_list(),
              'DispatchSendGateRequest': self.send_gate, 'DispatchCollectGateRewardRequest': self.collect_gate}.get(name)
        return fn(f) if fn else None
