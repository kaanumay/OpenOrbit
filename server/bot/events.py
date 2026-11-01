"""Etkinlikler, Battle Pass ve Season Pass: botlar takvimdeki etkinliklere oyuncu gibi katılır (oyunun event_maps.py,
battle_pass.py, season.py ve data/tickets.json kuralları).

  etkinlik    etkin etkinliğin harita bölümü botun haritasını kapsıyorsa: gücü yeten etkinlik uzaylılarını avlar (somutta haritada
              gerçekten doğanları, soyutta bölümün listesinden), düşmeleri ('dusme': etkinlik parası) alır, haritadaki anahtarsız
              etkinlik kutularını toplar (içerik oyunun ETK.roll'u); parası Assembly'nin etkinlik tariflerine gider (ganimet.assembly)
  Battle Pass pass'li etkinlik sürerken oynadıkça pass görevleri biter (oynanan sürenin ve öldürmenin payıyla), her görevin
              ödülü alınır; pass'i alan (200.000 U, zengin ve hırslı bot) görev başına anahtar da alır; anahtarlar değişim
              tablosunda değer / anahtar oranı en iyi ödüle harcanır (sınırıyla)
  Season Pass günlük ve haftalık görevlerden puan (oynanan saatle); seviyenin puan bedeli dolunca ücretsiz sıranın ödülü
Durum: bot.k['pass'] = {'donem', 'tamam', 'satin', 'degisim': {ödül: adet}}, bot.k['sezon'] = {'donem', 'puan', 'seviye'}.
"""
import json, os, random, time

from . import catalog as K

B = json.load(open(os.path.join(K.HERE, 'data', 'tickets.json'), encoding='utf8'))
SEASON = B['sezon']
BT = B['savas_bileti']
PASS_PRICE = 200000
PASS_QUEST_SEC = 2700            # oynanan ~45 dakikada bir pass görevi
SEASON_POINTS_PER_HOUR = 30            # oynanan saatte Season Pass puanı (günlük + haftalık görevler)
_on = {'t': 0, 'bolum': [], 'aktif': set()}


def _refresh():
    import event_maps as EM, event_calendar as CAL
    t = time.time()
    if t - _on['t'] > 60:
        _on.update(t=t, bolum=EM.specs(), aktif=set(CAL.active()))
    return _on


def sections(game_map):
    """Bu haritayı kapsayan etkin etkinlik harita bölümleri [(etkinlik, bölüm)]."""
    import map_links as H
    klass, name = H.map_class(game_map), H.name(game_map)
    return [(k, s) for k, s in _refresh()['bolum'] if klass in s.get('haritalar', ()) or name in s.get('haritalar', ())]


def event_types(bot, game_map):
    """Gücü yeten etkinlik uzaylısı türleri."""
    d = bot.value()
    out = set()
    for _, s in sections(game_map):
        for u in s.get('uzaylilar', []):
            tip = str(u['tur']).replace('{x}', 'x%s' % map_number(game_map)) if '{x}' in str(u['tur']) else str(u['tur'])
            v = K.npc_value(tip) or K.npc_value(str(u['tur']))
            if v and d['dps'] > 0 and v['ehp'] / d['dps'] < 120 and v['dps'] * v['ehp'] / d['dps'] < d['ehp'] * 0.6:
                out.add(tip if K.npc_value(tip) else str(u['tur']))
    return out


def map_number(game_map):
    import map_links as H
    return H.name(game_map).split('-')[-1]


def drop(bot, game_map, tip):
    """Etkinlik uzaylısının (ya da haritanın uzaylısının) etkinlik düşmeleri bota (oyunun ETK.roll'u)."""
    import world as WD
    import event_maps as EM
    from . import loot as LT
    if not bot.permission.get('etkinlik', True):
        return
    b = EM.base(tip)
    for _, s in sections(game_map):
        tab = s.get('dusme', {})
        for loot, a in (tab.get(tip) or tab.get(b) or {}).items():
            n = WD.extra_count(a, 1.0)                    # oyunun okuyuşu: sayı, [en az, en çok] ya da {adet, olasilik} (Agatus)
            if n > 0:
                LT.give(bot, loot, n)
                bot.ist('etkinlik_dusme', n)
        box_drop = (s.get('kutu_dusme', {}).get(tip) or s.get('kutu_dusme', {}).get(b))
        if box_drop and random.random() < box_drop.get('olasilik', 1.0) * 0.8:            # düşen sandığı çoğunlukla toplar
            for loot, n in EM.roll(box_drop):
                LT.give(bot, loot, n)


def open_box(bot, spec):
    import event_maps as EM
    from . import loot as LT
    got = EM.roll(spec)
    for loot, n in got:
        LT.give(bot, loot, n)
    bot.ist('etkinlik_kutusu')
    return got


def abstract(bot, dt, y, dps):
    """Soyut: etkinlik uzaylılarını avlar (düşmeleri ve öldürme ödülü) ve haritanın etkinlik kutularına rastlar."""
    if not bot.permission.get('etkinlik', True):
        return
    bl = sections(bot.game_map)
    if not bl:
        return
    speed = y.speed(bot) if y is not None else 1.0
    crowd = max(1.0, 0.3 * len(y.on_map.get(bot.game_map, ()))) if y is not None else 1.0
    kinds = event_types(bot, bot.game_map)
    for k, s in bl:
        for u in s.get('uzaylilar', []):
            tip = next((t for t in kinds if t == str(u['tur']) or t.startswith(str(u['tur']).split('{')[0])), None)
            v = K.npc_value(tip) if tip else None
            if not v:
                continue
            ratio = min(u.get('adet', 1) * dt / 60.0 / crowd, dt * 0.25 * dps / max(1.0, v['ehp']))    # etkinlik uzaylısı payı
            n = int(ratio) + (bot.r.random() < ratio - int(ratio))
            for _ in range(n):
                o = v['odul']
                bot.reward('npc', speed, ep=o.get('ep', 0), kredi=o.get('kredi', 0), uridyum=o.get('uridyum', 0), onur=o.get('onur', 0))
                drop(bot, bot.game_map, tip)
            if n:
                bot.ist('etkinlik_npc', n)
                if y is not None:
                    y.npc_killed(bot, tip, n)
        for box in s.get('kutular', []):
            respawn = box.get('yeniden_sn') or [300, 600]
            if bot.r.random() < box.get('adet', 1) * dt / (sum(respawn) / 2.0) / crowd:
                open_box(bot, box)


# ------------------------------------------------------------------------------------------------------------ Battle Pass
def active_pass():
    """Şu an süren pass'in etkinliği (pass'i olan etkin etkinlik) ya da None."""
    active = _refresh()['aktif']
    return next((k for k in BT['passler'] if k in active), None)


def battle_pass(bot, dt):
    """Oynadıkça pass görevleri biter; ödül ve (pass alındıysa) anahtar; anahtarlar değişime."""
    from . import loot as LT
    if not bot.permission.get('etkinlik', True):
        return
    k = active_pass()
    if not k:
        return
    st = bot.k.setdefault('pass', {})
    if st.get('donem') != k:
        st.clear()
        st.update(donem=k, tamam=0, satin=False, sure=0.0, degisim={})
    p = BT['passler'][k]
    rewards = list((p.get('oduller') or {}).values())
    if not st['satin'] and not p.get('anahtarsiz') and bot.level >= 12 and bot.o('hirs') > 0.6 \
            and bot.k['uridyum'] > PASS_PRICE * (2 + bot.o('tutumluluk')) and bot.pay('U', PASS_PRICE * bot.game_settings.multiplier('magaza_fiyat')):
        st['satin'] = True
        bot.ist('battle_pass')
        stock = LT.stock(bot)
        stock['resource_battle-pass-key'] = stock.get('resource_battle-pass-key', 0) + st['tamam']     # o ana dek toplananlar
    st['sure'] += dt
    while st['sure'] >= PASS_QUEST_SEC and st['tamam'] < len(rewards):
        st['sure'] -= PASS_QUEST_SEC
        o = rewards[st['tamam']]
        st['tamam'] += 1
        for loot, n in o.get('odul', []):
            LT.give(bot, loot, n)
        if st['satin']:
            stock = LT.stock(bot)
            stock['resource_battle-pass-key'] = stock.get('resource_battle-pass-key', 0) + o.get('anahtar', 0)
        bot.ist('pass_gorev')
    exchange(bot, st)


def exchange(bot, st):
    """Battle Pass anahtarlarını değişim tablosunda en iyi değer / anahtar oranlı ödüle harcar (sınırıyla)."""
    from . import loot as LT
    stock = LT.stock(bot)
    table = (BT['passler'].get(st['donem']) or {}).get('anahtar_degisimi') or BT['anahtar_degisimi']
    while stock.get('resource_battle-pass-key', 0) > 0:
        eligible = [r for r in table if r['cost'] <= stock['resource_battle-pass-key']
                 and st['degisim'].get(r['exchangeReward'], 0) < r.get('limit', 99)]
        if not eligible:
            return
        r = max(eligible, key=lambda r: sum(LT.value(l['lootId'], l['amount']) for l in r['listOfloot']) / max(1, r['cost']))
        stock['resource_battle-pass-key'] -= r['cost']
        st['degisim'][r['exchangeReward']] = st['degisim'].get(r['exchangeReward'], 0) + 1
        for l in r['listOfloot']:
            LT.give(bot, l['lootId'], l['amount'])
        bot.ist('pass_degisim')


# ------------------------------------------------------------------------------------------------------------ Season Pass
def season_period():
    t = time.localtime()
    month = ((t.tm_mon - 2) // 3) * 3 + 2 if t.tm_mon >= 2 else 11
    return '%d-%02d' % (t.tm_year if t.tm_mon >= 2 else t.tm_year - 1, month)


def season_pass(bot, dt):
    from . import loot as LT
    if not bot.permission.get('etkinlik', True):
        return
    st = bot.k.setdefault('sezon', {})
    d = season_period()
    if st.get('donem') != d:
        st.clear()
        st.update(donem=d, puan=0.0, seviye=0)
    st['puan'] += SEASON_POINTS_PER_HOUR * dt / 3600.0 * (0.7 + 0.6 * bot.o('hirs'))
    cost = SEASON['puan_bedeli']
    order = {lv: (loot, n) for lv, loot, n in SEASON['odul'].get('ucretsiz', [])}
    while st['seviye'] + 1 < len(cost) and st['puan'] >= cost[st['seviye'] + 1]:
        st['puan'] -= cost[st['seviye'] + 1]
        st['seviye'] += 1
        if st['seviye'] in order:
            LT.give(bot, *order[st['seviye']])
        bot.ist('sezon_seviye')
