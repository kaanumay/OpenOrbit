"""Yerel müzayede (yol haritası Aşama 10; istemcinin Auction* mesajları ve UIAuction penceresi).

Lotlar kayıttaki listeden (data/social.json, tools/social.py): saatlik, günlük ve haftalık; teklif kredisiyle, anında alım
uridyumla. Dönem bitişi: saatlik her saatin 30. dakikası, günlük 22:30 UTC, haftalık pazar 22:30 UTC (kayıttaki kalan süreler).
  AuctionListRequest          -> AuctionListCommand {hour/day/weekSubSec, auctionList, myBidList, historyList}
  AuctionBidRequest {lootId, type, price}  -> AuctionBidCommand {success, myBid, curBid, stack} + liste + para
      en az 10.000 kredi, en yüksek tekliften büyük ve önceki teklifinden en az 10.000 fazla ("auction_bid_minBid_not_reached");
      kredi teklifte düşer (önceki teklifin farkı), kredi yetmezse "auction_bid_credits_to_little" (kayıt: enumBaseKey 93)
  AuctionQuickBuyRequest {lootId, type}    -> uridyumla hemen (anında alımı olmayan lot: "auction_buy_instant_invalid")
  Get/UpdateNamFIagRequest                 -> onay postaları açık mı (istemci: "Enable confirmation messages")
Dönem bitince en yüksek teklif oyuncununsa eşya verilir (mağazanın ödül yolu), geçmişe yazılır, onay postası açıksa posta
(müzayede mesajı, msgType 2 "Item purchased").
Sanal rakipler isteğe bağlı (panelin Müzayede ayarı, settings.py muzayede_rakip; varsayılan kapalı: teklifleri yalnız oyuncu verir).
Seviyeler data/social.json rakipler'de. Her lotun her döneminde olasılıkla bir rakip: bütçesi, dönem içindeki teklif adımları ve
adı lot, dönem ve seviye tohumlu (yeniden hesaplanır, saklanmaz).
  Çekingen, Ilımlı ('gecer' yok): birkaç küçük teklif verir; oyuncu teklif verince donar, oyuncuyu hiç geçmez -> lot oyuncunun.
  Rekabetçi, Agresif: oyuncu geçince bir tepki süresi sonra karşılık verir (oyuncunun teklifi + artış, bütçeye kadar; dönemin
  son 5 saniyesine kalmadan). Bütçeyi aşan teklif kazanır. Teklifi geçilen oyuncunun kredisi hemen geri gelir, teklif kaydı düşer
  (yeniden tam tutarla teklif verir; resmî forum 127234) ve onay postası açıksa "geçildin" postası.
Bot oyuncular gelince (Aşama 11) teklifleri rival() döndürecek.
Panelin Açık Artırma sayfası (panel_channel.py; kullanıcı isteği 2026-10-28): kurallar profilde, panel kapalıyken de oturumun tick'inde
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
import game_data as DATA

import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = DATA.load('social.json')['auction']
LOTS = {(l[2], l[0]): {'loot': l[0], 'group': l[1], 'type': l[2], 'count': l[3], 'instant': l[4], 'price': l[5]} for l in D['lots']}


def refresh():
    """Dünyanın açık artırması değişti (game.dunya_izle): lotlar yerinde yenilenir. Kaldırılan lottaki teklif dönem sonunda iade
    edilir (settle: lot yoksa kredi geri)."""
    new_ = DATA.load('social.json')['auction']['lots']
    with LOCK:
        LOTS.clear()
        LOTS.update({(l[2], l[0]): {'loot': l[0], 'group': l[1], 'type': l[2], 'count': l[3], 'instant': l[4], 'price': l[5]} for l in new_})
REQUESTS = {'AuctionListRequest', 'AuctionBidRequest', 'AuctionQuickBuyRequest', 'GetNamFIagRequest', 'UpdateNamFIagRequest',
            'AuctionTestRequest'}
B = D['end_time']


def mod(_cls, **f):
    f['_'] = _cls
    return f


def period_end(kind, now):
    """Dönemin bitiş anı (UTC saniye)."""
    t = int(now)
    if kind == 'hour':
        end = t - t % 3600 + B['hour_min'] * 60
        return end if end > t else end + 3600
    end = t - t % 86400 + B['day_sec']
    if end <= t:
        end += 86400
    if kind == 'day':
        return end
    while time.gmtime(end).tm_wday != B['weekday']:
        end += 86400
    return end


R = D['rivals']
SPAN = {'hour': 3600, 'day': 86400, 'week': 7 * 86400}
LAST_SEC = 5                      # rakip karşılığını dönemin bitiminden en geç bu kadar önce verir
LOCK = threading.Lock()
RESULT = {}                      # (tür, lot, bitiş) -> dönemin en yüksek oyuncu teklifi (teklif, zaman, ad, kimlik)
EVENT_LIMIT = 60
# oyundaki ekran mesajı (alarm ve otomatik teklif sınırı): istemcinin diline göre (Türkçe, öteki diller İngilizce)
SCREEN = {'outbid': ('Açık artırma: %s teklifin geçildi.', 'Auction: you were outbid on %s.'),
         'ending': ('Açık artırma: %s için %d dakika kaldı.', 'Auction: %d minutes left for %s.'),
         'auto_limit': ('Açık artırma: %s otomatik teklif sınırına ulaştı.', 'Auction: %s reached the auto-bid limit.')}


def bids(lot, end, skip=None):
    """Sunucudaki oyuncuların bu lotun bu dönemine teklifleri -> [(teklif, zaman, ad, kimlik)] (skip: bu profil hariç)."""
    import community as TP
    key, out = '%s|%s' % (lot['type'], lot['loot']), []
    for k in TP.all_().values():
        b = ((k.profile.d.get('auction') or {}).get('bids') or {}).get(key)
        if k.profile is not skip and b and b.get('end_time') == end:
            out.append((int(b['bid']), int(b.get('time', 0)), k.name, k.uid))
    return out


def best(lst):
    return max(lst, key=lambda x: (x[0], -x[1]), default=None)


def rival_level():
    """Sanal rakiplerin seviyesi; dünyada müzayedeye katılan botlar varken 0: teklifleri botlar verir, sanal rakip onlarla çakışmasın
    (kullanıcı isteği 2026-10-30)."""
    from bot import manager as MGR
    y = MGR.ACTIVE
    if y is not None and y.bots and y.permission('auction'):
        return 0
    return SET.get('auction_rivals')


def plan(lot, end, level):
    """Rakibin bu dönemdeki planı {'butce', 'adimlar' [(an, teklif)], 'ad', 'id', 'tohum', 'cfg'} ya da None (rakip yok)."""
    cfg = R['levels'].get(str(level))
    if not cfg:
        return None
    seed = '%s|%s|%d|%d' % (lot['type'], lot['loot'], end, level)
    r = random.Random(seed)
    if r.random() >= cfg['interest']:
        return None
    if lot['instant'] and lot['price']:
        budget = lot['price'] * r.uniform(*cfg['multiplier'])
    else:
        budget = r.uniform(*cfg['unpriced'])
    least, step = D['min_bid'], D['increase']
    budget = max(least + step, int(round(budget, -4)))
    final = max(least, min(int(round(budget * r.uniform(*cfg['last']), -4)), budget - step))   # karşılıksız en son teklifi
    span = SPAN[lot['type']]
    times = sorted(end - span + span * r.uniform(0, 0.95) for _ in range(r.randint(1, cfg['step'])))
    fracs = sorted(r.uniform(0.2, 1.0) for _ in times[:-1]) + [1.0]
    steps, last = [], 0
    for t, fr in zip(times, fracs):
        a = max(least, int(round(final * fr, -4)))
        if a > last:
            steps.append((t, a))
            last = a
    name = '%s%s' % (r.choice(R['names']), r.choice(R['attachments']))
    return {'budget': budget, 'steps': steps, 'name': name, 'id': 900000 + r.randrange(100000), 'seed': seed, 'cfg': cfg}


def rival(lot, end, now, bid=None, level=None):
    """Rakibin `now` anındaki teklifi -> (teklif, ad, kimlik); rakip yoksa (0, '', 0). bid: oyuncunun bu dönemki teklifi
    {'teklif', 'zaman'}: Çekingen/Ilımlı rakip o anda donar, Rekabetçi/Agresif tepki süresi sonra karşılık verir."""
    level = rival_level() if level is None else level
    pl = plan(lot, end, level) if level else None
    if not pl:
        return 0, '', 0
    at = lambda t: max([a for s, a in pl['steps'] if s <= t], default=0)
    v = at(now)
    if bid and bid.get('bid'):
        price, t0 = bid['bid'], bid.get('time', end - SPAN[lot['type']])
        if not pl['cfg'].get('outbids'):
            v = min(v, at(t0))                  # oyuncuyu geçmez: oyuncunun teklifindeki yerinde kalır
        elif price < pl['budget']:
            delay = SPAN[lot['type']] * random.Random('%s|%d' % (pl['seed'], int(t0))).uniform(*pl['cfg']['reaction'])
            if now >= min(t0 + delay, end - LAST_SEC):
                v = max(v, min(pl['budget'], price + D['increase']))
    return (v, pl['name'], pl['id']) if v else (0, '', 0)


def is_drone(loot):
    import shop as SHP
    return loot in SHP.DRONES


def stamp(t):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))


class Auction:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.mailer = None
        with self.p.lock:
            d = self.p.d.setdefault('auction', {})
            d.setdefault('bids', {})
            d.setdefault('history', [])
            d.setdefault('confirm_mail', False)
            d.setdefault('auto', {})
            d.setdefault('alarms', {})
            d.setdefault('events', [])

    @property
    def d(self):
        return self.p.d['auction']

    def bid_rec(self, lot, now):
        """Oyuncunun bu dönemdeki teklif kaydı {'teklif', 'bitis', 'zaman'} ya da None."""
        b = self.d['bids'].get('%s|%s' % (lot['type'], lot['loot']))
        return b if b and b['end_time'] == period_end(lot['type'], now) else None

    def bid_of(self, lot, now):
        b = self.bid_rec(lot, now)
        return b['bid'] if b else 0

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
        return lot['price']

    def data(self, lot, now):
        b = self.bid_rec(lot, now)
        mine = b['bid'] if b else 0
        end = period_end(lot['type'], now)
        riv, rname, rid = rival(lot, end, now, b)
        o = best(bids(lot, end, self.p))                       # öteki oyuncuların en yüksek teklifi
        if o and o[0] > riv and (o[0] > mine or (o[0] == mine and b and o[1] < b.get('time', 0))):
            riv, rname, rid = o[0], o[2], o[3]
        lead = mine and mine > riv
        pl = self.p.d['pilot']
        return mod('AuctionDataCommand', instantBuy=lot['instant'], price=self.unit_price(lot), highestBid=max(mine, riv),
                   highestBidderName=pl.get('userName', '') if lead else rname, id=lot['loot'], myBid=mine, type=lot['type'],
                   highestBidderId=self.p.user_id if lead else rid, group=lot['group'], amount=lot['count'])

    def list_cmd(self, now=None):
        now = now or time.time()
        hist = [mod('AuctionHistoryCommand', group=h['group'], winnerId=h['who'], currendBid=h['bid'], auctionStartTime=h['date'],
                    lootId=h['loot'], type=h['type'], winnerName=h['name']) for h in self.history(now)]
        return ('AuctionListCommand', {
            'weekSubSec': period_end('week', now) - int(now), 'hourSubSec': period_end('hour', now) - int(now),
            'daySubSec': period_end('day', now) - int(now), 'historyList': hist,
            'myBidList': [self.data(l, now) for l in LOTS.values() if self.bid_of(l, now)],
            'auctionList': [self.data(l, now) for l in LOTS.values() if not self.owned(l)]})

    def history(self, now):
        """Oyuncunun kazandıkları ve kaybettikleri + sunucudaki öteki oyuncuların ve botların kazandıkları + (rakipler açıksa) son
        biten dönemlerin rakip kazananları (oyuncu bildirimi 2026-10-31: geçmişte yalnız kendi teklif verdikleri görünüyordu)."""
        import community as TP
        out = list(self.d['history'])
        seen = {(h['type'], h['loot'], h['date']) for h in out}
        for k in TP.all_().values():
            if k.profile is self.p:
                continue
            for h in (k.profile.d.get('auction') or {}).get('history') or ():
                if h.get('who') == k.uid and (h['type'], h['loot'], h['date']) not in seen:
                    seen.add((h['type'], h['loot'], h['date']))
                    out.append(h)
        level = rival_level()
        if level:
            for kind, span in SPAN.items():
                end = period_end(kind, now) - span
                for lot in LOTS.values():
                    if lot['type'] != kind or (kind, lot['loot'], stamp(end - span)) in seen:
                        continue
                    v, name, rid = rival(lot, end, end, None, level)
                    if v:
                        out.append({'group': lot['group'], 'who': rid, 'bid': v, 'date': stamp(end - span), 'loot': lot['loot'],
                                    'type': kind, 'name': name})
        out.sort(key=lambda h: h['date'], reverse=True)
        return out[:D['history_limit']]

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
                self.d['confirm_mail'] = bool(f.get('open'))
                self.p.dirty = True
            return [('UpdateNamFIagCommand', {'open': self.d['confirm_mail'], 'success': True})]
        if name == 'AuctionBidRequest':
            return self.bid(f, now)
        if name == 'AuctionQuickBuyRequest':
            return self.quick(f, now)
        if name == 'AuctionTestRequest':
            return [('AuctionTestCommand', {'args': []})]
        return []

    def flag_cmd(self):
        return ('GetNamFlagCommand', {'open': self.d['confirm_mail']})

    def bid(self, f, now):
        from shop import stack_msg
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
        end = period_end(lot['type'], now)
        rec = self.bid_rec(lot, now)
        mine = rec['bid'] if rec else 0
        top = max([mine, rival(lot, end, now, rec)[0]] + [x[0] for x in bids(lot, end, self.p)])
        if price < D['min_bid'] or price <= top or (mine and price < mine + D['increase']):
            return fail('auction_bid_minBid_not_reached', _MINIMUM_BID_='{:,}'.format(D['increase']))
        import inventory as INV
        if INV.spend(self.p, {'currency_credits': price - mine}, 'buy_SPECIAL', lot['loot']) is None:
            return fail('auction_bid_credits_to_little')
        with self.p.lock:
            self.d['bids']['%s|%s' % (lot['type'], lot['loot'])] = {'bid': price, 'end_time': end, 'time': int(now)}
            self.p.dirty = True
        self.log('   müzayede teklifi: %s %s %d kredi' % (lot['type'], lot['loot'], price))
        cur = self.data(lot, now)
        return [('AuctionBidCommand', {'success': True, 'myBid': cur, 'curBid': cur, 'stack': stack_msg('auction_bid_saved')}),
                self.list_cmd(now), self.flag_cmd()] + (self.m.money_msgs() if self.m else [])

    def quick(self, f, now):
        from shop import stack_msg
        lot = LOTS.get((f.get('type'), f.get('lootId')))
        if not lot or not lot['instant'] or not lot['price']:
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg('auction_buy_instant_invalid')})]
        if self.owned(lot):
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg(
                'drone_have_max' if is_drone(lot['loot']) else 'items_shop_error_ship_contains_ship')})]
        price = self.unit_price(lot)
        import inventory as INV
        if INV.spend(self.p, {'currency_uridium': price}, 'buy_SPECIAL', lot['loot']) is None:
            return [('AuctionQuickBuyCommand', {'success': False, 'stack': stack_msg('not_enough_uridium')})]
        self.log('   müzayede anında alım: %s x%d (%d U)' % (lot['loot'], lot['count'], price))
        msgs = self.m.reward(lot['loot'], lot['count']) if self.m else []
        return [('AuctionQuickBuyCommand', {'success': True, 'stack': stack_msg('empty')}), self.list_cmd(now)] + \
            (self.m.money_msgs() if self.m else []) + msgs

    # -------------------------------------------------------- dönem sonu
    # -------------------------------------------------------- panel: otomatik teklif, alarm, olaylar
    def top(self, lot, now):
        """Lotun bu dönemdeki en yüksek teklifi (oyuncunun, rakibin, öteki oyuncuların) ve oyuncunun önde olup olmadığı."""
        rec = self.bid_rec(lot, now)
        mine = rec['bid'] if rec else 0
        others = [rival(lot, period_end(lot['type'], now), now, rec)[0]] + [x[0] for x in bids(lot, period_end(lot['type'], now), self.p)]
        return max([mine] + others), bool(mine) and mine > max(others)

    def next_bid(self, lot, now):
        """En düşük geçerli teklif (bid()'in kuralları)."""
        rec = self.bid_rec(lot, now)
        mine = rec['bid'] if rec else 0
        top = self.top(lot, now)[0]
        return max(D['min_bid'], top + D['increase'], mine + D['increase'] if mine else 0)

    def event(self, tip, lot, screen=False, **extra):
        """Olay kaydı (panel bildirimi) -> oyundaki ekran mesajı (ekran: alarm ya da sınır)."""
        with self.p.lock:
            no = (self.d['events'][0]['no'] if self.d['events'] else 0) + 1
            self.d['events'].insert(0, dict(extra, no=no, time=int(time.time()), tip=tip, type=lot['type'], loot=lot['loot']))
            del self.d['events'][EVENT_LIMIT:]
            self.p.dirty = True
        if not (screen and tip in SCREEN):
            return []
        import galaxy_gates as KAPI
        tr = (getattr(self.m, 'lang', None) or '').startswith('tr')
        text, name = SCREEN[tip][0 if tr else 1], lot['loot'].rsplit('_', 1)[-1].upper()      # sunucuda eşya adı yok: MCB-25
        text = text % (((name, extra['min']) if tr else (extra['min'], name)) if tip == 'ending' else name)
        return [KAPI.screen(text)]

    def auto(self, now=None):
        """Otomatik teklifler ve bitiş alarmları (tick) -> mesajlar."""
        now = now or time.time()
        msgs = []
        for key, a in list(self.d['alarms'].items()):
            lot = LOTS.get(tuple(key.split('|', 1)))
            end = lot and period_end(lot['type'], now)
            if lot and a.get('min') and end - now <= a['min'] * 60 and a.get('last') != end:
                with self.p.lock:
                    a['last'] = end
                    self.p.dirty = True
                msgs += self.event('ending', lot, screen=True, min=max(1, int((end - now) // 60)))
        for key, r in list(self.d['auto'].items()):
            lot = LOTS.get(tuple(key.split('|', 1)))
            if not lot or self.owned(lot) and not self.bid_rec(lot, now):
                continue
            end = period_end(lot['type'], now)
            if end - now <= LAST_SEC or self.top(lot, now)[1]:
                continue
            price = self.next_bid(lot, now)
            if price > r['maximum']:
                if r.get('reported') != end:
                    with self.p.lock:
                        r['reported'] = end
                        self.p.dirty = True
                    msgs += self.event('auto_limit', lot, screen=True, maximum=r['maximum'], required=price)
                continue
            out = self.bid({'type': lot['type'], 'lootId': lot['loot'], 'price': price}, now)
            if out and out[0][1].get('success'):
                self.log('   müzayede otomatik teklif: %s %d (azami %d)' % (lot['loot'], price, r['maximum']))
                msgs += self.event('auto_bid', lot, price=price) + [m for m in out[1:]]
        return msgs

    def outbid(self, now):
        """Süren dönemde teklifi geçilen lotlar: kredi hemen iade, kayıt düşer (forum 127234) -> (postalar, iade var mı)."""
        msgs, back = [], False
        for key, b in list(self.d['bids'].items()):
            kind, loot = key.split('|', 1)
            lot = LOTS.get((kind, loot))
            if b['end_time'] <= now or not lot:
                continue
            riv = rival(lot, b['end_time'], now, b)[0]
            o = best(bids(lot, b['end_time'], self.p))
            if riv <= b['bid'] and not (o and (o[0] > b['bid'] or (o[0] == b['bid'] and o[1] < b.get('time', 0)))):
                continue
            with self.p.lock:
                self.d['bids'].pop(key, None)
                self.p.dirty = True
            self.p.gain(credits=b['bid'], reason='auction_bookMoneyBack', detail=loot)
            self.log('   müzayede teklifi geçildi: %s (%d kredi geri)' % (loot, b['bid']))
            msgs += self.mail(lot, b, 1) + self.event('outbid', lot, screen=bool(self.d['alarms'].get(key, {}).get('when_outbid')),
                                                       price=b['bid'], auto=key in self.d['auto'])
            back = True
        return msgs, back

    def settle(self, now=None):
        """Biten dönemlerdeki teklifler: kazanılan eşya verilir; süren dönemde geçilen teklifin kredisi geri -> mesajlar."""
        now = now or time.time()
        msgs, back = self.outbid(now)
        for key, b in list(self.d['bids'].items()):
            if b['end_time'] > now:
                continue
            kind, loot = key.split('|', 1)
            lot = LOTS.get((kind, loot))
            with self.p.lock:
                self.d['bids'].pop(key, None)
                self.p.dirty = True
            if not lot:
                self.p.gain(credits=b['bid'], reason='auction_bookMoneyBack', detail=loot)
                continue
            span = SPAN[kind]
            riv, rname, rid = rival(lot, b['end_time'], b['end_time'], b)
            with LOCK:                                                   # oyuncuların kazananı dönemde bir kez
                win = RESULT.get((kind, loot, b['end_time']))
                if win is None:
                    me = (int(b['bid']), int(b.get('time', 0)), self.p.d['pilot'].get('userName', ''), self.p.user_id)
                    win = RESULT[(kind, loot, b['end_time'])] = best(bids(lot, b['end_time'], self.p) + [me])
            if win[3] != self.p.user_id and win[0] > riv:                # başka oyuncu kazandı
                riv, rname, rid = win[0], win[2], win[3]
            if b['bid'] <= riv or win[3] != self.p.user_id:         # rakip ya da oyuncu kazandı: kredi geri, geçmişte onun adı
                self.p.gain(credits=b['bid'], reason='auction_bookMoneyBack', detail=loot)
                with self.p.lock:
                    self.d['history'].insert(0, {'group': lot['group'], 'who': rid, 'bid': riv, 'date': stamp(b['end_time'] - span),
                                                'loot': loot, 'type': kind, 'name': rname})
                    del self.d['history'][D['history_limit']:]
                self.log('   müzayede kaybedildi: %s (%s %d kredi; teklifin %d geri)' % (loot, rname, riv, b['bid']))
                msgs += self.mail(lot, b, 1) + self.event('lost', lot, price=riv, name=rname)
                continue
            pl = self.p.d['pilot']
            with self.p.lock:
                self.d['history'].insert(0, {'group': lot['group'], 'who': self.p.user_id, 'bid': b['bid'],
                                            'date': stamp(b['end_time'] - span), 'loot': loot, 'type': kind, 'name': pl.get('userName', '')})
                del self.d['history'][D['history_limit']:]
                self.p.dirty = True
            self.log('   müzayede kazanıldı: %s x%d (%d kredi)' % (loot, lot['count'], b['bid']))
            msgs += (self.m.reward(loot, lot['count']) if self.m else []) + self.mail(lot, b, 2) + self.event('won', lot, price=b['bid'])
        if (msgs or back) and self.m:
            msgs += self.m.money_msgs()
        return msgs

    def mail(self, lot, b, msg_type):
        if not (self.mailer and self.d['confirm_mail']):
            return []
        import mail as PS
        rec = self.mailer.add(PS.AUCTION, '', '', sender='', extra={'lootId': lot['loot'], 'auctionType': lot['type'],
                                                                  'amount': b['bid'], 'msgType': msg_type, 'auctionId': 0})
        return [self.mailer.notify(rec)]
