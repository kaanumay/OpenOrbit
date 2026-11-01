"""Etkinliğe özel modlar ve PvE modları: botlar oyuncunun girebildiği her moda aynı kurallarla girer (soyut koşu).

Her mod (Mod alt sınıfı) oyunun verisinden: açık mı (takvim, saat penceresi), girebilir mi (seviye, bilet/anahtar/CPU, günlük /
yıllık / bekleme sınırı, firma), bedel (bilet harcanır ya da uridyumla alınır), dalgalar [(can+kalkan, aynı anda vuranların
saniyede hasarı, uzaylıların öldürme ödülleri)], can hakkı, süre sınırı ve bitiş ödülü (ulaşılan dalgaya göre: yıldız, rift,
basamak, seviye). Koşu (kos) dalga dalga ilerler: botun en iyi cephanesiyle hasarı (kapi.tahmin'in yöntemi), ölümler can hakkını
bitirince durur; öldürme ödülleri ulaşılan dalgalarınki, bitiş ödülü modun kuralıyla. Bot koşu boyunca modun haritasındadır
(senin haritandan kalkar; hedefler/mode_run.py).

Modlar: etkinlik kapıları (Gauntlet of Plutus, Trial of Terrors, Birthday, Quarantine Zone, Compromising Invasion, Permafrost,
The Breach, Devolarium Attack), Voyagers' Ascent, Trinity Trials, Astral Ascension, Eternal Black Light, Deep Space Echoes,
Battle of LoW, Vortex of Greed, Mimesis Mutiny, World Boss, Kristallon Apotheosis, Frozen Labyrinth. Pasifler (Dispatch,
Galaxy Trek) pasif() ile karar anında.
"""
import json, os, random, time

from . import catalog as K

D = lambda f: json.load(open(os.path.join(K.HERE, 'data', f), encoding='utf8'))
PVE = D('pve_modes.json')
EVG = D('event_gates.json')
BIG_CONTENT = D('major_content.json')
LOW = D('low.json')
EX = D('extra_events.json')
DISP = D('dispatch.json')


def _tech():
    import event_calendar as CAL
    return CAL


def kind_value(tip):
    """Uzaylı türü -> (hp, kalkan, hasar, ödül): PvE türleri, npc.json ya da modun kendi tablosu."""
    t = PVE['kinds'].get(tip) or K.NPC['types'].get(str(tip))
    if not t:
        return None
    return t.get('hp', 0), t.get('kalkan', 0), t.get('hasar', 0), t.get('reward') or {}


def wave(groups, health=1.0, damage=1.0, table=None):
    """[[[tür, adet], …], …] (gruplar) -> (can+kalkan, saniyede gelen hasar, öldürme ödülleri)."""
    ehp = dps = 0.0
    reward = {}
    for group in groups:
        for x in group:
            tip, n = x[0], x[1]                          # [tür, adet] ya da [tür, adet, patron mu]
            v = (table or {}).get(tip)
            v = (v.get('hp', 0), v.get('kalkan', 0), v.get('hasar', 0), v.get('reward') or {}) if v else kind_value(tip)
            if not v:
                continue
            hp, kl, dmg, rew = v
            ehp += n * (hp + kl) * health
            dps += min(n, 2) * dmg * damage * K.COMBAT['npc_hit_chance'] * 0.6 / K.NPC_INTERVAL
            for k, x in rew.items():
                reward[k] = reward.get(k, 0) + x * n
    return ehp, dps, reward


def alien_wave(aliens):
    """Etkinlik kapısı biçimi: [{hp, kalkan, hasar, adet, odul}] -> dalga."""
    table = {str(i): u for i, u in enumerate(aliens)}
    return wave([[[str(i), u.get('adet', 1)] for i, u in enumerate(aliens)]], table=table)


# ------------------------------------------------------------------------------------------------------------ ödül
def grant_list(bot, rows, rng=random):
    """[[loot, adet ya da [en az, en çok]], …] -> bota."""
    from . import loot as LT
    for r in rows or []:
        loot, n = r[0], r[1]
        n = rng.randint(*n) if isinstance(n, list) else n
        if n:
            LT.give(bot, loot, n)


def grant_reward(bot, o, rng=random, speed=1.0):
    """Etkinlik kapısı / genel ödül sözlüğü: ep, onur, kredi, uridyum, esyalar, sans [[loot, n, olasılık]], biri [[loot, n, ağırlık]]."""
    if not o:
        return
    currency = {k: o[k] for k in ('ep', 'onur', 'kredi', 'uridyum') if o.get(k)}
    if currency:
        bot.reward('gorev', speed, **currency)
    grant_list(bot, o.get('esyalar'), rng)
    for loot, n, p in o.get('chance') or []:
        if rng.random() < p:
            grant_list(bot, [[loot, n]], rng)
    if o.get('one_of'):
        r = rng.choices(o['one_of'], weights=[x[2] if len(x) > 2 else 1 for x in o['one_of']])[0]
        grant_list(bot, [r[:2]], rng)


def state(bot, mod):
    return bot.k.setdefault('modes', {}).setdefault(mod, {})


def day():
    return time.strftime('%Y-%m-%d')


# ------------------------------------------------------------------------------------------------------------ modlar
class Mod:
    name = ''
    uid = ''
    game_map = None              # koşu boyunca botun haritası (senin haritandan kalkar)
    hp = 1
    level = 1
    time_limit = None          # koşunun en uzun süresi (sn; süreli modlar)
    tip = 'run'

    def is_open(self, now):
        return True

    def can_enter(self, bot, now):
        return bot.level >= self.level

    def cost(self, bot):
        return True

    def affordable(self, bot):
        """Giriş bedeli şimdi ödenebilir mi (harcamadan): aday seçimi için."""
        return True

    def waves(self, bot):
        return []

    def finish(self, bot, reached, total, duration, rng):
        pass

    def save(self, bot, reached, total):
        state(bot, self.uid).update(last=time.time(), gun=day(), sayi=state(bot, self.uid).get('sayi', 0) + 1)


def _stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def _has_or_can_buy(bot, loot, uridium=None):
    if _stock(bot).get(loot, 0) > 0:
        return True
    f = K.price(loot)
    price = uridium if uridium else (f[1] if f and f[0] == 'U' else None)
    return bool(price) and bot.permission.get('shop', True) and \
        bot.k['uridyum'] >= price * bot.game_settings.multiplier('shop_price') * (3 + 3 * bot.o('frugality'))


def _spend_or_take(bot, loot, uridium=None):
    """Bilet/anahtar/CPU stokta varsa harcar; yoksa uridyumla alınabiliyorsa (fiyat ya da verilen) ve bot zenginse alır."""
    s = _stock(bot)
    if s.get(loot, 0) > 0:
        s[loot] -= 1
        if not s[loot]:
            del s[loot]
        return True
    f = K.price(loot)
    price = uridium if uridium else (f[1] if f and f[0] == 'U' else None)
    if not price or not bot.permission.get('shop', True):
        return False
    price *= bot.game_settings.multiplier('shop_price')
    if bot.k['uridyum'] < price * (3 + 3 * bot.o('frugality')):
        return False
    return bot.pay('U', price)


class EventGate(Mod):
    """data/event_gates.json kapilar.<anahtar>: etkinlik, kural (gunluk+grup, yillik, donem, bekleme_sn, seviye,
    azami_seviye, firma, bir_kez, cpu, gorev), can, dalgalar (uzaylilar), odul."""

    def __init__(self, k, g):
        self.uid, self.g = 'egate_' + k, g
        self.name = g['ad']
        self.game_map = (g.get('haritalar') or [None])[0]
        self.hp = min(int(g.get('can', 1)), 50)
        self.rule = g.get('rule') or {}
        self.level = self.rule.get('seviye', 1)

    def is_open(self, now):
        e = self.g.get('etkinlik')
        if e and not _tech().is_active(e, now):
            return False
        period = self.rule.get('donem')
        if period:
            md = time.strftime('%m-%d', time.localtime(now))
            return any((a <= md <= b) if a <= b else (md >= a or md <= b) for a, b in period)
        return True

    def can_enter(self, bot, now):
        k, st = self.rule, state(bot, self.uid)
        if bot.level < k.get('seviye', 1) or bot.level > k.get('max_level', 99):
            return False
        if k.get('firma') and k['firma'] != bot.firma:
            return False
        if k.get('once') and st.get('sayi'):
            return False
        if k.get('daily'):
            group = k.get('grup') or self.uid
            if state(bot, 'group_' + group).get('gun') == day():
                return False
        if k.get('yearly') and st.get('year') == time.strftime('%Y'):
            return False
        if k.get('bekleme_sn') and now - st.get('last', 0) < k['bekleme_sn']:
            return False
        if k.get('gorev'):
            g = bot.k.get('gorev') or {}
            if str(g.get('id')) != str(k['gorev']):
                return False
        if k.get('cpu') and _stock(bot).get(k['cpu'], 0) <= 0 and not K.price(k['cpu']):
            return False
        return True

    def cost(self, bot):
        cpu = self.rule.get('cpu')
        return _spend_or_take(bot, cpu) if cpu else True

    def affordable(self, bot):
        cpu = self.rule.get('cpu')
        return _has_or_can_buy(bot, cpu) if cpu else True

    def waves(self, bot):
        return [alien_wave(d.get('alien_spawns', [])) for d in self.g.get('waves', [])]

    def finish(self, bot, reached, total, duration, rng):
        if reached >= total:
            grant_reward(bot, self.g.get('reward'), rng)

    def save(self, bot, reached, total):
        super().save(bot, reached, total)
        k = self.rule
        if k.get('daily'):
            state(bot, 'group_' + (k.get('grup') or self.uid))['gun'] = day()
        if k.get('yearly'):
            state(bot, self.uid)['year'] = time.strftime('%Y')


class Voyagers(Mod):
    uid, name, tip = 'voyagers', "Voyagers' Ascent", 'arena'
    V = PVE['voyagers']
    game_map = V['harita'] if isinstance(V['harita'], int) else 0
    level = 8

    def difficulty(self, bot):
        st = state(bot, self.uid)
        d = 0
        while d + 1 < len(self.V['difficulties']) and st.get('star', {}).get(str(d), 0) >= 3:
            d += 1
        return d

    def can_enter(self, bot, now):
        return bot.level >= self.level

    def cost(self, bot):
        st = state(bot, self.uid)
        if st.get('free') != day():
            st['free'] = day()
            return True
        return _spend_or_take(bot, self.V['token'])

    def affordable(self, bot):
        return state(bot, self.uid).get('free') != day() or _has_or_can_buy(bot, self.V['token'])

    def waves(self, bot):
        z = self.V['difficulties'][self.difficulty(bot)]
        return [wave(d['gruplar']) for d in z['waves']]

    def finish(self, bot, reached, total, duration, rng):
        if reached < total:
            return
        sec = self.V['star_sec']
        star = 3 if duration <= sec[0] else 2 if duration <= sec[1] else 1
        d = self.difficulty(bot)
        st = state(bot, self.uid).setdefault('star', {})
        st[str(d)] = max(st.get(str(d), 0), star)
        grant_list(bot, self.V['difficulties'][d]['rewards'].get(str(star)), rng)


class Trinity(Mod):
    uid, name, tip = 'trinity', 'Trinity Trials', 'arena'
    T = PVE['trinity']
    game_map = next(iter(T['haritalar'].values()))[0] if isinstance(T['haritalar'], dict) else T['haritalar'][0]
    level = 8

    def arena(self):
        g = time.localtime().tm_wday
        return next((a for a, days in self.T['days'].items() if g in days), '1')

    def cost(self, bot):
        st = state(bot, self.uid)
        if st.get('free') != day():
            st['free'] = day()
            return True
        return _spend_or_take(bot, self.T['token'])

    def affordable(self, bot):
        return state(bot, self.uid).get('free') != day() or _has_or_can_buy(bot, self.T['token'])

    def difficulty(self, bot):
        return min(len(self.T['difficulties']) - 1, max(0, bot.level // 6 - 1))

    def waves(self, bot):
        z = self.T['difficulties'][self.difficulty(bot)]
        ar = z['arenas'].get(self.arena()) or next(iter(z['arenas'].values()))
        return [wave(d['gruplar']) for d in ar]

    def finish(self, bot, reached, total, duration, rng):
        milestone = reached // 5                                   # 5 dalgada bir kilometre taşı: Quantum Prism ve Xyralith
        d = self.difficulty(bot) + 1
        if milestone:
            grant_list(bot, [[self.T['kp'], milestone], [self.T['xy'], milestone * 10 * d]], rng)


class Astral(Mod):
    uid, name = 'astral', 'Astral Ascension'
    A = PVE['astral']
    game_map = A['haritalar'][0]
    level = 12

    def can_enter(self, bot, now):
        return bot.level >= self.level and (_stock(bot).get(self.A['cpu'], 0) > 0 or bool(K.price(self.A['cpu'])))

    def cost(self, bot):
        return _spend_or_take(bot, self.A['cpu'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.A['cpu'])

    def waves(self, bot):
        o = self.A['scale']
        out = []
        for r, rift in enumerate(self.A['rifts'], 1):
            s = random.choice(rift['sets'])
            health = (1 + o['rift_hp'] * r) * o['boss_hp'].get(str(r), 1)
            dmg = (1 + o['rift_damage'] * r) * o['boss_damage'].get(str(r), 1)
            out.append(_combined([wave(d['gruplar'], health, dmg) for d in s]))
        return out

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.A['reward'] if r['en_az'] <= reached <= r['max_count']), None)
        if row:
            grant_list(bot, [['resource_collectable_astralite', row.get('astralite', 0)],
                            ['resource_collectable_salvage-core', row.get('salvage', 0)],
                            ['resource_booty-key-astral', row.get('anahtar', 0)]], rng)


class Ebl(Mod):
    uid, name = 'ebl', 'Eternal Black Light'
    E = PVE['ebl']
    game_map = E['haritalar'][0]
    level = E['seviye']

    def can_enter(self, bot, now):
        return bot.level >= self.level and (_stock(bot).get(self.E['cpu'], 0) > 0 or bool(K.price(self.E['cpu'])))

    def cost(self, bot):
        return _spend_or_take(bot, self.E['cpu'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.E['cpu'])

    def waves(self, bot):
        out = []
        for kind in range(3):                                 # en çok 3 tur (her tur x1,8): çoğu pilot ilkinde düşer
            k = self.E['kind_multiplier'] ** kind
            out += [wave(d['gruplar'], d.get('carpan', 1) * k, d.get('carpan', 1) * k) for d in self.E['waves']]
        return out

    def finish(self, bot, reached, total, duration, rng):
        row = next((r for r in self.E['death_reward'] if r['en_az'] <= reached <= r['max_count']), self.E['death_reward'][-1]
                   if reached > self.E['death_reward'][-1]['max_count'] else None)
        if row:
            grant_list(bot, [['resource_collectable_blacklight-shard', row.get('part', 0)]], rng)


class Echoes(Mod):
    uid, name = 'echoes', 'Deep Space Echoes'
    E = PVE['echoes']
    game_map = E['haritalar'][0]
    level = E['level_requirement']
    time_limit = E['sure_sn']

    def level_no(self, bot):
        return min(len(self.E['seviyeler']) - 1, state(bot, self.uid).get('cleared', 0))

    def cost(self, bot):
        return _spend_or_take(bot, self.E['ticket'], self.E['ticket_price'])

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.E['ticket'], self.E['ticket_price'])

    def waves(self, bot):
        s = self.E['seviyeler'][self.level_no(bot)]
        k = 1 + self.E['scale_level'] * s['seviye']
        return [wave(d['gruplar'], k, k) for d in s['waves']]

    def finish(self, bot, reached, total, duration, rng):
        if reached < total:
            return
        st = state(bot, self.uid)
        s = self.E['seviyeler'][self.level_no(bot)]
        t = self.E['tekrar']
        if st.get('cleared', 0) <= self.level_no(bot):
            grant_list(bot, s.get('ilk'), rng)
            st['cleared'] = self.level_no(bot) + 1
        grant_list(bot, [['currency_uridium', t['uridium_base'] + t['uridium_level'] * s['seviye']],
                        ['ammunition_laser_ucb-100', t['ucb_base'] + t['ucb_level'] * s['seviye']]], rng)


class Low(Mod):
    uid, name = 'low', 'Battle of LoW'
    game_map = LOW['harita']
    level = 10
    tip = 'full'                                          # ödülü bitirmekte: yarısını geçemeyeceği koşuya girmez

    def can_enter(self, bot, now):
        return bot.level >= self.level and now - state(bot, self.uid).get('last', 0) > 6 * 3600     # arada bir

    def waves(self, bot):
        return [wave([[[t, n]]]) for t, n in LOW['waves']] + [wave([[[LOW['boss'], 1]]])]


class VortexGreed(Mod):
    uid, name = 'vog', 'Vortex of Greed'
    V = BIG_CONTENT['vortex']
    game_map = V['harita']
    level = V['seviye']
    time_limit = V['session_sec']

    def is_open(self, now):
        if not _tech().is_active(self.V['etkinlik'], now):
            return False
        t = time.localtime(now)
        minutes = t.tm_hour * 60 + t.tm_min
        return any(0 <= minutes - (int(s[:2]) * 60 + int(s[3:])) < self.V['session_sec'] // 60 for s in self.V['sessions'])

    def can_enter(self, bot, now):
        st = state(bot, self.uid)
        return bot.level >= self.level and st.get('session') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        aliens = self.V['alien_spawns']
        n = self.V['session_sec'] // self.V['wave_sec']
        return [wave([[[k, max(1, v.get('adet', 3))] for k, v in aliens.items()]], table=aliens) for _ in range(n)]

    def finish(self, bot, reached, total, duration, rng):
        from . import loot as LT
        st = state(bot, self.uid)
        st['session'] = time.strftime('%Y-%m-%d %H')
        week = time.strftime('%Y-%W')
        if st.get('hafta') != week:
            st.update(hafta=week, coin=0)
        coin = int(reached * self.V['wave_box'] * self.V['box_sc'] * 0.4)       # kutuların bir payını toplar, tahliye eder
        coin = min(coin, self.V['weekly_limit'] - st['coin'])
        if coin > 0:
            st['coin'] += coin
            LT.give(bot, self.V['currency'], coin)


class Mimesis(Mod):
    uid, name = 'mimesis', 'Mimesis Mutiny'
    M = BIG_CONTENT['mimesis']
    game_map = M['haritalar'].get(str(1)) if isinstance(M['haritalar'], dict) else M['haritalar'][0]
    time_limit = M['sure_sn']
    level = 10

    def is_open(self, now):
        return _tech().is_active(self.M['etkinlik'], now) and time.localtime(now).tm_hour in self.M['hours']

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('saat') != time.strftime('%Y-%m-%d %H')

    def cost(self, bot):
        return _spend_or_take(bot, self.M['anahtar'], self.M.get('key_uridium'))

    def affordable(self, bot):
        return _has_or_can_buy(bot, self.M['anahtar'], self.M.get('key_uridium'))

    def waves(self, bot):
        table = self.M['kinds']
        d = self.M['waves']
        return [wave([d['baslangic']], table=table)] + [wave([g], table=table) for g in d['waypoints']]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['saat'] = time.strftime('%Y-%m-%d %H')
        points = reached * self.M['waypoint_points'] + (self.M['arrival_bonus'] if reached >= total else 0)
        row = next((r for r in reversed(self.M['trip_tiers']) if points >= r['den']), None)
        if row:
            grant_list(bot, row['rewards'], rng)


class WorldBoss(Mod):
    uid, name = 'world_boss', 'World Boss'
    W = BIG_CONTENT['world_boss']
    game_map = W['harita']
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.W['etkinlik'], now):
            return False
        hm = time.strftime('%H:%M', time.localtime(now))
        return any(a <= hm < b for a, b in self.W['windows'])

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('windowed') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        f = self.W['npcs'].get('dreadfyre_fortress') or next(iter(self.W['npcs'].values()))
        pay = 0.02                                           # kalabalık sunucuda botun hasar payı
        return [(((f['hp'] + f['kalkan']) * pay), 0.0, {})]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['windowed'] = time.strftime('%Y-%m-%d %H')
        if reached:
            g = bot.value()['power']
            tier = self.W['kademe'][min(len(self.W['kademe']) - 1, int(g // 25))]
            grant_list(bot, tier['rewards'], rng)


class Apotheosis(Mod):
    uid, name = 'apotheosis', 'Kristallon Apotheosis'
    A = BIG_CONTENT['kristallon_apotheosis']
    game_map = A['harita']
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.A['etkinlik'], now):
            return False
        hm = time.strftime('%H:%M', time.localtime(now))
        return any(a <= hm < b for a, b in self.A['windows'])

    def can_enter(self, bot, now):
        return bot.level >= self.level and state(bot, self.uid).get('windowed') != time.strftime('%Y-%m-%d %H')

    def waves(self, bot):
        p = self.A['boss']
        return [((p['hp'] + p['kalkan']) * 0.03, p['hasar'] * 0.6 * K.COMBAT['npc_hit_chance'] / K.NPC_INTERVAL, {})]

    def finish(self, bot, reached, total, duration, rng):
        state(bot, self.uid)['windowed'] = time.strftime('%Y-%m-%d %H')
        k = self.A['participation']
        grant_list(bot, k[min(len(k) - 1, int(bot.value()['power'] // 30))], rng)


class Labyrinth(Mod):
    uid, name = 'labyrinth', 'Frozen Labyrinth'
    L = EVG['labyrinth']
    game_map = (L['baslangic'] if isinstance(L.get('baslangic'), int) else (list(L['haritalar'])[0] if L.get('haritalar') else 0))
    level = 12

    def is_open(self, now):
        if not _tech().is_active(self.L['etkinlik'], now):
            return False
        hours = self.L['hours_weekend'] if time.localtime(now).tm_wday >= 5 else self.L['hours']
        return time.localtime(now).tm_hour in (hours or range(24))

    def can_enter(self, bot, now):
        return bot.level >= self.level and now - state(bot, self.uid).get('last', 0) > 3600

    def waves(self, bot):
        aliens = self.L['alien_spawns']
        aliens = aliens if isinstance(aliens, list) else [dict(v, tur=k) for k, v in aliens.items()]
        return [wave([[[str(u.get('tur')), u.get('adet', 5)] for u in aliens]]) for _ in range(4)]

    def finish(self, bot, reached, total, duration, rng):
        aliens = self.L['alien_spawns']
        aliens = aliens if isinstance(aliens, list) else list(aliens.values())
        key = sum((u.get('anahtar') or 0) * u.get('adet', 5) * 0.3 for u in aliens if isinstance(u.get('anahtar'), (int, float)))
        if key:
            grant_list(bot, [['resource_key_labyrinth', int(key * reached)]], rng)


def _combined(waves):
    ehp = sum(d[0] for d in waves)
    dps = max([d[1] for d in waves] or [0])
    reward = {}
    for d in waves:
        for k, v in d[2].items():
            reward[k] = reward.get(k, 0) + v
    return ehp, dps, reward


def _gates():
    import event_gate as EKP
    return [EventGate(k, g) for k, g in EKP.GATES.items()]


MODES = []


def modes():
    if not MODES:
        MODES.extend(_gates() + [Voyagers(), Trinity(), Astral(), Ebl(), Echoes(), Low(), VortexGreed(), Mimesis(),
                                    WorldBoss(), Apotheosis(), Labyrinth()])
    return MODES


# ------------------------------------------------------------------------------------------------------------ koşu
def estimate(bot, mod, waves=None):
    """Koşu tahmini -> (ulaşılan dalga, toplam, süre sn, öldürme ödülleri). Kapıdaki yöntem: en iyi cephane, aynı anda vuranlar,
    dalga arasında onarım; ölümler can hakkını bitirince durur; süre sınırı varsa orada biter."""
    from . import weapons as WP
    waves = mod.waves(bot) if waves is None else waves
    d = bot.value()
    s = WP.stock(bot)
    multiplier = max([WP.multiplier(c) for c in ('ammunition_laser_ucb-100', WP.MCB50, WP.MCB25, WP.LCB) if s.get(c, 0) > 1000] or [1])
    dps = max(1.0, d['dps'] * multiplier * 1.15)
    duration = death = 0.0
    reward = {}
    reached = 0
    for ehp, incoming, rew in waves:
        t = ehp / dps
        if mod.time_limit and duration + t > mod.time_limit:
            break
        death += t * incoming / max(1.0, d['ehp'] * 3)
        if death >= mod.hp:
            break
        duration += t
        reached += 1
        for k, v in rew.items():
            reward[k] = reward.get(k, 0) + v
    return reached, len(waves), duration, reward


def value(bot, mod):
    """Modun bota beklenen değeri (kredi/saat kabaca): öldürme ödülleri ve bitiş, ilerleme payıyla; geçemeyeceği mod 0."""
    ul, top, duration, reward = estimate(bot, mod)
    if top == 0 or ul == 0 or (mod.tip in ('full', 'run') and ul < top * 0.5):
        return 0.0                                       # ilerlemeyle ödül vermeyen modun yarısını geçemiyorsa girmez
    v = reward.get('kredi', 0) + reward.get('uridyum', 0) * 100 + reward.get('ep', 0) * 0.3 + reward.get('onur', 0) * 3
    v += 200000 * ul / top                                    # bitiş ödülleri (eşya, kaynak, anahtar) kabaca
    return v / max(600.0, duration) * 3600


def candidates(bot, now):
    """Şu an girilebilecek modlar (açık, koşulu sağlanan, en az ilk dalgayı geçeceği)."""
    if not bot.permission.get('modes', True):
        return []
    out = []
    for m in modes():
        try:
            if m.is_open(now) and m.can_enter(bot, now) and m.affordable(bot) and value(bot, m) > 0:
                out.append(m)
        except (KeyError, TypeError, ValueError, IndexError):
            continue                                       # verisi beklenmedik biçimde olan mod: atla
    return out


def run(bot, mod, rng=random):
    """Koşunun sonucu -> (ulaşılan, toplam, süre, öldürme ödülleri); süre gerçek koşu payıyla uzatılır."""
    waves = mod.waves(bot)
    ul, top, duration, reward = estimate(bot, mod, waves)
    if ul < top and rng.random() < 0.3:
        ul = min(top, ul + 1)                               # şans
    return ul, top, duration * rng.uniform(1.1, 1.5) + 90, reward


# ------------------------------------------------------------------------------------------------------------ pasif
def dispatch(bot, now):
    """Dispatch: zengin bot toplayıcı gönderir (kredi ücreti), süresi dolunca listesinden 4 ödül (taban adetlerle)."""
    if not bot.permission.get('modes', True) or bot.level < 10:
        return
    st = state(bot, 'dispatch')
    if st.get('bitis') and now >= st['bitis']:
        t = DISP['collectors'][st['tur']]
        entries = DISP['rewards'].get(t['code']) or []
        multiplier = 1 + (t.get('kademe', 1) - 1) * DISP.get('tier_increase', 0.5)
        if _tech().is_active('dispatch_day', now):
            multiplier *= DISP.get('dispatch_day_multiplier', 2)
        for loot in random.sample(entries, min(DISP['reward_count'], len(entries))):
            n = DISP['base_count'].get(loot, 1)
            grant_list(bot, [[loot, n if loot in DISP['single'] else int(n * multiplier)]])
        st.pop('bitis')
        bot.ist('dispatch')
    if st.get('bitis'):
        return
    eligible = [(k, t) for k, t in DISP['collectors'].items()
             if all(bot.k[{'currency_credits': 'kredi', 'currency_uridium': 'uridyum'}.get(p, 'kredi')] > n * (3 + 3 * bot.o('frugality'))
                    for p, n in t.get('fee', {}).items())]
    if not eligible:
        return
    k, t = max(eligible, key=lambda x: x[1].get('kademe', 1))
    for p, n in t.get('fee', {}).items():
        bot.pay('C' if p == 'currency_credits' else 'U', n)
    st.update(tur=k, bitis=now + t['sure_sn'])


def galaxy_trek(bot, now):
    """Galaxy Trek: etkinlik sürerken günlük FTL anahtarlarıyla keşif (olaylar tablosundan ödül)."""
    g = EX['galaxy_trek']
    if not bot.permission.get('modes', True) or not _tech().is_active('galaxy_trek', now):
        return
    st = state(bot, 'galaxy_trek')
    if st.get('gun') == day():
        return
    st['gun'] = day()
    events = g.get('events')
    rows = events if isinstance(events, list) else list((events or {}).values())
    for _ in range(int(g.get('daily', 10)) // max(1, int(g.get('cost', 1)))):
        r = random.choice(rows) if rows else None
        if isinstance(r, dict):
            grant_list(bot, r.get('rewards') or r.get('esyalar') or [])
        elif isinstance(r, list) and r and isinstance(r[0], str):
            grant_list(bot, [r[:2]])
    bot.ist('galaxy_trek')


def passive(bot, now):
    dispatch(bot, now)
    galaxy_trek(bot, now)
