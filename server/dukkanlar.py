"""Uridyumla çalışan dükkân pencereleri (yol haritası Ö7; veri data/dukkanlar.json <- tools/dukkanlar_o7.py, kaynak
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
Profilde 'dukkanlar': mileage {donem, indirim {paket: adım}, alinan []}, vip {donem, paket, takas {ödül: n}}, returnee {baslangic,
  hosgeldin, gun, son_gun, kapali, son_kampanya}, pre_bf {donem, alinan []}, rehero {donem, ilk_giris, bagli, veteran, deger, tamam,
  alinan, gun_gorevleri, takas}, tek_sefer [paket].
"""
import datetime, json, os, random, time

import envanter as INV
import gorev_takip as GT
import odeme as OD
import takvim as TK

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'dukkanlar.json'), encoding='utf8'))
MM, VIP, RL, PB, RH, SP = D['mileage'], D['vip'], D['returnee'], D['pre_bf'], D['rehero'], D['stellar']
_FIYAT = json.load(open(os.path.join(HERE, 'data', 'fiyatlar.json'), encoding='utf8'))['fiyatlar']     # market dengesi
for _r in MM['indirim_paketleri']:                 # indirim paketleri yalnız pencerede: fiyatları dengeden
    if _FIYAT.get(_r['lootId'], {}).get('para') == 'U':
        _r['uridyum'] = _FIYAT[_r['lootId']]['fiyat']
MM_COIN = {r['lootId'] for r in MM['jeton_paketleri']}
MM_DISC = {r['id']: r for r in MM['indirim_paketleri']}
VIP_PKG = {r['lootId'] for r in VIP['paketler']}
RL_PKG = {r['lootId'] for r in RL['paketler']}
PB_PKG = {r['lootId'] for r in PB['paketler']}
SP_PKG = {r['lootId'] for r in SP['paketler']}
RH_Q = {q['id']: q for q in RH['gorevler']}
RH_X = {r['exchangeReward']: r for r in RH['takas']}
DAY = 86400


def mod(_cls, **f):
    f['_'] = _cls
    return f


def today(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now)


class Dukkanlar:
    REQUESTS = ('MileageMarketEventBuyRequest', 'MileageMarketExchangeRequest', 'MileageMarketPackageBuyRequest',
                'VIPMerchantExchangeBuyRequest', 'VIPMerchantExchangeRequest',
                'ReturneeLoginRewardClaimRequest', 'ReturneeLoginBundleBuyRequest', 'ReturneeLoginHideUIItemRequest',
                'EventReturnOfHeroActionRequest', 'EventANewHopeActionRequest')

    def __init__(self, profil, magaza, log=print):
        self.p, self.m, self.log = profil, magaza, log
        self.send = None
        self.map_id = None
        magaza.shop_gate = self.shop_gate          # mağazada görünürlük (etkinlik / bir kez / seviye)
        magaza.on_bought.append(self.bought)
        self.prev_seen = self.st.get('son_oturum') # önceki oturumun son anı (Returnee Login; tick yazar)
        self.returnee_check(self.prev_seen)
        if TK.is_active(RH['takvim']) and 'ilk_giris' not in self.rh():
            with self.p.lock:                      # Return of Hero'daki ilk giriş: veterana bağlanma süresi buradan
                self.rh()['ilk_giris'] = time.time()
                self.p.dirty = True

    @property
    def st(self):
        return self.p.d.setdefault('dukkanlar', {})

    def part(self, key, event=None):
        """Etkinliğe bağlı bölüm: dönem değişince sıfırlanır."""
        st = self.st.setdefault(key, {})
        if event:
            per = TK.period(event)
            tag = per and str(int(per[0])) or ('acik' if TK.is_active(event) else '')
            if st.get('donem') != tag:
                st.clear()
                st['donem'] = tag
                self.p.dirty = True
        return st

    def money(self):
        return self.m.money_msgs() if self.m else []

    # ------------------------------------------------------------ mağaza kancaları
    def shop_gate(self, entry, loot):
        """ek_magaza satırı şimdi satılır mı (takvim / kampanya, bir kez, Stellar'ın seviyesi)."""
        ev = entry.get('takvim') if entry else None
        if ev == 'returnee':
            if not self.returnee_active():
                return False
        elif ev and not TK.is_active(ev):
            return False
        if loot in SP_PKG:
            lv, (lo, hi) = self.p.d['pilot'].get('level', 1), SP['seviye']     # hi None: üst sınır yok
            if lv < lo or (hi is not None and lv > hi):
                return False
        if (entry and entry.get('bir_kez')) or loot in SP_PKG:
            return loot not in self.bought_set(ev)
        return True

    def bought_set(self, ev):
        if ev and ev != 'returnee':
            return set(self.part('alinan_' + ev, ev).get('liste', []))
        return set(self.st.get('tek_sefer', []))

    def bought(self, loot, amount):
        """Mağazadan alım (magaza.on_bought): bir kezlikler, VIP, Pre-BF sayaçları -> mesajlar."""
        ev = next((e for s, e in ((MM_COIN, 'mileage_market'), (VIP_PKG, 'vip_merchant'), (PB_PKG, 'pre_prometheus')) if loot in s), None)
        entry = self.m.extra_entry.get(loot) or {}
        if not ev and entry.get('bir_kez') and entry.get('takvim') not in (None, 'returnee'):
            ev = entry['takvim']     # Return of Hero'nun bir kezlik VIP rozet paketleri (kayıtsız kalınca sınırsız alınıyordu)
        msgs = []
        with self.p.lock:
            if ev:
                self.part('alinan_' + ev, ev).setdefault('liste', []).append(loot)
            elif loot in RL_PKG or loot in SP_PKG:
                self.st.setdefault('tek_sefer', []).append(loot)
            else:
                return []
            self.p.dirty = True
        if loot in MM_COIN and TK.is_active(MM['takvim']):
            msgs.append(self.mm_info())
        if loot in VIP_PKG and TK.is_active(VIP['takvim']):
            msgs += [('VIPMerchantExchangePackageUpdateCommand', {'packagesBought': self.vip_bought()}), self.vip_info()]
        if loot in PB_PKG:
            msgs.append(self.pb_info())
        self.log('   dükkân: %s alındı' % loot)
        return msgs

    # ------------------------------------------------------------ Mileage Market
    def mm_coins(self):
        return INV.count(self.p, MM['jeton'])

    def mm_price(self, r, steps):
        return int((1 - steps * MM['adim_yuzde'] / 100.0) * r['uridyum'])

    def mm_module(self, r):
        st = self.part('mileage', MM['takvim'])
        steps = st.get('indirim', {}).get(r['id'], 0)
        # istemci (MileageMarketVo) fiyatı metindeki ilk sayıdan okur, %PRICE%'i eski/indirimli değerle doldurur; düz '40000 U.' ile
        # indirimli metin de 40000 kalıyordu: TMP'nin görünmez <link>'i sayıyı taşır (canlı Ö7: '40000 U. -> 30000 U.')
        return mod('MileageMarketPackageModule', packagePrice='<link=%d>%%PRICE%% U.</link>' % r['uridyum'],
                   isBought=r['id'] in st.get('alinan', []),
                   imageKey=r['id'], maxDiscountSteps=MM['azami_adim'], claimedDiscountSteps=steps, packageId=r['id'],
                   discountPerStep=float(MM['adim_yuzde']), priority=int(r.get('priority', 0)))

    def mm_info(self):
        return ('MileageMarketInfoCommand', dict(coinCount=self.mm_coins(), exchangePackages=[self.mm_module(r) for r in MM['indirim_paketleri']],
                                                 packageList=[r['id'] for r in MM['jeton_paketleri']],
                                                 timeToEventEnd=float(TK.time_left(MM['takvim']))))

    def mm_exchange(self, f):
        pid, steps = str(f.get('packageId') or ''), int(f.get('claimedDiscountSteps') or 0)
        st = self.part('mileage', MM['takvim'])
        r = MM_DISC.get(pid)
        if not r or not 1 <= steps <= min(MM['azami_adim'], self.mm_coins()) or st.get('indirim', {}).get(pid) or \
                pid in st.get('alinan', []) or INV.spend(self.p, {MM['jeton']: steps}, 'buy_SPECIAL', 'mileage') is None:
            return [('MileageMarketInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('indirim', {})[pid] = steps
            self.p.dirty = True
        self.log('   Mileage Market: %s için %d jeton (%%%d)' % (pid, steps, steps * MM['adim_yuzde']))
        return [('MileageMarketPackageUpdateCommand', dict(isBought=False, claimedDiscountSteps=steps, packageID=pid)),
                ('MileageMarketInfoUpdateCommand', {'coinCount': self.mm_coins()}), self.mm_info()] \
            + INV.update_msgs(self.m, self.p, [MM['jeton']])

    def mm_buy(self, f):
        pid = str(f.get('packageId') or '')
        st = self.part('mileage', MM['takvim'])
        r = MM_DISC.get(pid)
        steps = st.get('indirim', {}).get(pid, 0)
        if not r or not steps or pid in st.get('alinan', []):
            return [('MileageMarketInsufficientResourcesCommand', {})]
        cost = self.mm_price(r, steps)
        if INV.spend(self.p, {'currency_uridium': cost}, 'buy_SPECIAL', 'mileage') is None:
            return [('MileageMarketInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('alinan', []).append(pid)
            self.p.dirty = True
        msgs = []
        for loot, n in r['icerik']:
            msgs += self.m.reward(loot, n) if self.m else []
        self.log('   Mileage Market: %s %d U (%%%d indirim)' % (pid, cost, steps * MM['adim_yuzde']))
        return msgs + [('MileageMarketPackageUpdateCommand', dict(isBought=True, claimedDiscountSteps=steps, packageID=pid)),
                       self.mm_info()] + self.money()

    def mm_expire(self):
        """Etkinlik bitti: jetonlar silinir (FAQ)."""
        n = INV.count(self.p, MM['jeton'])
        if n and not TK.is_active(MM['takvim']):
            INV.spend(self.p, {MM['jeton']: n}, 'buy_SPECIAL', 'mileage_bitti')
            self.log('   Mileage Market bitti: %d jeton silindi' % n)

    # ------------------------------------------------------------ VIP Merchant Exchange
    def vip_bought(self):
        return len(self.part('alinan_' + VIP['takvim'], VIP['takvim']).get('liste', []))

    def vip_row(self, r, st):
        own = lambda loot: float(INV.count(self.p, loot))
        rl, rn = r['odul']
        return mod('VIPMerchantExchangeModule', claimLimit=int(r['sinir']), priority=int(r['sira']), isSpecial=bool(r['ozel']),
                   reward=mod('VIPMerchantExchangeItemModule', amount=int(rn), lootId=rl, amountOwned=own(rl)),
                   costs=[mod('VIPMerchantExchangeItemModule', amount=int(n), lootId=l, amountOwned=own(l)) for l, n in r['bedel']],
                   claimCount=int(st.get('takas', {}).get(rl, 0)))

    def vip_info(self):
        st = self.part('vip', VIP['takvim'])
        return ('VIPMerchantExchangeInfoCommand', dict(timeToEventEnd=float(TK.time_left(VIP['takvim'])), packagesBought=self.vip_bought(),
                                                       exchangeList=[self.vip_row(r, st) for r in VIP['takas']],
                                                       packageList=[r['id'] for r in VIP['paketler']]))

    def vip_exchange(self, f):
        loot = str(f.get('lootId') or '')
        st = self.part('vip', VIP['takvim'])
        r = next((x for x in VIP['takas'] if x['odul'][0] == loot), None)
        done = st.get('takas', {}).get(loot, 0)
        if not r or not self.vip_bought() or (r['sinir'] > 0 and done >= r['sinir']) or \
                INV.spend(self.p, {l: n for l, n in r['bedel']}, 'buy_SPECIAL', 'vip_exchange') is None:
            return [('VIPMerchantExchangeInsufficientResourcesCommand', {})]
        with self.p.lock:
            st.setdefault('takas', {})[loot] = done + 1
            self.p.dirty = True
        msgs = self.m.reward(loot, r['odul'][1]) if self.m else []
        self.log('   VIP takas: %s x%d (%s)' % (loot, r['odul'][1], r['bedel']))
        return msgs + INV.update_msgs(self.m, self.p, [l for l, n in r['bedel']]) + self.money() + [self.vip_info()]

    # ------------------------------------------------------------ Returnee Login
    def returnee_state(self):
        return self.st.setdefault('returnee', {})

    def returnee_check(self, last_seen, now=None):
        """Girişte: son oturum bekleme_gun'den eskiyse (ve son kampanyadan tekrar_gun geçtiyse) kampanya başlar."""
        now = time.time() if now is None else now
        st = self.returnee_state()
        if st.get('baslangic') and not st.get('kapali') and now < st['baslangic'] + RL['sure_gun'] * DAY:
            return False
        last = st.get('son_kampanya', 0)
        if last_seen and now - last_seen >= RL['bekleme_gun'] * DAY and now - last >= RL['tekrar_gun'] * DAY and \
                self.p.d['pilot'].get('level', 1) >= RL['en_az_seviye']:
            self.returnee_start(now)
            return True
        return False

    def returnee_start(self, now=None):
        now = time.time() if now is None else now
        with self.p.lock:
            self.st['returnee'] = dict(baslangic=now, hosgeldin=False, gun=0, son_gun='', kapali=False, son_kampanya=now)
            self.st['tek_sefer'] = [x for x in self.st.get('tek_sefer', []) if x not in RL_PKG]
            self.p.dirty = True
        self.log('   Returnee Login: kampanya başladı (%d gün)' % RL['sure_gun'])

    def returnee_active(self, now=None):
        st = self.returnee_state()
        now = time.time() if now is None else now
        return bool(st.get('baslangic')) and not st.get('kapali') and now < st['baslangic'] + RL['sure_gun'] * DAY

    def returnee_left(self, now=None):
        now = time.time() if now is None else now
        return max(0.0, self.returnee_state().get('baslangic', 0) + RL['sure_gun'] * DAY - now)

    def returnee_claimable(self, now=None):
        st = self.returnee_state()
        return st.get('gun', 0) < min(RL['takvim_gun'], len(RL['takvim_odul'])) and st.get('son_gun') != today(now).isoformat()

    def returnee_msgs(self, now=None):
        st = self.returnee_state()
        items = lambda rows: [mod('ReturneeLoginItemRewardModule', amount=int(n), lootId=l) for l, n in rows]
        left = float(self.returnee_left(now))
        return [('ReturneeLoginInitialRewardInfoCommand', dict(rewardList=items(RL['hosgeldin']), isClaimable=not st.get('hosgeldin'))),
                ('ReturneeLoginRewardInfoCommand', dict(daysClaimed=int(st.get('gun', 0)), rewardList=items(RL['takvim_odul'][:RL['takvim_gun']]),
                                                        timeToEndEvent=left, isClaimable=self.returnee_claimable(now))),
                ('ReturneeLoginBundleInfoCommand', dict(timeToEndEvent=left))]

    def returnee_claim(self, f):
        st = self.returnee_state()
        if not self.returnee_active():
            return []
        msgs = []
        if not f.get('isClaimDaily'):
            if st.get('hosgeldin'):
                return []
            with self.p.lock:
                st['hosgeldin'] = True
                self.p.dirty = True
            for l, n in RL['hosgeldin']:
                msgs += self.m.reward(l, n) if self.m else []
            return msgs + [('ReturneeLoginInitialRewardClaimableInfoCommand', {'isClaimable': False})] + self.money()
        if not self.returnee_claimable():
            return []
        l, n = RL['takvim_odul'][st.get('gun', 0)]
        with self.p.lock:
            st['gun'] = st.get('gun', 0) + 1
            st['son_gun'] = today().isoformat()
            self.p.dirty = True
        msgs += self.m.reward(l, n) if self.m else []
        self.log('   Returnee Login: %d. gün %s x%d' % (st['gun'], l, n))
        return msgs + [('ReturneeLoginRewardDayInfoCommand', dict(daysClaimed=int(st['gun']), isClaimable=False))] + self.money()

    def returnee_hide(self):
        st = self.returnee_state()
        if st.get('baslangic') and self.returnee_left() < 1:
            with self.p.lock:
                st['kapali'] = True
                self.p.dirty = True
        return self.window_item('returnee_login', self.returnee_active())

    # ------------------------------------------------------------ Pre-Prometheus Day
    def pb_bought(self):
        return len(set(self.part('alinan_' + PB['takvim'], PB['takvim']).get('liste', [])))

    def pb_info(self):
        return ('PreBlackFridaySalesInfoCommand', {'packBought': min(5, self.pb_bought())})

    # ------------------------------------------------------------ Return of Hero
    def rh(self):
        return self.part('rehero', RH['takvim'])

    def rh_day(self, now=None):
        st = self.rh()
        if not st.get('baslangic'):
            with self.p.lock:
                st['baslangic'] = today(now).isoformat()
                self.p.dirty = True
        return (today(now) - datetime.date.fromisoformat(st['baslangic'])).days

    def rh_quests(self, now=None):
        """(tekrarsız, bugünün günlükleri): ilk 13 görev tekrarsız, kalan havuzdan gün başına 5 (gün tohumuyla)."""
        qs = RH['gorevler']
        once = qs[:RH['tekrarsiz_adet']]
        pool = qs[RH['tekrarsiz_adet']:] or qs
        d = self.rh_day(now)
        st = self.rh()
        if st.get('gun_no') != d:          # yeni gün: günlük havuzun tamam/ilerlemesi sıfırlanır (yoksa yeniden çıkan görev bitmiş görünür)
            pool_ids = {q['id'] for q in pool if q not in once}
            with self.p.lock:
                st['tamam'] = [i for i in st.get('tamam', []) if i not in pool_ids]
                for i in pool_ids:
                    st.get('deger', {}).pop(str(i), None)
                st['gun_no'] = d
                self.p.dirty = True
        if d >= RH['gun']:
            return once, []
        rnd = random.Random('%s-%d' % (self.rh().get('baslangic'), d))
        return once, rnd.sample(pool, min(RH['gunluk_adet'], len(pool)))

    def rh_quest_module(self, q, st):
        done = q['id'] in st.get('tamam', [])
        return mod('EventQuestDefinitionModule', module=GT.with_state(q, st.get('deger', {}).get(str(q['id']), {}), done),
                   completed=done, claimed=done)

    def rh_cmd(self, rtype=1, error=None, now=None):
        st = self.rh()
        once, daily = self.rh_quests(now)
        bound = bool(st.get('bagli'))
        tomorrow = datetime.datetime.combine(today(now) + datetime.timedelta(days=1), datetime.time()).timestamp()
        nows = time.time() if now is None else now
        from magaza import stack_msg
        return ('EventReturnOfHeroActionCommand', dict(
            btnEnable=True, returnType=int(rtype), errorMessage=error if isinstance(error, dict) else stack_msg(error or 'empty'),
            inviterName=st.get('veteran', '') if bound else '', bootKeyLootId=RH['anahtar'], inviterId=int(st.get('kod', 0)),
            eventReturnOfHeroQuestCommand=mod('EventReturnOfHeroQuestCommand', dailyNextRefreshSecond=int(max(0, tomorrow - nows)),
                                              dailyQuests=[self.rh_quest_module(q, st) for q in daily],
                                              noRepeatNextRefreshSecond=int(TK.time_left(RH['takvim'])),
                                              noRepeatQuests=[self.rh_quest_module(q, st) for q in once]),
            eventReturnOfHeroContributorListCommand=mod('EventReturnOfHeroContributorListCommand', contributorList=[]),
            activityStatus=4 if bound else 2, bootKeyAmount=float(INV.count(self.p, RH['anahtar']))))

    def rh_exchange_info(self):
        st = self.rh()
        rows = [dict(r, claimCount=int(st.get('takas', {}).get(r['exchangeReward'], 0))) for r in RH['takas']]
        return ('BattlePassKeyExchangeInfoCommand', dict(rewardList=rows, numOfKeys=int(INV.count(self.p, RH['anahtar'])), exchangeType=2))

    def rh_action(self, f):
        if not TK.is_active(RH['takvim']):
            return []
        act = int(f.get('actionType') or 0)
        st = self.rh()
        if act == 0:
            return [self.rh_cmd(1), self.rh_exchange_info()]
        if act == 1:
            if st.get('bagli'):
                return [self.rh_cmd(0, 'empty')]
            if time.time() - st.get('ilk_giris', time.time()) > RH['bag_suresi_sn']:     # SSS: girişten 24 saat içinde
                return [self.rh_cmd(0, self.m.neden('rh_bag_suresi'))]
            with self.p.lock:
                st.update(bagli=True, kod=int(f.get('id') or 0), veteran=random.choice(RH['veteran_adlari']))
                self.p.dirty = True
            self.log('   Return of Hero: %s veterana bağlandı' % st['veteran'])
            return [self.rh_cmd(2)]
        if act == 2:
            key = str(f.get('exchange') or '')
            r = RH_X.get(key)
            done = st.get('takas', {}).get(key, 0)
            if not r or done >= r['limit'] or INV.spend(self.p, {RH['anahtar']: r['cost']}, 'buy_SPECIAL', 'return_of_hero') is None:
                return [self.rh_cmd(0, 'captain_hangar_error_not_enough_resources')]
            with self.p.lock:
                st.setdefault('takas', {})[key] = done + 1
                self.p.dirty = True
            msgs = []
            for x in r['listOfloot']:
                msgs += self.m.reward(x['lootId'], x['amount']) if self.m else []
            self.log('   Return of Hero takas: %s (%d anahtar)' % (key, r['cost']))
            return msgs + [('BattlePassKeyExchangeUpdateCommand', dict(spcId=0, numOfKeys=int(INV.count(self.p, RH['anahtar'])),
                                                                       claimCount=done + 1, exchangeReward=key, lootId=RH['anahtar'])),
                           self.rh_cmd(1), self.rh_exchange_info()]
        return []

    def event(self, kind, kw):
        """Görev olayları (oturumun quest olayları): Return of Hero görevleri ilerler; biten görev anahtar verir."""
        if not TK.is_active(RH['takvim']) or not self.rh().get('bagli'):
            return []
        st = self.rh()
        once, daily = self.rh_quests()
        msgs = []
        for q in once + daily:
            if q['id'] in st.get('tamam', []):
                continue
            m, fin = GT.advance(self.p, q['rootCase'], st.setdefault('deger', {}).setdefault(str(q['id']), {}), kind, kw, self.map_id)
            msgs += m
            if fin:
                n = RH['anahtar_odulu']['tekrarsiz' if q in once else 'gunluk']
                with self.p.lock:
                    st.setdefault('tamam', []).append(q['id'])
                    self.p.dirty = True
                self.p.add_resource(RH['anahtar'], n)
                msgs.append(('EventQuestCompletedCommand', dict(eventType='ReturnOfHero', repeatableType='DAILY' if q in daily else 'NONE')))
                msgs += INV.update_msgs(self.m, self.p, [RH['anahtar']])
                self.log('   Return of Hero görevi bitti: %d (+%d anahtar)' % (q['id'], n))
        if any(n == 'EventQuestCompletedCommand' for n, f in msgs):
            msgs += [self.rh_cmd(1), self.rh_exchange_info()]       # takas satırlarının anahtar sayısı (sekme açılınca yenilenir)
        return msgs

    # ------------------------------------------------------------ Ö3 kabının yüzü
    def attach(self, world):
        self.map_id = world.map_id
        return []

    def tick(self, now):
        if now - self.st.get('son_oturum', 0) >= 60:          # oturumun son anı (bir sonraki girişte Returnee'nin ölçüsü)
            with self.p.lock:
                self.st['son_oturum'] = now
                self.p.dirty = True
        return []

    def window_item(self, item_id, visible):
        it = self.p.window_item(item_id) if hasattr(self.p, 'window_item') else None
        return [('WindowItemCommand', dict(it, visible=bool(visible), maximized=False))] if it else []

    def login_msgs(self):
        self.mm_expire()
        msgs = []
        if TK.is_active(MM['takvim']):
            msgs.append(self.mm_info())
        if TK.is_active(VIP['takvim']):
            msgs.append(self.vip_info())
        if self.returnee_active():
            msgs += self.returnee_msgs()
        if TK.is_active(PB['takvim']):
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
            return [OD.open_shop(), self.info_msg('Mileage Packs: Shop > Extras (uridium).')]
        if name == 'MileageMarketExchangeRequest':
            return self.mm_exchange(f)
        if name == 'MileageMarketPackageBuyRequest':
            return self.mm_buy(f)
        if name == 'VIPMerchantExchangeBuyRequest':
            return [OD.open_shop(), self.info_msg('VIP Merchant Packs: Shop > Extras (uridium).')]
        if name == 'VIPMerchantExchangeRequest':
            return self.vip_exchange(f)
        if name == 'ReturneeLoginRewardClaimRequest':
            return self.returnee_claim(f)
        if name == 'ReturneeLoginBundleBuyRequest':
            return [OD.open_shop(), self.info_msg('Returnee Bundles: Shop > Extras (uridium).')]
        if name == 'ReturneeLoginHideUIItemRequest':
            return self.returnee_hide()
        if name in ('EventReturnOfHeroActionRequest', 'EventANewHopeActionRequest'):
            return self.rh_action(f)
        return []

    @staticmethod
    def info_msg(text):
        import kapi as KAPI
        return KAPI.screen(text)
