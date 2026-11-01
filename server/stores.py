"""Uridyumla çalışan dükkân pencereleri (yol haritası Ö7; veri data/stores.json <- tools/stores_o7.py, kaynak
belgeler/wiki/dukkanlar_o7.json). Ö3'ün kabında (ek_etkinlikler.add). Ödeme sayfasını açan *BuyCommand'ler (MileageMarketBuyCommand,
VIPMerchantExchangeBuyCommand, ReturneeLoginBundleBuyCommand) hiç gönderilmez; pencerelerin "Buy now" düğmeleri (hangi paket olduğu
istekte yok, onay sorusu yok) mağazayı Extras'ta açar ve bilgi verir (odeme.open_shop): paketler orada uridyumla, etkinlik
süresince birer kez.

  Mileage Market (takvim mileage_market): jeton paketleri mağazada (Mileage Coin verir); penceredeki indirim paketlerine jeton başına
      %5 (en çok 5 jeton = %25) bir kez uygulanır, sonra indirimli fiyatla uridyumla alınır (MileageMarketExchangeRequest ->
      MileageMarketPackageBuyRequest). Etkinlik bitince jetonlar silinir.
  VIP Merchant Exchange (vip_merchant): mağazadaki VIP paketlerinden biri alınınca VIP; takas satırları (oyun içi kaynak + uridyum /
      kredi) VIP'e açık, satır başına sınır.
  Returnee Login: kayıtta son oturum 14 günden (ve son kampanyadan 60 günden) eskiyse girişte 15 günlük kampanya: hoş geldin ödülü,
      7 günlük giriş takvimi, dönüş paketleri mağazada. Süre bitince istemcinin gizleme isteği kampanyayı kapatır.
  Pre-Prometheus Day Sales (pre_prometheus): alınan farklı Pre-BF paketi sayısı (yalnız bilgi penceresi).
  Return of Hero (return_of_hero): dönen oyuncu (TRUE / INVITEE); herhangi bir kod sanal bir veterana bağlar, yalnız etkinlikteki ilk
      girişten 24 saat içinde (SSS); 13 tekrarsız ve günde 5 görev (Season Pass havuzundan) Returnee Key verir; Exchange sekmesinde
      anahtarla takas (BattlePassKeyExchange*, exchangeType 2; liste SSS'ninki).
  Stellar Pathfinder: paketler mağazada seviye 5'ten başlayarak hesap başına bir kez (pencerenin _claim düğmesi istemci içi: karşılığı
      yok). Oyunda 5-14; tek oyunculuda Solaris'in tek yolu olduğu için üst sınır yok (EP çarpanıyla aralık hızla geçiliyor).
Profilde 'dukkanlar': mileage {donem, indirim {package: adım}, alinan []}, vip {donem, paket, takas {ödül: n}}, returnee {baslangic,
  hosgeldin, gun, son_gun, kapali, son_kampanya}, pre_bf {donem, alinan []}, rehero {donem, ilk_giris, bagli, veteran, deger, tamam,
  alinan, gun_gorevleri, takas}, tek_sefer [paket].
"""
import datetime, json, os, random, time

import inventory as INV
import quest_tracker as GT
import payment as PAY
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'stores.json'), encoding='utf8'))
MM, VIP, RL, PB, CT, SP = D['mileage'], D['vip'], D['returnee'], D['pre_bf'], D['rehero'], D['stellar']
_PRICE = json.load(open(os.path.join(HERE, 'data', 'prices.json'), encoding='utf8'))['prices']     # market dengesi
for _r in MM['discount_packages']:                 # indirim paketleri yalnız pencerede: fiyatları dengeden
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
        shop.shop_gate = self.shop_gate          # mağazada görünürlük (etkinlik / bir kez / seviye)
        shop.on_bought.append(self.bought)
        self.prev_seen = self.st.get('last_session') # önceki oturumun son anı (Returnee Login; tick yazar)
        self.returnee_check(self.prev_seen)
        if CAL.is_active(CT['calendar']) and 'first_login' not in self.rh():
            with self.p.lock:                      # Return of Hero'daki ilk giriş: veterana bağlanma süresi buradan
                self.rh()['first_login'] = time.time()
                self.p.dirty = True

    @property
    def st(self):
        return self.p.d.setdefault('stores', {})

    def part(self, key, event=None):
        """Etkinliğe bağlı bölüm: dönem değişince sıfırlanır."""
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

    # ------------------------------------------------------------ mağaza kancaları
    def shop_gate(self, entry, loot):
        """ek_magaza satırı şimdi satılır mı (takvim / kampanya, bir kez, Stellar'ın seviyesi)."""
        ev = entry.get('calendar') if entry else None
        if ev == 'returnee':
            if not self.returnee_active():
                return False
        elif ev and not CAL.is_active(ev):
            return False
        if loot in SP_PKG:
            lv, (lo, hi) = self.p.d['pilot'].get('level', 1), SP['level']     # hi None: üst sınır yok
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
        """Mağazadan alım (magaza.on_bought): bir kezlikler, VIP, Pre-BF sayaçları -> mesajlar."""
        ev = next((e for s, e in ((MM_COIN, 'mileage_market'), (VIP_PKG, 'vip_merchant'), (PB_PKG, 'pre_prometheus')) if loot in s), None)
        entry = self.m.extra_entry.get(loot) or {}
        if not ev and entry.get('once') and entry.get('calendar') not in (None, 'returnee'):
            ev = entry['calendar']     # Return of Hero'nun bir kezlik VIP rozet paketleri (kayıtsız kalınca sınırsız alınıyordu)
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
        self.log('   dükkân: %s alındı' % loot)
        return msgs

    # ------------------------------------------------------------ Mileage Market
    def mm_coins(self):
        return INV.count(self.p, MM['token'])

    def mm_price(self, r, steps):
        return int((1 - steps * MM['step_percent'] / 100.0) * r['uridium'])

    def mm_module(self, r):
        st = self.part('mileage', MM['calendar'])
        steps = st.get('discount', {}).get(r['id'], 0)
        # istemci (MileageMarketVo) fiyatı metindeki ilk sayıdan okur, %PRICE%'i eski/indirimli değerle doldurur; düz '40000 U.' ile
        # indirimli metin de 40000 kalıyordu: TMP'nin görünmez <link>'i sayıyı taşır (canlı Ö7: '40000 U. -> 30000 U.')
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
        self.log('   Mileage Market: %s için %d jeton (%%%d)' % (pid, steps, steps * MM['step_percent']))
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
        self.log('   Mileage Market: %s %d U (%%%d indirim)' % (pid, cost, steps * MM['step_percent']))
        return msgs + [('MileageMarketPackageUpdateCommand', dict(isBought=True, claimedDiscountSteps=steps, packageID=pid)),
                       self.mm_info()] + self.money()

    def mm_expire(self):
        """Etkinlik bitti: jetonlar silinir (FAQ)."""
        n = INV.count(self.p, MM['token'])
        if n and not CAL.is_active(MM['calendar']):
            INV.spend(self.p, {MM['token']: n}, 'buy_SPECIAL', 'mileage_ended')
            self.log('   Mileage Market bitti: %d jeton silindi' % n)

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
        self.log('   VIP takas: %s x%d (%s)' % (loot, r['reward'][1], r['charge']))
        return msgs + INV.update_msgs(self.m, self.p, [l for l, n in r['charge']]) + self.money() + [self.vip_info()]

    # ------------------------------------------------------------ Returnee Login
    def returnee_state(self):
        return self.st.setdefault('returnee', {})

    def returnee_check(self, last_seen, now=None):
        """Girişte: son oturum bekleme_gun'den eskiyse (ve son kampanyadan tekrar_gun geçtiyse) kampanya başlar."""
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
        self.log('   Returnee Login: kampanya başladı (%d gün)' % RL['duration_days'])

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
        self.log('   Returnee Login: %d. gün %s x%d' % (st['day'], l, n))
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
        """(tekrarsız, bugünün günlükleri): ilk 13 görev tekrarsız, kalan havuzdan gün başına 5 (gün tohumuyla)."""
        qs = CT['quests']
        once = qs[:CT['once_count']]
        pool = qs[CT['once_count']:] or qs
        d = self.rh_day(now)
        st = self.rh()
        if st.get('day_number') != d:          # yeni gün: günlük havuzun tamam/ilerlemesi sıfırlanır (yoksa yeniden çıkan görev bitmiş görünür)
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
            inviterName=st.get('veteran', '') if bound else '', bootKeyLootId=CT['anahtar'], inviterId=int(st.get('code', 0)),
            eventReturnOfHeroQuestCommand=mod('EventReturnOfHeroQuestCommand', dailyNextRefreshSecond=int(max(0, tomorrow - nows)),
                                              dailyQuests=[self.rh_quest_module(q, st) for q in daily],
                                              noRepeatNextRefreshSecond=int(CAL.time_left(CT['calendar'])),
                                              noRepeatQuests=[self.rh_quest_module(q, st) for q in once]),
            eventReturnOfHeroContributorListCommand=mod('EventReturnOfHeroContributorListCommand', contributorList=[]),
            activityStatus=4 if bound else 2, bootKeyAmount=float(INV.count(self.p, CT['anahtar']))))

    def rh_exchange_info(self):
        st = self.rh()
        rows = [dict(r, claimCount=int(st.get('exchange', {}).get(r['exchangeReward'], 0))) for r in CT['exchange']]
        return ('BattlePassKeyExchangeInfoCommand', dict(rewardList=rows, numOfKeys=int(INV.count(self.p, CT['anahtar'])), exchangeType=2))

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
            if time.time() - st.get('first_login', time.time()) > CT['link_duration_sec']:     # SSS: girişten 24 saat içinde
                return [self.rh_cmd(0, self.m.reason('rh_bond_duration'))]
            with self.p.lock:
                st.update(connected=True, code=int(f.get('id') or 0), veteran=random.choice(CT['veteran_names']))
                self.p.dirty = True
            self.log('   Return of Hero: %s veterana bağlandı' % st['veteran'])
            return [self.rh_cmd(2)]
        if act == 2:
            key = str(f.get('exchange') or '')
            r = RH_X.get(key)
            done = st.get('exchange', {}).get(key, 0)
            if not r or done >= r['limit'] or INV.spend(self.p, {CT['anahtar']: r['cost']}, 'buy_SPECIAL', 'return_of_hero') is None:
                return [self.rh_cmd(0, 'captain_hangar_error_not_enough_resources')]
            with self.p.lock:
                st.setdefault('exchange', {})[key] = done + 1
                self.p.dirty = True
            msgs = []
            for x in r['listOfloot']:
                msgs += self.m.reward(x['lootId'], x['amount']) if self.m else []
            self.log('   Return of Hero takas: %s (%d anahtar)' % (key, r['cost']))
            return msgs + [('BattlePassKeyExchangeUpdateCommand', dict(spcId=0, numOfKeys=int(INV.count(self.p, CT['anahtar'])),
                                                                       claimCount=done + 1, exchangeReward=key, lootId=CT['anahtar'])),
                           self.rh_cmd(1), self.rh_exchange_info()]
        return []

    def event(self, kind, kw):
        """Görev olayları (oturumun quest olayları): Return of Hero görevleri ilerler; biten görev anahtar verir."""
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
                self.p.add_resource(CT['anahtar'], n)
                msgs.append(('EventQuestCompletedCommand', dict(eventType='ReturnOfHero', repeatableType='DAILY' if q in daily else 'NONE')))
                msgs += INV.update_msgs(self.m, self.p, [CT['anahtar']])
                self.log('   Return of Hero görevi bitti: %d (+%d anahtar)' % (q['id'], n))
        if any(n == 'EventQuestCompletedCommand' for n, f in msgs):
            msgs += [self.rh_cmd(1), self.rh_exchange_info()]       # takas satırlarının anahtar sayısı (sekme açılınca yenilenir)
        return msgs

    # ------------------------------------------------------------ Ö3 kabının yüzü
    def attach(self, world):
        self.map_id = world.map_id
        return []

    def tick(self, now):
        if now - self.st.get('last_session', 0) >= 60:          # oturumun son anı (bir sonraki girişte Returnee'nin ölçüsü)
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
