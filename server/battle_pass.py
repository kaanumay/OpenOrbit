"""Battle Pass ve anahtar değişimi (yol haritası Aşama 7, E8; veri data/tickets.json "savas_bileti" <- tools/tickets.py): etkinlik
başına pass ('passler': Halloween kayıttan ve CDN'deki pass_halloween2026.xml'den, Immortal Union resmî pass_valentine2026.xml'den,
Hitac, Protegit, Mimesis, GoP, Treacherous Domain, Frozen Labyrinth, Galactic Strife, Astral Ascension ve Space Cup yazılan
pass_offline_*.xml'lerle); anahtar değişimi: Halloween'de kayıttaki liste, önünde etkinliğin tasarımları (event_appearances.py);
öteki etkinliklerin kendi tablosu (passler[k].anahtar_degisimi: wiki'deki tablo, bedel/sınır/öncelik etkinlik başına).

Mesajlar (istemcinin kodu ve kayıt):
  giriş       BattlePassInfoCommand {filename, statusCommand BattlePassUpdateStatusCommand {questsToCollectReward [görev],
              purchased}, battlePassQuestModuleList [BattlePassQuestModule {acceptabilityStatus 2 sürüyor / 3 bitti, questDefinition}]},
              BattlePassKeyExchangeInfoCommand {rewardList, numOfKeys, exchangeType}, BattlePassWindowSettingsModule
  ilerleme    QuestConditionUpdateCommand; bitince QuestCompletedCommand ve toplanacaklar listesi (BattlePassUpdateStatusCommand)
  toplama     BattlePassCollectRequest: biten görevlerin ödülü (XML'in questReward'ı) ve Battle Pass alındıysa anahtarları (bpReward)
  değişim     BattlePassKeyExchangeRequest {exchangeReward}: anahtar (resource_battle-pass-key) harcanır, ödül verilir ->
              BattlePassKeyExchangeUpdateCommand {numOfKeys, claimCount, exchangeReward, lootId}; anahtar sayısı değişince de (kayıt)
  süzgeç      BattlePassSetFilterRequest {battlePassWindowSettingsModule}
Battle Pass etkinliğin (event_calendar.py: 'BattlePass' türü olan, pass'i olan etkinlik) süresince; anahtar değişimi de. Battle Pass mağazada
(resource_battle-pass 200.000 U): alınınca o ana dek toplanan görevlerin anahtarları da verilir (uyarlama). Anahtarsız pass ('anahtarsiz':
Veba Mutasyonu 2020, resmî Türk forumu 154610): Battle Pass'in ödülü hedefin biletli ödülü ('bilet_odul', XML'in bpReward'ı); anahtar
değişimi yok.
Kayda özgü süre (geliştirici notu 2026-10-28): pass'li etkinlik açılınca kaydın pass'i 1. günden başlar ('bas') ve panelin
savas_bileti_suresi günü sürer; bu sürede etkinlik de açık sayılır (takvim.PASS_RUNS: görevler etkinliğin içeriğine bağlı), takvimdeki
dönemi önce bitse de. Aynı anda tek pass: süren pass bitmeden başka pass'li etkinlik açılsa da değişmez; biten pass aynı dönemde
yeniden başlamaz.
Profilde: savas_bileti {donem, bas, satin, deger, tamam, toplanacak, toplandi, degisim, suzgec}.
"""
import json, os, time

import settings as SET
import inventory as INV
import event_appearances as EG
import quest_tracker as GT
import event_calendar as CAL

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'tickets.json'), encoding='utf8'))['battle_pass']
PASSES = {k: dict(p, quests={int(q): d for q, d in p['quests'].items()}, rewards={int(q): r for q, r in p['rewards'].items()})
          for k, p in B['passes'].items()}
EXCHANGE = {r['exchangeReward']: r for r in B['key_exchange']}
EVENT_EXCHANGE = {k: {r['exchangeReward']: r for r in EG.exchange_rows(k)} for k in PASSES}      # etkinlik -> tasarım satırları
PASS_EXCHANGE = {k: {r['exchangeReward']: dict(r) for r in p['key_exchange']} for k, p in PASSES.items() if p.get('key_exchange')}
for _k, _rows in PASS_EXCHANGE.items():
    # etkinliğin kendi tablosunda olmayan tasarımlar (etkinlik_gorunumleri.json: başka tasarım sayfalarının kaynakları) sona özel satır
    # olarak kalır; mağazada satılmayan bu tasarımların tek yolu burası (etkinlik_gorunumleri.ITEMS)
    _have = {x['lootId'] for r in _rows.values() for x in r['listOfloot']}
    _top = max([r['priority'] for r in _rows.values() if r['isSpecial']] or [0])
    for _r in EVENT_EXCHANGE[_k].values():
        if _r['listOfloot'][0]['lootId'] not in _have:
            _top += 1
            _rows[_r['exchangeReward']] = dict(_r, priority=_top)
KEY, PASS_ITEM = 'resource_battle-pass-key', 'resource_battle-pass'
RUNNING, DONE = 2, 3
CLOAK = 'equipment_extra_cpu_cl04k'      # Cloak CPU çeşitleri (-m, -xl, -xs): görevler tek kimliğe (-xs) bağlı


def mod(name, **f):
    f['_'] = name
    return f


def measure(c, kind, kw, map_id=None):
    """gorev_takip.measure + Pass görevlerine özgü üç eşleme: "hasar al" (tür 7, görünüm 9 = TAKE_DAMAGE) alınan hasarı sayar;
    cephane harcama (SPEND_ITEM + cephane: use_ammo 'ammo' olayı yayar) 'spend' gibi sayılır; Cloak CPU çeşitleri tek kimlik."""
    if c['type'] == 7 and c.get('displayType') == 9:
        c = dict(c, type=9)
    if c['type'] == 89 and kind == 'ammo':
        kind = 'spend'
    if kind == 'spend' and kw.get('loot', '').startswith(CLOAK):
        kw = dict(kw, loot=CLOAK + '-xs')
    return GT.measure(c, kind, kw, map_id)


def duration():
    return max(1, int(SET.get('battle_pass_duration'))) * 86400


def event_key(now=None):
    """Battle Pass'i açan etkinlik ve dönemi ('halloween-2026') ya da None."""
    for k in sorted(CAL.active(now)):
        if 'BattlePass' in CAL.EVENTS[k].get('kinds', []) and k in PASSES:
            p = CAL.period(k, now)
            year = time.localtime(p[0]).tm_year if p else time.localtime(now).tm_year
            return '%s-%d' % (k, year)
    return None


class BattlePass:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None
        self.send = None
        self.map_id = None
        self.objective = None         # oturum bağlar: biten görev Season Pass'in "N Battle Pass görevi" koşuluna (87)
        # istemcinin bildiği anahtar sayısı: giriş demeti (login_msgs) gönderir; None olsaydı LoginRequest sırasındaki ilk olay
        # anahtar güncellemesini giriş demetinden önce gönderiyordu
        self.keys_sent = profile.resource(KEY)

    @property
    def st(self):
        return self.p.d.setdefault('battle_pass', {})

    def active(self, now=None):
        return event_key(now) is not None

    @property
    def bp(self):
        """Dönemin pass'i (ensure'dan sonra)."""
        return PASSES[self.st['donem'].rsplit('-', 1)[0]]

    def end(self):
        return self.st.get('start', 0) + duration()

    def ensure(self, now=None):
        """Kaydın süren pass'i (dönem adı) ya da None: süren pass sürer (etkinliği de açık tutar); yoksa açık pass'li etkinliğin
        pass'i 1. günden başlar (aynı dönemin biten pass'i yeniden başlamaz)."""
        now = time.time() if now is None else now
        st = self.st
        ev = st.get('donem', '').rsplit('-', 1)[0]
        if st.get('donem') and not st.get('start'):                    # süresiz eski kayıt: etkinliği sürüyorsa pass bugünden
            with self.p.lock:
                st['start'] = now if event_key(now) == st['donem'] else 1
                self.p.dirty = True
        if st.get('donem') and now < self.end() and SET.event_state(ev) != 'off':      # panelde kapatılan etkinliğin pass'i durur
            CAL.PASS_RUNS[ev] = (st['start'], self.end())
            return st['donem']
        CAL.PASS_RUNS.pop(ev, None)
        extra = event_key(now)
        if not extra or extra == st.get('donem'):
            return None
        with self.p.lock:
            st.clear()
            st.update(donem=extra, start=now, purchased=False, value={}, tamam=[], to_collect=[], collected=[], exchange={},
                      filters=B['settings'].get('battlePassItemFilters', []))
            self.p.dirty = True
        if self.p.resource(PASS_ITEM) > 0:                       # önceden alınmış Battle Pass bu döneme
            self.p.add_resource(PASS_ITEM, -1)
            st['purchased'] = True
        CAL.PASS_RUNS[extra.rsplit('-', 1)[0]] = (now, self.end())
        self.log('   Battle Pass başladı: %s (%d gün)' % (extra, duration() // 86400))
        return extra

    # ------------------------------------------------------------ mesajlar
    def status_cmd(self):
        st = self.st
        return mod('BattlePassUpdateStatusCommand', questsToCollectReward=list(st.get('to_collect', [])), purchased=bool(st.get('purchased')))

    def info_cmd(self):
        st, bp = self.st, self.bp
        rows = [mod('BattlePassQuestModule', acceptabilityStatus=mod('QuestAcceptabilityStatusModule', type=DONE if q in st['tamam'] else RUNNING),
                    questDefinition=GT.with_state(d, st['value'].get(str(q), {}), q in st['tamam'])) for q, d in bp['quests'].items()]
        return ('BattlePassInfoCommand', dict(filename=bp['dosya'], statusCommand=self.status_cmd(), battlePassQuestModuleList=rows))

    def exchanges(self):
        """Dönemin anahtar değişimi (ensure'dan sonra): etkinliğin kendi tablosu; yoksa (Halloween) tasarımları, ardından kayıttaki liste."""
        k = self.st['donem'].rsplit('-', 1)[0]
        if self.bp.get('keyless'):
            return {}
        return dict(PASS_EXCHANGE[k]) if k in PASS_EXCHANGE else dict(EVENT_EXCHANGE.get(k, {}), **EXCHANGE)

    def exchange_cmd(self):
        rows = [dict(r, claimCount=self.st.get('exchange', {}).get(k, 0)) for k, r in self.exchanges().items()]
        return ('BattlePassKeyExchangeInfoCommand', dict(rewardList=rows, numOfKeys=self.p.resource(KEY), exchangeType=0))

    def key_update(self, reward='', count=0):
        self.keys_sent = self.p.resource(KEY)
        return ('BattlePassKeyExchangeUpdateCommand', dict(spcId=0, numOfKeys=self.keys_sent, claimCount=count, exchangeReward=reward,
                                                           lootId=KEY))

    def login_msgs(self):
        """Etkinlik süresince Battle Pass pencereleri; değilse hiçbiri (istemci Battle Pass düğmesini göstermez)."""
        if not self.ensure():
            return []
        self.keys_sent = self.p.resource(KEY)
        return [self.info_cmd(), self.exchange_cmd(), ('BattlePassWindowSettingsModule', {'battlePassItemFilters': list(self.st['filters'])})]

    # ------------------------------------------------------------ görevler
    def event(self, kind, **kw):
        if not self.p.d.get('battle_pass') or not self.ensure():     # etkinlik değiştiyse yeni dönemin pass'i
            return []
        st, msgs, done = self.st, [], []
        for q, d in self.bp['quests'].items():
            if q in st['tamam']:
                continue
            m, fin = GT.advance(self.p, d['rootCase'], st['value'].setdefault(str(q), {}), kind, kw, self.map_id, fn=measure)
            msgs += m
            if fin:
                done.append(q)
        for q in done:
            with self.p.lock:
                st['tamam'].append(q)
                st['to_collect'].append(q)
                self.p.dirty = True
            msgs.append(('QuestCompletedCommand', {'id': q, 'rating': 0}))
            self.p.ach('quest', id=q)
            self.log('   Battle Pass görevi bitti: %d' % q)
        if done:
            msgs.append(('BattlePassInfoCommand', self.info_cmd()[1]))
            for q in done:                                            # "N Battle Pass görevi bitir" (Battle Pass ve Season Pass)
                msgs += self.event('objective') if kind != 'objective' else []
                if self.objective:
                    self.objective()
        if kind == 'objective':
            return msgs
        if self.p.resource(KEY) != self.keys_sent:
            msgs.append(self.key_update())
        if msgs and self.send:
            self.send(msgs)
        return msgs

    # ------------------------------------------------------------ istekler
    def keys_for(self, q):
        return self.bp['rewards'].get(q, {}).get('anahtar', 0)

    def ticket_rewards(self, qs):
        """Biletli ödüller (anahtarsız pass): Battle Pass alınmışsa toplanan hedeflerinki."""
        msgs = []
        for q in qs:
            for loot, n in self.bp['rewards'].get(q, {}).get('ticket_reward', []):
                msgs += self.m.reward(loot, n) if self.m else []
        return msgs

    def collect(self, f=None):
        st = self.st
        if not self.ensure() or not st['to_collect']:
            return [('BattlePassInfoCommand', self.info_cmd()[1])] if self.p.d.get('battle_pass') else []
        msgs, keys = [], 0
        for q in list(st['to_collect']):
            for loot, n in self.bp['rewards'].get(q, {}).get('reward', []):
                msgs += self.m.reward(loot, n) if self.m else []
            if st.get('purchased'):
                keys += self.keys_for(q)
                msgs += self.ticket_rewards([q])
        with self.p.lock:
            st['collected'] += st['to_collect']
            st['to_collect'] = []
            self.p.dirty = True
        if keys:
            self.p.add_resource(KEY, keys)
        self.log('   Battle Pass ödülleri toplandı%s' % (' (+%d anahtar)' % keys if keys else ''))
        return msgs + [self.info_cmd(), self.key_update()]

    def grant_pass(self, n=1):
        """Mağazadan Battle Pass: bu dönem için; toplanmış görevlerin anahtarları verilir."""
        if not self.ensure():
            self.p.add_resource(PASS_ITEM, n)                        # etkinlik yokken alınırsa sonraki Battle Pass'e
            return []
        st = self.st
        if st.get('purchased'):
            self.p.add_resource(PASS_ITEM, n)
            return []
        keys = sum(self.keys_for(q) for q in st['collected'])
        with self.p.lock:
            st['purchased'] = True
            self.p.dirty = True
        if keys:
            self.p.add_resource(KEY, keys)
        msgs = self.ticket_rewards(st['collected'])                  # forum 154610: önceki hedeflerin biletli ödülleri de
        self.log('   Battle Pass alındı (+%d anahtar)' % keys)
        return msgs + [self.info_cmd(), self.key_update()]

    def exchange(self, f):
        name = f.get('exchangeReward') or ''
        st = self.st
        r = self.exchanges().get(name) if self.ensure() else None
        if not r:
            return []
        count = st['exchange'].get(name, 0)
        if count >= r['limit'] or INV.spend(self.p, {KEY: r['cost']}, reason='buy_SPECIAL', detail='battle_pass_' + name) is None:
            self.log('   anahtar değişimi yok: %s (%d/%d, %d anahtar)' % (name, count, r['limit'], self.p.resource(KEY)))
            return [self.key_update(name, count)]
        with self.p.lock:
            st['exchange'][name] = count + 1
            self.p.dirty = True
        msgs = []
        for x in r['listOfloot']:
            msgs += self.m.reward(x['lootId'], x['amount']) if self.m else []
        self.log('   anahtar değişimi: %s (%d anahtar)' % (name, r['cost']))
        return msgs + [self.key_update(name, count + 1)]

    def set_filter(self, f):
        mods = (f.get('battlePassWindowSettingsModule') or {}).get('battlePassItemFilters')
        if mods is not None and self.p.d.get('battle_pass'):
            with self.p.lock:
                self.st['filters'] = list(mods)
                self.p.dirty = True
        return []

    def handle(self, name, f):
        fn = {'BattlePassCollectRequest': self.collect, 'BattlePassKeyExchangeRequest': self.exchange,
              'BattlePassSetFilterRequest': self.set_filter}.get(name)
        return fn(f) if fn else None
