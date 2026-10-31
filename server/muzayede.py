"""Yerel müzayede (yol haritası Aşama 10; istemcinin Auction* mesajları ve UIAuction penceresi).

Lotlar kayıttaki listeden (data/sosyal.json, tools/sosyal.py): saatlik, günlük ve haftalık; teklif kredisiyle, anında alım
uridyumla. Dönem bitişi: saatlik her saatin 30. dakikası, günlük 22:30 UTC, haftalık pazar 22:30 UTC (kayıttaki kalan süreler).
  AuctionListRequest          -> AuctionListCommand {hour/day/weekSubSec, auctionList, myBidList, historyList}
  AuctionBidRequest {lootId, type, price}  -> AuctionBidCommand {success, myBid, curBid, stack} + liste + para
      en az 10.000 kredi, en yüksek tekliften büyük ve önceki teklifinden en az 10.000 fazla ("auction_bid_minBid_not_reached");
      kredi teklifte düşer (önceki teklifin farkı), kredi yetmezse "auction_bid_credits_to_little" (kayıt: enumBaseKey 93)
  AuctionQuickBuyRequest {lootId, type}    -> uridyumla hemen (anında alımı olmayan lot: "auction_buy_instant_invalid")
  Get/UpdateNamFIagRequest                 -> onay postaları açık mı (istemci: "Enable confirmation messages")
Dönem bitince en yüksek teklif oyuncununsa eşya verilir (mağazanın ödül yolu), geçmişe yazılır, onay postası açıksa posta
(müzayede mesajı, msgType 2 "Item purchased").
Sanal rakipler isteğe bağlı (panelin Müzayede ayarı, ayar.py muzayede_rakip; varsayılan kapalı: teklifleri yalnız oyuncu verir).
Seviyeler data/sosyal.json rakipler'de. Her lotun her döneminde olasılıkla bir rakip: bütçesi, dönem içindeki teklif adımları ve
adı lot, dönem ve seviye tohumlu (yeniden hesaplanır, saklanmaz).
  Çekingen, Ilımlı ('gecer' yok): birkaç küçük teklif verir; oyuncu teklif verince donar, oyuncuyu hiç geçmez -> lot oyuncunun.
  Rekabetçi, Agresif: oyuncu geçince bir tepki süresi sonra karşılık verir (oyuncunun teklifi + artış, bütçeye kadar; dönemin
  son 5 saniyesine kalmadan). Bütçeyi aşan teklif kazanır. Teklifi geçilen oyuncunun kredisi hemen geri gelir, teklif kaydı düşer
  (yeniden tam tutarla teklif verir; resmî forum 127234) ve onay postası açıksa "geçildin" postası.
Bot oyuncular gelince (Aşama 11) teklifleri rival() döndürecek.
Panelin Açık Artırma sayfası (panel_kanali.py; kullanıcı isteği 2026-10-28): kurallar profilde, panel kapalıyken de oturumun tick'inde
işler (Sosyal.tick -> settle + oto):
  otomatik {"tür|lot": {azami, bildirilen}}  geçilince (ya da hiç teklif yoksa) en düşük geçerli teklifi verir (en yüksek + artış,
      en az en_az_teklif), azamiyi aşacaksa bir kez "oto_sinir" olayı; dönem bitince kural kalır (her dönem yeniden).
  alarmlar {"tür|lot": {gecilince, dk, son}}  teklif geçilince, dönemin bitmesine dk dakika kala: oyunda ekran mesajı.
  olaylar [{no, zaman, tip, tur, loot, ...}]  gecildi, bitiyor, kazanildi, kaybedildi, oto_teklif, oto_sinir (son OLAY_SINIRI; panel
      yeni olayları bildirim olarak gösterir).
Çok oyunculu sunucuda lotlar herkes için aynı: öteki oyuncuların teklifleri de yarışır (en yüksek teklif; eşitse önce veren), dönemin
kazananı ilk hesaplayan oturumda bir kez belirlenir (SONUC): önce her oyuncu kendi teklifiyle aynı lotu kazanabiliyordu.
"""
import json, os, random, threading, time
import veri as VERI

import ayar as AY

HERE = os.path.dirname(os.path.abspath(__file__))
D = VERI.yukle('sosyal.json')['muzayede']
LOTS = {(l[2], l[0]): {'loot': l[0], 'grup': l[1], 'tur': l[2], 'adet': l[3], 'anlik': l[4], 'fiyat': l[5]} for l in D['lotlar']}


def yenile():
    """Dünyanın açık artırması değişti (game.dunya_izle): lotlar yerinde yenilenir. Kaldırılan lottaki teklif dönem sonunda iade
    edilir (settle: lot yoksa kredi geri)."""
    yeni = VERI.yukle('sosyal.json')['muzayede']['lotlar']
    with LOCK:
        LOTS.clear()
        LOTS.update({(l[2], l[0]): {'loot': l[0], 'grup': l[1], 'tur': l[2], 'adet': l[3], 'anlik': l[4], 'fiyat': l[5]} for l in yeni})
REQUESTS = {'AuctionListRequest', 'AuctionBidRequest', 'AuctionQuickBuyRequest', 'GetNamFIagRequest', 'UpdateNamFIagRequest',
            'AuctionTestRequest'}
B = D['bitis']


def mod(_cls, **f):
    f['_'] = _cls
    return f


def period_end(kind, now):
    """Dönemin bitiş anı (UTC saniye)."""
    t = int(now)
    if kind == 'hour':
        end = t - t % 3600 + B['saat_dk'] * 60
        return end if end > t else end + 3600
    end = t - t % 86400 + B['gun_sn']
    if end <= t:
        end += 86400
    if kind == 'day':
        return end
    while time.gmtime(end).tm_wday != B['hafta_gunu']:
        end += 86400
    return end


R = D['rakipler']
SPAN = {'hour': 3600, 'day': 86400, 'week': 7 * 86400}
SON_SN = 5                      # rakip karşılığını dönemin bitiminden en geç bu kadar önce verir
LOCK = threading.Lock()
SONUC = {}                      # (tür, lot, bitiş) -> dönemin en yüksek oyuncu teklifi (teklif, zaman, ad, kimlik)
OLAY_SINIRI = 60
# oyundaki ekran mesajı (alarm ve otomatik teklif sınırı): istemcinin diline göre (Türkçe, öteki diller İngilizce)
EKRAN = {'gecildi': ('Açık artırma: %s teklifin geçildi.', 'Auction: you were outbid on %s.'),
         'bitiyor': ('Açık artırma: %s için %d dakika kaldı.', 'Auction: %d minutes left for %s.'),
         'oto_sinir': ('Açık artırma: %s otomatik teklif sınırına ulaştı.', 'Auction: %s reached the auto-bid limit.')}


def bids(lot, end, skip=None):
    """Sunucudaki oyuncuların bu lotun bu dönemine teklifleri -> [(teklif, zaman, ad, kimlik)] (skip: bu profil hariç)."""
    import topluluk as TP
    key, out = '%s|%s' % (lot['tur'], lot['loot']), []
    for k in TP.hepsi().values():
        b = ((k.profil.d.get('muzayede') or {}).get('teklifler') or {}).get(key)
        if k.profil is not skip and b and b.get('bitis') == end:
            out.append((int(b['teklif']), int(b.get('zaman', 0)), k.ad, k.uid))
    return out


def best(lst):
    return max(lst, key=lambda x: (x[0], -x[1]), default=None)


def rival_level():
    """Sanal rakiplerin seviyesi; dünyada müzayedeye katılan botlar varken 0: teklifleri botlar verir, sanal rakip onlarla çakışmasın
    (kullanıcı isteği 2026-10-30)."""
    from bot import yonetici as YN
    y = YN.AKTIF
    if y is not None and y.botlar and y.izin('muzayede'):
        return 0
    return AY.get('muzayede_rakip')


def plan(lot, end, level):
    """Rakibin bu dönemdeki planı {'butce', 'adimlar' [(an, teklif)], 'ad', 'id', 'tohum', 'cfg'} ya da None (rakip yok)."""
    cfg = R['seviyeler'].get(str(level))
    if not cfg:
        return None
    seed = '%s|%s|%d|%d' % (lot['tur'], lot['loot'], end, level)
    r = random.Random(seed)
    if r.random() >= cfg['ilgi']:
        return None
    if lot['anlik'] and lot['fiyat']:
        budget = lot['fiyat'] * r.uniform(*cfg['carpan'])
    else:
        budget = r.uniform(*cfg['fiyatsiz'])
    least, step = D['en_az_teklif'], D['artis']
    budget = max(least + step, int(round(budget, -4)))
    final = max(least, min(int(round(budget * r.uniform(*cfg['son']), -4)), budget - step))   # karşılıksız en son teklifi
    span = SPAN[lot['tur']]
    times = sorted(end - span + span * r.uniform(0, 0.95) for _ in range(r.randint(1, cfg['adim'])))
    fracs = sorted(r.uniform(0.2, 1.0) for _ in times[:-1]) + [1.0]
    steps, last = [], 0
    for t, fr in zip(times, fracs):
        a = max(least, int(round(final * fr, -4)))
        if a > last:
            steps.append((t, a))
            last = a
    name = '%s%s' % (r.choice(R['adlar']), r.choice(R['ekler']))
    return {'butce': budget, 'adimlar': steps, 'ad': name, 'id': 900000 + r.randrange(100000), 'tohum': seed, 'cfg': cfg}


def rival(lot, end, now, bid=None, level=None):
    """Rakibin `now` anındaki teklifi -> (teklif, ad, kimlik); rakip yoksa (0, '', 0). bid: oyuncunun bu dönemki teklifi
    {'teklif', 'zaman'}: Çekingen/Ilımlı rakip o anda donar, Rekabetçi/Agresif tepki süresi sonra karşılık verir."""
    level = rival_level() if level is None else level
    pl = plan(lot, end, level) if level else None
    if not pl:
        return 0, '', 0
    at = lambda t: max([a for s, a in pl['adimlar'] if s <= t], default=0)
    v = at(now)
    if bid and bid.get('teklif'):
        price, t0 = bid['teklif'], bid.get('zaman', end - SPAN[lot['tur']])
        if not pl['cfg'].get('gecer'):
            v = min(v, at(t0))                  # oyuncuyu geçmez: oyuncunun teklifindeki yerinde kalır
        elif price < pl['butce']:
            delay = SPAN[lot['tur']] * random.Random('%s|%d' % (pl['tohum'], int(t0))).uniform(*pl['cfg']['tepki'])
            if now >= min(t0 + delay, end - SON_SN):
                v = max(v, min(pl['butce'], price + D['artis']))
    return (v, pl['ad'], pl['id']) if v else (0, '', 0)


def is_drone(loot):
    import magaza as MG
    return loot in MG.DRONES


def stamp(t):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))


class Muzayede:
    def __init__(self, profil, log=print):
        self.p, self.log = profil, log
        self.m = None
        self.posta = None
        with self.p.lock:
            d = self.p.d.setdefault('muzayede', {})
            d.setdefault('teklifler', {})
            d.setdefault('gecmis', [])
            d.setdefault('onay_postasi', False)
            d.setdefault('otomatik', {})
            d.setdefault('alarmlar', {})
            d.setdefault('olaylar', [])

    @property
    def d(self):
        return self.p.d['muzayede']

    def bid_rec(self, lot, now):
        """Oyuncunun bu dönemdeki teklif kaydı {'teklif', 'bitis', 'zaman'} ya da None."""
        b = self.d['teklifler'].get('%s|%s' % (lot['tur'], lot['loot']))
        return b if b and b['bitis'] == period_end(lot['tur'], now) else None

    def bid_of(self, lot, now):
        b = self.bid_rec(lot, now)
        return b['teklif'] if b else 0

    def owned(self, lot):
        """Oyuncunun zaten sahip olduğu benzersiz lot (gemi, gemi tasarımı) ya da yeri kalmayan dron: müzayedede listelenmez
        (oyuncu bildirimi 2026-10-27: kazanılan gemi ve tasarımlar listede kalıyordu, azami Iris'te Iris de)."""
        m = self.m
        if not m:
            return False
        loot = lot['loot']
        return m.owned_unique(loot) or (is_drone(loot) and not m.drone_room(loot))

    def unit_price(self, lot):
        """Anında alım bedeli (uridyum): dronda kaçıncı dron olduğuna göre mağaza fiyatı (Iris 15.000'den artar), ötekilerde lotun sabiti."""
        m = self.m
        if m and is_drone(lot['loot']):
            cur, price = m.drone_price(lot['loot'])
            if cur == 'uridium':
                return price
        return lot['fiyat']

    def data(self, lot, now):
        b = self.bid_rec(lot, now)
        mine = b['teklif'] if b else 0
        end = period_end(lot['tur'], now)
        riv, rname, rid = rival(lot, end, now, b)
        o = best(bids(lot, end, self.p))                       # öteki oyuncuların en yüksek teklifi
        if o and o[0] > riv and (o[0] > mine or (o[0] == mine and b and o[1] < b.get('zaman', 0))):
            riv, rname, rid = o[0], o[2], o[3]
        lead = mine and mine > riv
        pl = self.p.d['pilot']
        return mod('AuctionDataCommand', instantBuy=lot['anlik'], price=self.unit_price(lot), highestBid=max(mine, riv),
                   highestBidderName=pl.get('userName', '') if lead else rname, id=lot['loot'], myBid=mine, type=lot['tur'],
                   highestBidderId=self.p.user_id if lead else rid, group=lot['grup'], amount=lot['adet'])

    def list_cmd(self, now=None):
        now = now or time.time()
        hist = [mod('AuctionHistoryCommand', group=h['grup'], winnerId=h['kim'], currendBid=h['teklif'], auctionStartTime=h['tarih'],
                    lootId=h['loot'], type=h['tur'], winnerName=h['ad']) for h in self.history(now)]
        return ('AuctionListCommand', {
            'weekSubSec': period_end('week', now) - int(now), 'hourSubSec': period_end('hour', now) - int(now),
            'daySubSec': period_end('day', now) - int(now), 'historyList': hist,
            'myBidList': [self.data(l, now) for l in LOTS.values() if self.bid_of(l, now)],
            'auctionList': [self.data(l, now) for l in LOTS.values() if not self.owned(l)]})

    def history(self, now):
        """Oyuncunun kazandıkları ve kaybettikleri + sunucudaki öteki oyuncuların ve botların kazandıkları + (rakipler açıksa) son
        biten dönemlerin rakip kazananları (oyuncu bildirimi 2026-10-31: geçmişte yalnız kendi teklif verdikleri görünüyordu)."""
        import topluluk as TP
        out = list(self.d['gecmis'])
        seen = {(h['tur'], h['loot'], h['tarih']) for h in out}
        for k in TP.hepsi().values():
            if k.profil is self.p:
                continue
            for h in (k.profil.d.get('muzayede') or {}).get('gecmis') or ():
                if h.get('kim') == k.uid and (h['tur'], h['loot'], h['tarih']) not in seen:
                    seen.add((h['tur'], h['loot'], h['tarih']))
                    out.append(h)
        level = rival_level()
        if level:
            for kind, span in SPAN.items():
                end = period_end(kind, now) - span
                for lot in LOTS.values():
                    if lot['tur'] != kind or (kind, lot['loot'], stamp(end - span)) in seen:
                        continue
                    v, name, rid = rival(lot, end, end, None, level)
                    if v:
                        out.append({'grup': lot['grup'], 'kim': rid, 'teklif': v, 'tarih': stamp(end - span), 'loot': lot['loot'],
                                    'tur': kind, 'ad': name})
        out.sort(key=lambda h: h['tarih'], reverse=True)
        return out[:D['gecmis_siniri']]

    # -------------------------------------------------------- istekler
    def handle(self, name, f, now=None):
        """İstek -> yanıtlar. Dönem sonu bu istekle yakalanırsa (istemcinin sayacı bitince liste ister; oturumun tick'i 5 sn'de bir)
        kazanılan eşyanın, paranın ve postanın mesajları yanıttan önce gider (H176: atılıyordu, eşya ancak yeniden girişte görünüyordu)."""
        now = now or time.time()
        return self.settle(now) + self.answer(name, f, now)

    def answer(self, name, f, now):
        if name == 'AuctionListRequest':
            return [self.list_cmd(now), self.flag_cmd()]
        if name == 'GetNamFIagRequest':
            return [self.flag_cmd()]
        if name == 'UpdateNamFIagRequest':
            with self.p.lock:
                self.d['onay_postasi'] = bool(f.get('open'))
                self.p.dirty = True
            return [('UpdateNamFIagCommand', {'open': self.d['onay_postasi'], 'success': True})]
        if name == 'AuctionBidRequest':
            return self.bid(f, now)
        if name == 'AuctionQuickBuyRequest':
            return self.quick(f, now)
        if name == 'AuctionTestRequest':
            return [('AuctionTestCommand', {'args': []})]
        return []

    def flag_cmd(self):
        return ('GetNamFlagCommand', {'open': self.d['onay_postasi']})

    def bid(self, f, now):
        from magaza import stack_msg
        lot = LOTS.get((f.get('type'), f.get('lootId')))
        price = int(f.get('price') or 0)
        empty = mod('AuctionDataCommand', instantBuy=False, price=0, highestBid=0, highestBidderName='', id='', myBid=0, type='',
                    highestBidderId=0, group='', amount=0)
        fail = lambda key, **a: [('AuctionBidCommand', {'success': False, 'myBid': empty, 'curBid': empty, 'stack': stack_msg(key, **a)}),
                                 self.list_cmd(now), self.flag_cmd()]
        if not lot:
            return fail('auction_error_generic')
        if self.owned(lot) and not self.bid_rec(lot, now):
            return fail('drone_have_max' if is_drone(lot['loot']) else 'items_shop_error_ship_contains_ship')
        end = period_end(lot['tur'], now)
        rec = self.bid_rec(lot, now)
        mine = rec['teklif'] if rec else 0
        top = max([mine, rival(lot, end, now, rec)[0]] + [x[0] for x in bids(lot, end, self.p)])
        if price < D['en_az_teklif'] or price <= top or (mine and price < mine + D['artis']):
            return fail('auction_bid_minBid_not_reached', _MINIMUM_BID_='{:,}'.format(D['artis']))
        import envanter as INV
        if INV.spend(self.p, {'currency_credits': price - mine}, 'buy_SPECIAL', lot['loot']) is None:
            return fail('auction_bid_credits_to_little')
        with self.p.lock:
            self.d['teklifler']['%s|%s' % (lot['tur'], lot['loot'])] = {'teklif': price, 'bitis': end, 'zaman': int(now)}
            self.p.dirty = True
        self.log('   müzayede teklifi: %s %s %d kredi' % (lot['tur'], lot['loot'], price))
        cur = self.data(lot, now)
        return [('AuctionBidCommand', {'success': True, 'myBid': cur, 'curBid': cur, 'stack': stack_msg('auction_bid_saved')}),
                self.list_cmd(now), self.flag_cmd()] + (self.m.money_msgs() if self.m else [])

    def quick(self, f, now):
        from magaza import stack_msg
        lot = LOTS.get((f.get('type'), f.get('lootId')))
        if not lot or not lot['anlik'] or not lot['fiyat']:
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg('auction_buy_instant_invalid')})]
        if self.owned(lot):
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg(
                'drone_have_max' if is_drone(lot['loot']) else 'items_shop_error_ship_contains_ship')})]
        price = self.unit_price(lot)
        import envanter as INV
        if INV.spend(self.p, {'currency_uridium': price}, 'buy_SPECIAL', lot['loot']) is None:
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg('not_enough_uridium')})]
        self.log('   müzayede anında alım: %s x%d (%d U)' % (lot['loot'], lot['adet'], price))
        msgs = self.m.reward(lot['loot'], lot['adet']) if self.m else []
        return [('AuctionQuickBuyCommand', {'success': True, 'stack': stack_msg('empty')}), self.list_cmd(now)] + \
            (self.m.money_msgs() if self.m else []) + msgs

    # -------------------------------------------------------- dönem sonu
    # -------------------------------------------------------- panel: otomatik teklif, alarm, olaylar
    def top(self, lot, now):
        """Lotun bu dönemdeki en yüksek teklifi (oyuncunun, rakibin, öteki oyuncuların) ve oyuncunun önde olup olmadığı."""
        rec = self.bid_rec(lot, now)
        mine = rec['teklif'] if rec else 0
        others = [rival(lot, period_end(lot['tur'], now), now, rec)[0]] + [x[0] for x in bids(lot, period_end(lot['tur'], now), self.p)]
        return max([mine] + others), bool(mine) and mine > max(others)

    def next_bid(self, lot, now):
        """En düşük geçerli teklif (bid()'in kuralları)."""
        rec = self.bid_rec(lot, now)
        mine = rec['teklif'] if rec else 0
        top = self.top(lot, now)[0]
        return max(D['en_az_teklif'], top + D['artis'], mine + D['artis'] if mine else 0)

    def olay(self, tip, lot, ekran=False, **ek):
        """Olay kaydı (panel bildirimi) -> oyundaki ekran mesajı (ekran: alarm ya da sınır)."""
        with self.p.lock:
            no = (self.d['olaylar'][0]['no'] if self.d['olaylar'] else 0) + 1
            self.d['olaylar'].insert(0, dict(ek, no=no, zaman=int(time.time()), tip=tip, tur=lot['tur'], loot=lot['loot']))
            del self.d['olaylar'][OLAY_SINIRI:]
            self.p.dirty = True
        if not (ekran and tip in EKRAN):
            return []
        import kapi as KAPI
        tr = (getattr(self.m, 'dil', None) or '').startswith('tr')
        metin, ad = EKRAN[tip][0 if tr else 1], lot['loot'].rsplit('_', 1)[-1].upper()      # sunucuda eşya adı yok: MCB-25
        metin = metin % (((ad, ek['dk']) if tr else (ek['dk'], ad)) if tip == 'bitiyor' else ad)
        return [KAPI.screen(metin)]

    def oto(self, now=None):
        """Otomatik teklifler ve bitiş alarmları (tick) -> mesajlar."""
        now = now or time.time()
        msgs = []
        for key, a in list(self.d['alarmlar'].items()):
            lot = LOTS.get(tuple(key.split('|', 1)))
            end = lot and period_end(lot['tur'], now)
            if lot and a.get('dk') and end - now <= a['dk'] * 60 and a.get('son') != end:
                with self.p.lock:
                    a['son'] = end
                    self.p.dirty = True
                msgs += self.olay('bitiyor', lot, ekran=True, dk=max(1, int((end - now) // 60)))
        for key, r in list(self.d['otomatik'].items()):
            lot = LOTS.get(tuple(key.split('|', 1)))
            if not lot or self.owned(lot) and not self.bid_rec(lot, now):
                continue
            end = period_end(lot['tur'], now)
            if end - now <= SON_SN or self.top(lot, now)[1]:
                continue
            price = self.next_bid(lot, now)
            if price > r['azami']:
                if r.get('bildirilen') != end:
                    with self.p.lock:
                        r['bildirilen'] = end
                        self.p.dirty = True
                    msgs += self.olay('oto_sinir', lot, ekran=True, azami=r['azami'], gereken=price)
                continue
            out = self.bid({'type': lot['tur'], 'lootId': lot['loot'], 'price': price}, now)
            if out and out[0][1].get('success'):
                self.log('   müzayede otomatik teklif: %s %d (azami %d)' % (lot['loot'], price, r['azami']))
                msgs += self.olay('oto_teklif', lot, fiyat=price) + [m for m in out[1:]]
        return msgs

    def outbid(self, now):
        """Süren dönemde teklifi geçilen lotlar: kredi hemen iade, kayıt düşer (forum 127234) -> (postalar, iade var mı)."""
        msgs, back = [], False
        for key, b in list(self.d['teklifler'].items()):
            kind, loot = key.split('|', 1)
            lot = LOTS.get((kind, loot))
            if b['bitis'] <= now or not lot:
                continue
            riv = rival(lot, b['bitis'], now, b)[0]
            o = best(bids(lot, b['bitis'], self.p))
            if riv <= b['teklif'] and not (o and (o[0] > b['teklif'] or (o[0] == b['teklif'] and o[1] < b.get('zaman', 0)))):
                continue
            with self.p.lock:
                self.d['teklifler'].pop(key, None)
                self.p.dirty = True
            self.p.gain(kredi=b['teklif'], neden='auction_bookMoneyBack', detay=loot)
            self.log('   müzayede teklifi geçildi: %s (%d kredi geri)' % (loot, b['teklif']))
            msgs += self.mail(lot, b, 1) + self.olay('gecildi', lot, ekran=bool(self.d['alarmlar'].get(key, {}).get('gecilince')),
                                                       fiyat=b['teklif'], oto=key in self.d['otomatik'])
            back = True
        return msgs, back

    def settle(self, now=None):
        """Biten dönemlerdeki teklifler: kazanılan eşya verilir; süren dönemde geçilen teklifin kredisi geri -> mesajlar."""
        now = now or time.time()
        msgs, back = self.outbid(now)
        for key, b in list(self.d['teklifler'].items()):
            if b['bitis'] > now:
                continue
            kind, loot = key.split('|', 1)
            lot = LOTS.get((kind, loot))
            with self.p.lock:
                self.d['teklifler'].pop(key, None)
                self.p.dirty = True
            if not lot:
                self.p.gain(kredi=b['teklif'], neden='auction_bookMoneyBack', detay=loot)
                continue
            span = SPAN[kind]
            riv, rname, rid = rival(lot, b['bitis'], b['bitis'], b)
            with LOCK:                                                   # oyuncuların kazananı dönemde bir kez
                win = SONUC.get((kind, loot, b['bitis']))
                if win is None:
                    me = (int(b['teklif']), int(b.get('zaman', 0)), self.p.d['pilot'].get('userName', ''), self.p.user_id)
                    win = SONUC[(kind, loot, b['bitis'])] = best(bids(lot, b['bitis'], self.p) + [me])
            if win[3] != self.p.user_id and win[0] > riv:                # başka oyuncu kazandı
                riv, rname, rid = win[0], win[2], win[3]
            if b['teklif'] <= riv or win[3] != self.p.user_id:         # rakip ya da oyuncu kazandı: kredi geri, geçmişte onun adı
                self.p.gain(kredi=b['teklif'], neden='auction_bookMoneyBack', detay=loot)
                with self.p.lock:
                    self.d['gecmis'].insert(0, {'grup': lot['grup'], 'kim': rid, 'teklif': riv, 'tarih': stamp(b['bitis'] - span),
                                                'loot': loot, 'tur': kind, 'ad': rname})
                    del self.d['gecmis'][D['gecmis_siniri']:]
                self.log('   müzayede kaybedildi: %s (%s %d kredi; teklifin %d geri)' % (loot, rname, riv, b['teklif']))
                msgs += self.mail(lot, b, 1) + self.olay('kaybedildi', lot, fiyat=riv, ad=rname)
                continue
            pl = self.p.d['pilot']
            with self.p.lock:
                self.d['gecmis'].insert(0, {'grup': lot['grup'], 'kim': self.p.user_id, 'teklif': b['teklif'],
                                            'tarih': stamp(b['bitis'] - span), 'loot': loot, 'tur': kind, 'ad': pl.get('userName', '')})
                del self.d['gecmis'][D['gecmis_siniri']:]
                self.p.dirty = True
            self.log('   müzayede kazanıldı: %s x%d (%d kredi)' % (loot, lot['adet'], b['teklif']))
            msgs += (self.m.reward(loot, lot['adet']) if self.m else []) + self.mail(lot, b, 2) + self.olay('kazanildi', lot, fiyat=b['teklif'])
        if (msgs or back) and self.m:
            msgs += self.m.money_msgs()
        return msgs

    def mail(self, lot, b, msg_type):
        if not (self.posta and self.d['onay_postasi']):
            return []
        import posta as PS
        rec = self.posta.add(PS.AUCTION, '', '', sender='', extra={'lootId': lot['loot'], 'auctionType': lot['tur'],
                                                                  'amount': b['teklif'], 'msgType': msg_type, 'auctionId': 0})
        return [self.posta.notify(rec)]
