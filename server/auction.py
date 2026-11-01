"""Local auction (roadmap stage 10; the client's Auction* messages and UIAuction window).

Lots come from the list in the save (data/social.json, tools/social.py): hourly, daily and weekly; bids in credits, instant buy
in uridium. Period end: hourly at minute 30 of every hour, daily 22:30 UTC, weekly Sunday 22:30 UTC (the remaining times in the save).
  AuctionListRequest          -> AuctionListCommand {hour/day/weekSubSec, auctionList, myBidList, historyList}
  AuctionBidRequest {lootId, type, price}  -> AuctionBidCommand {success, myBid, curBid, stack} + list + currency
      at least 10,000 credits, higher than the top bid and at least 10,000 more than the previous bid ("auction_bid_minBid_not_reached");
      credits are deducted when bidding (the difference from the previous bid), if credits are short "auction_bid_credits_to_little" (save: enumBaseKey 93)
  AuctionQuickBuyRequest {lootId, type}    -> immediately with uridium (a lot with no instant buy: "auction_buy_instant_invalid")
  Get/UpdateNamFIagRequest                 -> whether confirmation mails are on (client: "Enable confirmation messages")
When a period ends and the top bid is the player's, the item is given (the shop's reward path), written to history and, if confirmation
mail is on, mailed (auction message, msgType 2 "Item purchased").
Virtual rivals are optional (the panel's Auction setting, settings.py auction_rivals; off by default: only the player places bids).
The levels are in data/social.json rivals. In every period of every lot there is a rival with some probability: its budget, its bid steps
within the period and its name are seeded by lot, period and level (recomputed, not stored).
  Timid, Moderate ('outbids' false): place a few small bids; they freeze once the player bids and never outbid the player -> the lot goes to the player.
  Competitive, Aggressive: when the player outbids them they answer after a reaction time (the player's bid + increase, up to the budget; not
  later than the last 5 seconds of the period). A bid over the budget wins. The credits of the outbid player come back at once, the bid record is dropped
  (they bid again with the full amount; official forum 127234) and, if confirmation mail is on, an "outbid" mail.
When bot players arrive (stage 11), rival() will return their bids.
The panel's Auction page (panel_channel.py; user request 2026-10-28): the rules are in the profile and work in the session's tick even when the panel
is closed (Social.tick -> settle + auto):
  auto {"type|lot": {maximum, reported}}  when outbid (or when there is no bid at all) places the lowest valid bid (top + increase,
      at least min_bid); if it would exceed the maximum, an "auto_limit" event once; the rule stays after the period ends (applies again every period).
  alarms {"type|lot": {when_outbid, min, last}}  when the bid is outbid, and min minutes before the period ends: an on-screen message in the game.
  events [{no, time, tip, type, loot, ...}]  outbid, ending, won, lost, auto_bid, auto_limit (last EVENT_LIMIT; the panel
      shows new events as notifications).
On a multiplayer server the lots are the same for everyone: the other players' bids compete too (highest bid; on a tie, whoever bid first), and the
winner of the period is decided once, in the session that computes it first (RESULT): before, every player could win the same lot with their own bid.
"""
import json, os, random, threading, time
import game_data as DATA

import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = DATA.load('social.json')['auction']
LOTS = {(l[2], l[0]): {'loot': l[0], 'group': l[1], 'type': l[2], 'count': l[3], 'instant': l[4], 'price': l[5]} for l in D['lots']}


def refresh():
    """The world's auction changed (game.watch_world): lots are renewed in place. A bid on a removed lot is refunded
    at the end of the period (settle: if there is no lot, the credits go back)."""
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
    """End moment of the period (UTC seconds)."""
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
LAST_SEC = 5                      # the rival gives its answer at the latest this long before the period ends
LOCK = threading.Lock()
RESULT = {}                      # (type, lot, end) -> the highest player bid of the period (bid, time, name, id)
EVENT_LIMIT = 60
# on-screen message in the game (alarm and auto-bid limit): by the client's language (Turkish, other languages English)
SCREEN = {'outbid': ('Açık artırma: %s teklifin geçildi.', 'Auction: you were outbid on %s.'),
         'ending': ('Açık artırma: %s için %d dakika kaldı.', 'Auction: %d minutes left for %s.'),
         'auto_limit': ('Açık artırma: %s otomatik teklif sınırına ulaştı.', 'Auction: %s reached the auto-bid limit.')}


def bids(lot, end, skip=None):
    """Bids of the players on the server for this period of this lot -> [(bid, time, name, id)] (skip: except this profile)."""
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
    """Level of the virtual rivals; 0 while bots in the world take part in the auction: the bots place the bids, so the virtual rival does not clash
    with them (user request 2026-10-30)."""
    from bot import manager as MGR
    y = MGR.ACTIVE
    if y is not None and y.bots and y.permission('auction'):
        return 0
    return SET.get('auction_rivals')


def plan(lot, end, level):
    """The rival's plan for this period {'budget', 'steps' [(moment, bid)], 'name', 'id', 'seed', 'cfg'} or None (no rival)."""
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
    final = max(least, min(int(round(budget * r.uniform(*cfg['last']), -4)), budget - step))   # its latest bid that has no answer
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
    """The rival's bid at moment `now` -> (bid, name, id); (0, '', 0) if there is no rival. bid: the player's bid in this period
    {'bid', 'time'}: a Timid/Moderate rival freezes at that moment, a Competitive/Aggressive one answers after a reaction time."""
    level = rival_level() if level is None else level
    pl = plan(lot, end, level) if level else None
    if not pl:
        return 0, '', 0
    at = lambda t: max([a for s, a in pl['steps'] if s <= t], default=0)
    v = at(now)
    if bid and bid.get('bid'):
        price, t0 = bid['bid'], bid.get('time', end - SPAN[lot['type']])
        if not pl['cfg'].get('outbids'):
            v = min(v, at(t0))                  # does not outbid the player: stays where it is under the player's bid
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
        """The player's bid record in this period {'bid', 'end_time', 'time'} or None."""
        b = self.d['bids'].get('%s|%s' % (lot['type'], lot['loot']))
        return b if b and b['end_time'] == period_end(lot['type'], now) else None

    def bid_of(self, lot, now):
        b = self.bid_rec(lot, now)
        return b['bid'] if b else 0

    def owned(self, lot):
        """A unique lot the player already owns (ship, ship design) or a drone with no room left: not listed in the auction
        (player report 2026-10-27: won ships and designs stayed in the list, and at max Iris, Iris too)."""
        m = self.m
        if not m:
            return False
        loot = lot['loot']
        return m.owned_unique(loot) or (is_drone(loot) and not m.drone_room(loot))

    def unit_price(self, lot):
        """Instant-buy price (uridium): for a drone, the shop price by which drone it would be (Iris rises from 15,000); for the rest, the lot's constant."""
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
        o = best(bids(lot, end, self.p))                       # the highest bid of the other players
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
        """What the player won and lost + what the other players and bots on the server won + (if rivals are on) the rival winners of the
        most recently ended periods (player report 2026-10-31: in history only the player's own bids showed)."""
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

    # -------------------------------------------------------- requests
    def handle(self, name, f, now=None):
        """Request -> replies. If the end of a period is caught by this request (the client asks for the list when its counter runs out; the session's tick runs every 5 s)
        the messages for the won item, currency and mail go before the reply (H176: they were dropped, the item only showed after logging in again)."""
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
        self.log('   auction bid: %s %s %d credits' % (lot['type'], lot['loot'], price))
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
        self.log('   auction instant buy: %s x%d (%d U)' % (lot['loot'], lot['count'], price))
        msgs = self.m.reward(lot['loot'], lot['count']) if self.m else []
        return [('AuctionQuickBuyCommand', {'success': True, 'stack': stack_msg('empty')}), self.list_cmd(now)] + \
            (self.m.money_msgs() if self.m else []) + msgs

    # -------------------------------------------------------- end of period
    # -------------------------------------------------------- panel: auto bid, alarm, events
    def top(self, lot, now):
        """The lot's highest bid in this period (the player's, the rival's, the other players') and whether the player is ahead."""
        rec = self.bid_rec(lot, now)
        mine = rec['bid'] if rec else 0
        others = [rival(lot, period_end(lot['type'], now), now, rec)[0]] + [x[0] for x in bids(lot, period_end(lot['type'], now), self.p)]
        return max([mine] + others), bool(mine) and mine > max(others)

    def next_bid(self, lot, now):
        """The lowest valid bid (the rules of bid())."""
        rec = self.bid_rec(lot, now)
        mine = rec['bid'] if rec else 0
        top = self.top(lot, now)[0]
        return max(D['min_bid'], top + D['increase'], mine + D['increase'] if mine else 0)

    def event(self, tip, lot, screen=False, **extra):
        """Event record (panel notification) -> on-screen message in the game (screen: alarm or limit)."""
        with self.p.lock:
            no = (self.d['events'][0]['no'] if self.d['events'] else 0) + 1
            self.d['events'].insert(0, dict(extra, no=no, time=int(time.time()), tip=tip, type=lot['type'], loot=lot['loot']))
            del self.d['events'][EVENT_LIMIT:]
            self.p.dirty = True
        if not (screen and tip in SCREEN):
            return []
        import galaxy_gates as GALAXY
        tr = (getattr(self.m, 'lang', None) or '').startswith('tr')
        text, name = SCREEN[tip][0 if tr else 1], lot['loot'].rsplit('_', 1)[-1].upper()      # the server has no item name: MCB-25
        text = text % (((name, extra['min']) if tr else (extra['min'], name)) if tip == 'ending' else name)
        return [GALAXY.screen(text)]

    def auto(self, now=None):
        """Auto bids and end alarms (tick) -> messages."""
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
                self.log('   auction auto bid: %s %d (maximum %d)' % (lot['loot'], price, r['maximum']))
                msgs += self.event('auto_bid', lot, price=price) + [m for m in out[1:]]
        return msgs

    def outbid(self, now):
        """Lots outbid during the running period: credits refunded at once, record dropped (forum 127234) -> (mails, whether there was a refund)."""
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
            self.log('   auction bid outbid: %s (%d credits back)' % (loot, b['bid']))
            msgs += self.mail(lot, b, 1) + self.event('outbid', lot, screen=bool(self.d['alarms'].get(key, {}).get('when_outbid')),
                                                       price=b['bid'], auto=key in self.d['auto'])
            back = True
        return msgs, back

    def settle(self, now=None):
        """Bids in ended periods: the won item is given; the credits of a bid outbid in a running period come back -> messages."""
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
            with LOCK:                                                   # the winner among the players, once per period
                win = RESULT.get((kind, loot, b['end_time']))
                if win is None:
                    me = (int(b['bid']), int(b.get('time', 0)), self.p.d['pilot'].get('userName', ''), self.p.user_id)
                    win = RESULT[(kind, loot, b['end_time'])] = best(bids(lot, b['end_time'], self.p) + [me])
            if win[3] != self.p.user_id and win[0] > riv:                # another player won
                riv, rname, rid = win[0], win[2], win[3]
            if b['bid'] <= riv or win[3] != self.p.user_id:         # a rival or the player won: credits back, its name in history
                self.p.gain(credits=b['bid'], reason='auction_bookMoneyBack', detail=loot)
                with self.p.lock:
                    self.d['history'].insert(0, {'group': lot['group'], 'who': rid, 'bid': riv, 'date': stamp(b['end_time'] - span),
                                                'loot': loot, 'type': kind, 'name': rname})
                    del self.d['history'][D['history_limit']:]
                self.log('   auction lost: %s (%s %d credits; %d of the bid back)' % (loot, rname, riv, b['bid']))
                msgs += self.mail(lot, b, 1) + self.event('lost', lot, price=riv, name=rname)
                continue
            pl = self.p.d['pilot']
            with self.p.lock:
                self.d['history'].insert(0, {'group': lot['group'], 'who': self.p.user_id, 'bid': b['bid'],
                                            'date': stamp(b['end_time'] - span), 'loot': loot, 'type': kind, 'name': pl.get('userName', '')})
                del self.d['history'][D['history_limit']:]
                self.p.dirty = True
            self.log('   auction won: %s x%d (%d credits)' % (loot, lot['count'], b['bid']))
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
