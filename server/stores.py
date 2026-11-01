"""Uridium-based shop windows (roadmap Ö7; data data/stores.json <- tools/stores_o7.py, source
belgeler/wiki/dukkanlar_o7.json). In Ö3's container (extra_events.add). The *BuyCommands that open the payment page (MileageMarketBuyCommand,
VIPMerchantExchangeBuyCommand, ReturneeLoginBundleBuyCommand) are never sent; the windows' "Buy now" buttons (the request does not say which
package it is, and there is no confirmation question) open the shop in Extras and give information (payment.open_shop): the packages are there for
uridium, once each while the event runs.

  Mileage Market (calendar mileage_market): token packages are in the shop (they give Mileage Coin); a 5% discount per token (at most 5 tokens = 25%)
      is applied once to the window's discount packages, then they are bought with uridium at the discounted price (MileageMarketExchangeRequest ->
      MileageMarketPackageBuyRequest). The tokens are deleted when the event ends.
  VIP Merchant Exchange (vip_merchant): VIP once one of the shop's VIP packages is bought; the exchange rows (in-game resource + uridium /
      credits) are open to VIP, with a limit per row.
  Returnee Login: if the last session in the save is older than 14 days (and the last campaign older than 60 days), a 15-day campaign on login: welcome reward,
      7-day login calendar, return packages in the shop. When the time is up, the client's hide request closes the campaign.
  Pre-Prometheus Day Sales (pre_prometheus): the number of different Pre-BF packages bought (information window only).
  Return of Hero (return_of_hero): the returning player (TRUE / INVITEE); any code ties to a virtual veteran, only within 24 hours of the first
      login during the event (FAQ); 13 non-repeating and 5 quests a day (from the Season Pass pool) give a Returnee Key; keys are exchanged
      in the Exchange tab (BattlePassKeyExchange*, exchangeType 2; the list is the FAQ's).
  Stellar Pathfinder: packages in the shop from level 5, once per account (the window's _claim button is inside the client: no counterpart).
      5-14 in the game; in single player there is no upper limit because it is Solaris' only way (the range is passed quickly with the EP multiplier).
In the profile 'stores': mileage {period, discount {package: step}, claimed []}, vip {period, exchange {reward: n}}, returnee {start,
  welcome, day, last_day, off, last_campaign}, pre_bf {period, claimed []}, rehero {period, first_login, connected, veteran, code, value,
  done, claimed, day_number, exchange}, one_time [package].
"""
import datetime, json, os, random, time

import inventory as INV
import quest_tracker as GT
import payment as PAY
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'stores.json'), encoding='utf8'))
MM, VIP, RL, PB, CT, SP = D['mileage'], D['vip'], D['returnee'], D['pre_bf'], D['rehero'], D['stellar']
_PRICE = json.load(open(os.path.join(HERE, 'data', 'prices.json'), encoding='utf8'))['prices']     # market balance
for _r in MM['discount_packages']:                 # the discount packages are only in the window: their prices from the balance
    if _PRICE.get(_r['lootId'], {}).get('currency') == 'U':
        _r['uridium'] = _PRICE[_r['lootId']]['price']
MM_COIN = {r['lootId'] for r in MM['token_packages']}
MM_DISC = {r['id']: r for r in MM['discount_packages']}
VIP_PKG = {r['lootId'] for r in VIP['packages']}
RL_PKG = {r['lootId'] for r in RL['packages']}
PB_PKG = {r['lootId'] for r in PB['packages']}
SP_PKG = {r['lootId'] for r in SP['packages']}
RH_Q = {q['id']: q for q in CT['quests']}
RH_X = {r['exchangeReward']: r for r in CT['exchange']}
DAY = 86400


def mod(_cls, **f):
    f['_'] = _cls
    return f


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now)


class Stores:
    REQUESTS = ('MileageMarketEventBuyRequest', 'MileageMarketExchangeRequest', 'MileageMarketPackageBuyRequest',
                'VIPMerchantExchangeBuyRequest', 'VIPMerchantExchangeRequest',
                'ReturneeLoginRewardClaimRequest', 'ReturneeLoginBundleBuyRequest', 'ReturneeLoginHideUIItemRequest',
                'EventReturnOfHeroActionRequest', 'EventANewHopeActionRequest')

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.send = None
        self.map_id = None
        shop.shop_gate = self.shop_gate          # visibility in the shop (event / once / level)
        shop.on_bought.append(self.bought)
        self.prev_seen = self.st.get('last_session') # the last moment of the previous session (Returnee Login; tick writes it)
        self.returnee_check(self.prev_seen)
        if CAL.is_active(CT['calendar']) and 'first_login' not in self.rh():
            with self.p.lock:                      # the first login in Return of Hero: the time to tie to a veteran comes from here
                self.rh()['first_login'] = time.time()
                self.p.dirty = True

    @property
    def st(self):
        return self.p.d.setdefault('stores', {})

    def part(self, key, event=None):
        """Event-tied section: reset when the period changes."""
        st = self.st.setdefault(key, {})
        if event:
            per = CAL.period(event)
            tag = per and str(int(per[0])) or ('on' if CAL.is_active(event) else '')
            if st.get('period') != tag:
                st.clear()
                st['period'] = tag
                self.p.dirty = True
        return st

    def money(self):
        return self.m.money_msgs() if self.m else []

    # ------------------------------------------------------------ shop hooks
    def shop_gate(self, entry, loot):
        """Whether an extra shop row is sold now (calendar / campaign, once, Stellar's level)."""
        ev = entry.get('calendar') if entry else None
        if ev == 'returnee':
            if not self.returnee_active():
                return False
        elif ev and not CAL.is_active(ev):
            return False
        if loot in SP_PKG:
            lv, (lo, hi) = self.p.d['pilot'].get('level', 1), SP['level']     # hi None: no upper limit
            if lv < lo or (hi is not None and lv > hi):
                return False
        if (entry and entry.get('once')) or loot in SP_PKG:
            return loot not in self.bought_set(ev)
        return True

    def bought_set(self, ev):
        if ev and ev != 'returnee':
            return set(self.part('alinan_' + ev, ev).get('entries', []))
        return set(self.st.get('one_time', []))

    def bought(self, loot, amount):
        """Purchase from the shop (shop.on_bought): once-only items, VIP, Pre-BF counters -> messages."""
        ev = next((e for s, e in ((MM_COIN, 'mileage_market'), (VIP_PKG, 'vip_merchant'), (PB_PKG, 'pre_prometheus')) if loot in s), None)
        entry = self.m.extra_entry.get(loot) or {}
        if not ev and entry.get('once') and entry.get('calendar') not in (None, 'returnee'):
            ev = entry['calendar']     # Return of Hero's once-only VIP badge packages (they were unlimited when unrecorded)
        msgs = []
        with self.p.lock:
            if ev:
                self.part('alinan_' + ev, ev).setdefault('entries', []).append(loot)
            elif loot in RL_PKG or loot in SP_PKG:
                self.st.setdefault('one_time', []).append(loot)
            else:
                return []
            self.p.dirty = True
        if loot in MM_COIN and CAL.is_active(MM['calendar']):
            msgs.append(self.mm_info())
        if loot in VIP_PKG and CAL.is_active(VIP['calendar']):
            msgs += [('VIPMerchantExchangePackageUpdateCommand', {'packagesBought': self.vip_bought()}), self.vip_info()]
        if loot in PB_PKG:
            msgs.append(self.pb_info())
        self.log('   shop: %s bought' % loot)
        return msgs

    # ------------------------------------------------------------ Mileage Market
    def mm_coins(self):
        return INV.count(self.p, MM['token'])

    def mm_price(self, r, steps):
        return int((1 - steps * MM['step_percent'] / 100.0) * r['uridium'])

    def mm_module(self, r):
        st = self.part('mileage', MM['calendar'])
        steps = st.get('discount', {}).get(r['id'], 0)
        # the client (MileageMarketVo) reads the price from the first number in the text and fills %PRICE% with the old/discounted value; with a plain '40000 U.' the
        # discounted text also stayed 40000: TMP's invisible <link> carries the number (live Ö7: '40000 U. -> 30000 U.')
        return mod('MileageMarketPackageModule', packagePrice='<link=%d>%%PRICE%% U.</link>' % r['uridium'],
                   isBought=r['id'] in st.get('claimed', []),
                   imageKey=r['id'], maxDiscountSteps=MM['max_steps'], claimedDiscountSteps=steps, packageId=r['id'],
                   discountPerStep=float(MM['step_percent']), priority=int(r.get('priority', 0)))

    def mm_info(self):
        return ('MileageMarketInfoCommand', dict(coinCount=self.mm_coins(), exchangePackages=[self.mm_module(r) for r in MM['discount_packages']],
                                                 packageList=[r['id'] for r in MM['token_packages']],
                                                 timeToEventEnd=float(CAL.time_left(MM['calendar']))))

    def mm_exchange(self, f):
        pid, steps = str(f.get('packageId') or ''), int(f.get('claimedDiscountSteps') or 0)
        st = self.part('mileage', MM['calendar'])
        r = MM_DISC.get(pid)
        if not r or not 1 <= steps <= min(MM['max_steps'], self.mm_coins()) or st.get('discount', {}).get(pid) or \
                pid in st.get('claimed', []) or INV.spend(self.p, {MM['token']: steps}, 'buy_SPECIAL', 'mileage') is None:
            return [('MileageMarketInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('discount', {})[pid] = steps
            self.p.dirty = True
        self.log('   Mileage Market: %s: %d tokens (%%%d)' % (pid, steps, steps * MM['step_percent']))
        return [('MileageMarketPackageUpdateCommand', dict(isBought=False, claimedDiscountSteps=steps, packageID=pid)),
                ('MileageMarketInfoUpdateCommand', {'coinCount': self.mm_coins()}), self.mm_info()] \
            + INV.update_msgs(self.m, self.p, [MM['token']])

    def mm_buy(self, f):
        pid = str(f.get('packageId') or '')
        st = self.part('mileage', MM['calendar'])
        r = MM_DISC.get(pid)
        steps = st.get('discount', {}).get(pid, 0)
        if not r or not steps or pid in st.get('claimed', []):
            return [('MileageMarketInsufficientResourcesCommand', {})]
        cost = self.mm_price(r, steps)
        if INV.spend(self.p, {'currency_uridium': cost}, 'buy_SPECIAL', 'mileage') is None:
            return [('MileageMarketInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('claimed', []).append(pid)
            self.p.dirty = True
        msgs = []
        for loot, n in r['contents']:
            msgs += self.m.reward(loot, n) if self.m else []
        self.log('   Mileage Market: %s %d U (%%%d discount)' % (pid, cost, steps * MM['step_percent']))
        return msgs + [('MileageMarketPackageUpdateCommand', dict(isBought=True, claimedDiscountSteps=steps, packageID=pid)),
                       self.mm_info()] + self.money()

    def mm_expire(self):
        """Event over: the tokens are deleted (FAQ)."""
        n = INV.count(self.p, MM['token'])
        if n and not CAL.is_active(MM['calendar']):
            INV.spend(self.p, {MM['token']: n}, 'buy_SPECIAL', 'mileage_ended')
            self.log('   Mileage Market ended: %d tokens deleted' % n)

    # ------------------------------------------------------------ VIP Merchant Exchange
    def vip_bought(self):
        return len(self.part('alinan_' + VIP['calendar'], VIP['calendar']).get('entries', []))

    def vip_row(self, r, st):
        own = lambda loot: float(INV.count(self.p, loot))
        rl, rn = r['reward']
        return mod('VIPMerchantExchangeModule', claimLimit=int(r['cap']), priority=int(r['order']), isSpecial=bool(r['special']),
                   reward=mod('VIPMerchantExchangeItemModule', amount=int(rn), lootId=rl, amountOwned=own(rl)),
                   costs=[mod('VIPMerchantExchangeItemModule', amount=int(n), lootId=l, amountOwned=own(l)) for l, n in r['charge']],
                   claimCount=int(st.get('exchange', {}).get(rl, 0)))

    def vip_info(self):
        st = self.part('vip', VIP['calendar'])
        return ('VIPMerchantExchangeInfoCommand', dict(timeToEventEnd=float(CAL.time_left(VIP['calendar'])), packagesBought=self.vip_bought(),
                                                       exchangeList=[self.vip_row(r, st) for r in VIP['exchange']],
                                                       packageList=[r['id'] for r in VIP['packages']]))

    def vip_exchange(self, f):
        loot = str(f.get('lootId') or '')
        st = self.part('vip', VIP['calendar'])
        r = next((x for x in VIP['exchange'] if x['reward'][0] == loot), None)
        done = st.get('exchange', {}).get(loot, 0)
        if not r or not self.vip_bought() or (r['cap'] > 0 and done >= r['cap']) or \
                INV.spend(self.p, {l: n for l, n in r['charge']}, 'buy_SPECIAL', 'vip_exchange') is None:
            return [('VIPMerchantExchangeInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('exchange', {})[loot] = done + 1
            self.p.dirty = True
        msgs = self.m.reward(loot, r['reward'][1]) if self.m else []
        self.log('   VIP exchange: %s x%d (%s)' % (loot, r['reward'][1], r['charge']))
        return msgs + INV.update_msgs(self.m, self.p, [l for l, n in r['charge']]) + self.money() + [self.vip_info()]

    # ------------------------------------------------------------ Returnee Login
    def returnee_state(self):
        return self.st.setdefault('returnee', {})

    def returnee_check(self, last_seen, now=None):
        """On login: if the last session is older than wait_days (and repeat_days have passed since the last campaign), the campaign starts."""
        now = time.time() if now is None else now
        st = self.returnee_state()
        if st.get('start') and not st.get('off') and now < st['start'] + RL['duration_days'] * DAY:
            return False
        last = st.get('last_campaign', 0)
        if last_seen and now - last_seen >= RL['wait_days'] * DAY and now - last >= RL['repeat_days'] * DAY and \
                self.p.d['pilot'].get('level', 1) >= RL['min_level']:
            self.returnee_start(now)
            return True
        return False

    def returnee_start(self, now=None):
        now = time.time() if now is None else now
        with self.p.lock:
            self.st['returnee'] = dict(start=now, welcome=False, day=0, last_day='', off=False, last_campaign=now)
            self.st['one_time'] = [x for x in self.st.get('one_time', []) if x not in RL_PKG]
            self.p.dirty = True
        self.log('   Returnee Login: campaign started (%d days)' % RL['duration_days'])

    def returnee_active(self, now=None):
        st = self.returnee_state()
        now = time.time() if now is None else now
        return bool(st.get('start')) and not st.get('off') and now < st['start'] + RL['duration_days'] * DAY

    def returnee_left(self, now=None):
        now = time.time() if now is None else now
        return max(0.0, self.returnee_state().get('start', 0) + RL['duration_days'] * DAY - now)

    def returnee_claimable(self, now=None):
        st = self.returnee_state()
        return st.get('day', 0) < min(RL['calendar_days'], len(RL['calendar_reward'])) and st.get('last_day') != today(now).isoformat()

    def returnee_msgs(self, now=None):
        st = self.returnee_state()
        items = lambda rows: [mod('ReturneeLoginItemRewardModule', amount=int(n), lootId=l) for l, n in rows]
        left = float(self.returnee_left(now))
        return [('ReturneeLoginInitialRewardInfoCommand', dict(rewardList=items(RL['welcome']), isClaimable=not st.get('welcome'))),
                ('ReturneeLoginRewardInfoCommand', dict(daysClaimed=int(st.get('day', 0)), rewardList=items(RL['calendar_reward'][:RL['calendar_days']]),
                                                        timeToEndEvent=left, isClaimable=self.returnee_claimable(now))),
                ('ReturneeLoginBundleInfoCommand', dict(timeToEndEvent=left))]

    def returnee_claim(self, f):
        st = self.returnee_state()
        if not self.returnee_active():
            return []
        msgs = []
        if not f.get('isClaimDaily'):
            if st.get('welcome'):
                return []
            with self.p.lock:
                st['welcome'] = True
                self.p.dirty = True
            for l, n in RL['welcome']:
                msgs += self.m.reward(l, n) if self.m else []
            return msgs + [('ReturneeLoginInitialRewardClaimableInfoCommand', {'isClaimable': False})] + self.money()
        if not self.returnee_claimable():
            return []
        l, n = RL['calendar_reward'][st.get('day', 0)]
        with self.p.lock:
            st['day'] = st.get('day', 0) + 1
            st['last_day'] = today().isoformat()
            self.p.dirty = True
        msgs += self.m.reward(l, n) if self.m else []
        self.log('   Returnee Login: day %d %s x%d' % (st['day'], l, n))
        return msgs + [('ReturneeLoginRewardDayInfoCommand', dict(daysClaimed=int(st['day']), isClaimable=False))] + self.money()

    def returnee_hide(self):
        st = self.returnee_state()
        if st.get('start') and self.returnee_left() < 1:
            with self.p.lock:
                st['off'] = True
                self.p.dirty = True
        return self.window_item('returnee_login', self.returnee_active())

    # ------------------------------------------------------------ Pre-Prometheus Day
    def pb_bought(self):
        return len(set(self.part('alinan_' + PB['calendar'], PB['calendar']).get('entries', [])))

    def pb_info(self):
        return ('PreBlackFridaySalesInfoCommand', {'packBought': min(5, self.pb_bought())})

    # ------------------------------------------------------------ Return of Hero
    def rh(self):
        return self.part('rehero', CT['calendar'])

    def rh_day(self, now=None):
        st = self.rh()
        if not st.get('start'):
            with self.p.lock:
                st['start'] = today(now).isoformat()
                self.p.dirty = True
        return (today(now) - datetime.date.fromisoformat(st['start'])).days

    def rh_quests(self, now=None):
        """(non-repeating, today's dailies): the first 13 quests are non-repeating, 5 a day from the remaining pool (with the day's seed)."""
        qs = CT['quests']
        once = qs[:CT['once_count']]
        pool = qs[CT['once_count']:] or qs
        d = self.rh_day(now)
        st = self.rh()
        if st.get('day_number') != d:          # new day: the daily pool's done/progress is reset (otherwise a quest that comes up again looks finished)
            pool_ids = {q['id'] for q in pool if q not in once}
            with self.p.lock:
                st['done'] = [i for i in st.get('done', []) if i not in pool_ids]
                for i in pool_ids:
                    st.get('value', {}).pop(str(i), None)
                st['day_number'] = d
                self.p.dirty = True
        if d >= CT['day']:
            return once, []
        rnd = random.Random('%s-%d' % (self.rh().get('start'), d))
        return once, rnd.sample(pool, min(CT['daily_count'], len(pool)))

    def rh_quest_module(self, q, st):
        done = q['id'] in st.get('done', [])
        return mod('EventQuestDefinitionModule', module=GT.with_state(q, st.get('value', {}).get(str(q['id']), {}), done),
                   completed=done, claimed=done)

    def rh_cmd(self, rtype=1, error=None, now=None):
        st = self.rh()
        once, daily = self.rh_quests(now)
        bound = bool(st.get('connected'))
        tomorrow = datetime.datetime.combine(today(now) + datetime.timedelta(days=1), datetime.time()).timestamp()
        nows = time.time() if now is None else now
        from shop import stack_msg
        return ('EventReturnOfHeroActionCommand', dict(
            btnEnable=True, returnType=int(rtype), errorMessage=error if isinstance(error, dict) else stack_msg(error or 'empty'),
            inviterName=st.get('veteran', '') if bound else '', bootKeyLootId=CT['key'], inviterId=int(st.get('code', 0)),
            eventReturnOfHeroQuestCommand=mod('EventReturnOfHeroQuestCommand', dailyNextRefreshSecond=int(max(0, tomorrow - nows)),
                                              dailyQuests=[self.rh_quest_module(q, st) for q in daily],
                                              noRepeatNextRefreshSecond=int(CAL.time_left(CT['calendar'])),
                                              noRepeatQuests=[self.rh_quest_module(q, st) for q in once]),
            eventReturnOfHeroContributorListCommand=mod('EventReturnOfHeroContributorListCommand', contributorList=[]),
            activityStatus=4 if bound else 2, bootKeyAmount=float(INV.count(self.p, CT['key']))))

    def rh_exchange_info(self):
        st = self.rh()
        rows = [dict(r, claimCount=int(st.get('exchange', {}).get(r['exchangeReward'], 0))) for r in CT['exchange']]
        return ('BattlePassKeyExchangeInfoCommand', dict(rewardList=rows, numOfKeys=int(INV.count(self.p, CT['key'])), exchangeType=2))

    def rh_action(self, f):
        if not CAL.is_active(CT['calendar']):
            return []
        act = int(f.get('actionType') or 0)
        st = self.rh()
        if act == 0:
            return [self.rh_cmd(1), self.rh_exchange_info()]
        if act == 1:
            if st.get('connected'):
                return [self.rh_cmd(0, 'empty')]
            if time.time() - st.get('first_login', time.time()) > CT['link_duration_sec']:     # FAQ: within 24 hours of login
                return [self.rh_cmd(0, self.m.reason('rh_bond_duration'))]
            with self.p.lock:
                st.update(connected=True, code=int(f.get('id') or 0), veteran=random.choice(CT['veteran_names']))
                self.p.dirty = True
            self.log('   Return of Hero: %s tied to a veteran' % st['veteran'])
            return [self.rh_cmd(2)]
        if act == 2:
            key = str(f.get('exchange') or '')
            r = RH_X.get(key)
            done = st.get('exchange', {}).get(key, 0)
            if not r or done >= r['limit'] or INV.spend(self.p, {CT['key']: r['cost']}, 'buy_SPECIAL', 'return_of_hero') is None:
                return [self.rh_cmd(0, 'captain_hangar_error_not_enough_resources')]
            with self.p.lock:
                st.setdefault('exchange', {})[key] = done + 1
                self.p.dirty = True
            msgs = []
            for x in r['listOfloot']:
                msgs += self.m.reward(x['lootId'], x['amount']) if self.m else []
            self.log('   Return of Hero exchange: %s (%d keys)' % (key, r['cost']))
            return msgs + [('BattlePassKeyExchangeUpdateCommand', dict(spcId=0, numOfKeys=int(INV.count(self.p, CT['key'])),
                                                                       claimCount=done + 1, exchangeReward=key, lootId=CT['key'])),
                           self.rh_cmd(1), self.rh_exchange_info()]
        return []

    def event(self, kind, kw):
        """Quest events (the session's quest events): Return of Hero quests progress; a finished quest gives a key."""
        if not CAL.is_active(CT['calendar']) or not self.rh().get('connected'):
            return []
        st = self.rh()
        once, daily = self.rh_quests()
        msgs = []
        for q in once + daily:
            if q['id'] in st.get('done', []):
                continue
            m, fin = GT.advance(self.p, q['rootCase'], st.setdefault('value', {}).setdefault(str(q['id']), {}), kind, kw, self.map_id)
            msgs += m
            if fin:
                n = CT['key_reward']['once' if q in once else 'daily']
                with self.p.lock:
                    st.setdefault('done', []).append(q['id'])
                    self.p.dirty = True
                self.p.add_resource(CT['key'], n)
                msgs.append(('EventQuestCompletedCommand', dict(eventType='ReturnOfHero', repeatableType='DAILY' if q in daily else 'NONE')))
                msgs += INV.update_msgs(self.m, self.p, [CT['key']])
                self.log('   Return of Hero quest finished: %d (+%d keys)' % (q['id'], n))
        if any(n == 'EventQuestCompletedCommand' for n, f in msgs):
            msgs += [self.rh_cmd(1), self.rh_exchange_info()]       # the key count of the exchange rows (refreshed when the tab opens)
        return msgs

    # ------------------------------------------------------------ the Ö3 container's face
    def attach(self, world):
        self.map_id = world.map_id
        return []

    def tick(self, now):
        if now - self.st.get('last_session', 0) >= 60:          # the session's last moment (the next login's yardstick for Returnee)
            with self.p.lock:
                self.st['last_session'] = now
                self.p.dirty = True
        return []

    def window_item(self, item_id, visible):
        it = self.p.window_item(item_id) if hasattr(self.p, 'window_item') else None
        return [('WindowItemCommand', dict(it, visible=bool(visible), maximized=False))] if it else []

    def login_msgs(self):
        self.mm_expire()
        msgs = []
        if CAL.is_active(MM['calendar']):
            msgs.append(self.mm_info())
        if CAL.is_active(VIP['calendar']):
            msgs.append(self.vip_info())
        if self.returnee_active():
            msgs += self.returnee_msgs()
        if CAL.is_active(PB['calendar']):
            msgs.append(self.pb_info())
        return msgs

    def window(self, item):
        if item == 'preBlackFridaySales':
            return [self.pb_info()]
        return None

    def handles(self, name):
        return name in self.REQUESTS

    def handle(self, name, f):
        if name == 'MileageMarketEventBuyRequest':
            return [PAY.open_shop(), self.info_msg('Mileage Packs: Shop > Extras (uridium).')]
        if name == 'MileageMarketExchangeRequest':
            return self.mm_exchange(f)
        if name == 'MileageMarketPackageBuyRequest':
            return self.mm_buy(f)
        if name == 'VIPMerchantExchangeBuyRequest':
            return [PAY.open_shop(), self.info_msg('VIP Merchant Packs: Shop > Extras (uridium).')]
        if name == 'VIPMerchantExchangeRequest':
            return self.vip_exchange(f)
        if name == 'ReturneeLoginRewardClaimRequest':
            return self.returnee_claim(f)
        if name == 'ReturneeLoginBundleBuyRequest':
            return [PAY.open_shop(), self.info_msg('Returnee Bundles: Shop > Extras (uridium).')]
        if name == 'ReturneeLoginHideUIItemRequest':
            return self.returnee_hide()
        if name in ('EventReturnOfHeroActionRequest', 'EventANewHopeActionRequest'):
            return self.rh_action(f)
        return []

    @staticmethod
    def info_msg(text):
        import galaxy_gates as KAPI
        return KAPI.screen(text)
