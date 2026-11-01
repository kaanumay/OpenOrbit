"""Bot klanlarının Klan Savaş İstasyonları (kullanıcı isteği 2026-10-31): botlar varken sahte rakip yok (cbs.botlu), asteroitler boş
açılır; bot klanlarının liderleri (ve kurma hakkı olan subaylar) gerçekten yarışır. En hızlı gelişen klan en iyi yeri kapar.

  hedef      en değerli boş asteroit (4-x, X-BL, X-5..7, X-3/4; kendi firmasının haritası öne), önde giden rakip çok öndeyse başkası
  modül      kasadan, bütçenin KSİ payıyla (klan_yonetim.harcanabilir) alınır; fiyatlar cbs.json bot_klan (uyarlama: oyunda
             modüller Assembly ile üretilir). Takım liderin tarzına göre: saldırgan lazer/roket, hırslı ve barışçı booster, temkinli
             onarım modülü
  yarış      asteroide 50 sn'de bir modül (cbs.json kurulum_sn); ilerleme a['yaris'] (pencerede "önde giden klan"). İlk 10/10 olan
             kurar (cbs.bot_kur); oyuncu önce kurarsa ya da başka klan kazanırsa modüller stoğa döner
  gelişme    kurulu istasyonda modüller seviye seviye (0-15) yükselir, yıkılan uydu bütçe yettikçe onarılır: her istasyon başka
  savunma    oyuncu vurunca lider çevrimiçi üyeleri istasyona yollar (klan_emir 'git'), duyuru ve toplu posta, saldırana kin
Klanın kaydında k['ksi'] = {hedef, plan, stok: [modül], son_*}; asteroidin kaydı ortak profilde (cbs.ortak)."""
import random, time

import cbs as CB
import map_links as H
import clan as KL
from . import clan_management as CMG

DEFAULTS = {'price': {}, 'level_multiplier': 0.35, 'repair_ratio': 0.4, 'upgrade_sec': 3600, 'build_min': [5, 30],
              'defense_sec': 1800}                     # asıl değerler cbs.json bot_klan
WEAPONS = ('module_ltm-lr', 'module_ltm-mr', 'module_ltm-hr', 'module_ram-la', 'module_ram-ma')
BOOSTER = ('module_honm-1', 'module_xpm-1', 'module_dmgm-1')


def setting():
    return dict(DEFAULTS, **(CB.D.get('bot_clan') or {}))


def is_open():
    return CB.with_bots()


def price(loot, level=0):
    a = setting()
    f = a['price'].get(loot, 1000000)
    return int(f if level <= 0 else f * a['level_multiplier'] * level)


def _registry():
    """(ortak profil, asteroitler) ya da (None, None): ortak kayıt bir oturumda kurulmuş olmalı (cbs.Cbs.asts: embed)."""
    h = CB.shared()
    d = (h.d.get('cbs') or {}) if h is not None else {}
    return (h, d['asteroids']) if h is not None and d.get('shared') and 'asteroids' in d else (None, None)


def cbs(k):
    with KL.LOCK:
        s = k.setdefault('ksi', {})
        s.setdefault('stock', [])
        return s


def stations(k):
    """Klanın kurulu istasyonlarının adları."""
    h, asteroids = _registry()
    return [CB.ASTEROIDS[int(aid)]['name'] for aid, a in (asteroids or {}).items()
            if a.get('state') == 'built' and a.get('clan') == k['id'] and int(aid) in CB.ASTEROIDS]


def _mine(asteroids, k):
    return {int(aid): a for aid, a in asteroids.items() if a.get('clan') == k['id'] and a.get('state') in ('building', 'built')}


def need(k):
    """Sıradaki KSİ hedefinin kalan bedeli: istasyonu yoksa eksik modüllerin fiyatı, varsa bir sonraki yükseltme."""
    s = k.get('ksi') or {}
    h, asteroids = _registry()
    if asteroids is None:
        return 0
    own = _mine(asteroids, k)
    if not own:
        owner = [m['loot'] for m in s.get('stock', [])]
        race = (asteroids.get(str(s.get('target'))) or {}).get('race', {}).get(str(k['id']), {}).get('modules', [])
        owner += [m['loot'] for m in race]
        missing = list(s.get('plan') or [])
        for l in owner:
            if l in missing:
                missing.remove(l)
        return sum(price(l) for l in missing)
    y = _to_upgrade(next(iter(own.values())), None)
    return price(y['loot'], y['level'] + 1) if y else 0


def summary(k):
    """Ajanın gözlemi: klanın istasyonları (modüller ve seviyeleri), yarışı, stoğu, sıradaki bedel ve boş asteroitler."""
    if not is_open():
        return ''
    h, asteroids = _registry()
    if asteroids is None:
        return ''
    row = []
    for aid, a in _mine(asteroids, k).items():
        mods = [y.get('module') for y in a['slots'].values() if y.get('module')]
        row.append('Your battle station %s (%s): %s, deflector %s, modules %s.' % (
            CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map']), 'building' if a['state'] == 'building' else 'built',
            'on' if (a.get('deflector') or {}).get('on') else 'off',
            ', '.join('%s L%d%s' % (CB.MODS[m['loot']]['code'], m['level'] + 1, ' destroyed' if m['can'] <= 0 else '') for m in mods)))
    s = k.get('ksi') or {}
    if s.get('target'):
        a = asteroids.get(str(s['target'])) or {}
        ours = len(((a.get('race') or {}).get(str(k['id'])) or {}).get('modules') or ())
        en = CB.race_leader(a)
        row.append('Building race at %s: you have %d/10 modules%s.' % (CB.ASTEROIDS[int(s['target'])]['name'], ours,
                                                                       ', leader %s %d/10' % (en[0], en[1] * 10) if en and en[0] != k['name'] else ''))
    if s.get('stock'):
        row.append('Modules in clan stock: %s.' % ', '.join(sorted(CB.MODS[m['loot']]['code'] for m in s['stock'])))
    row.append('Next station cost: about %s credits (the station share of the budget pays it).' % '{:,}'.format(need(k)))
    empty = sorted(((value(aid, k), aid) for aid in CB.ASTEROIDS if (asteroids.get(str(aid)) or {}).get('state', 'vacant') == 'vacant'), reverse=True)[:6]
    if empty:
        row.append('Free asteroids (best first; klan_istasyon to target one): %s.' % ', '.join(
            '%s (%s)' % (CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map'])) for _, aid in empty))
    return '\n'.join(row)


def set_target(k, name, b):
    """Ajanın seçtiği asteroit (adıyla): boşsa hedef olur; önceki hedefteki modüller stoğa döner."""
    h, asteroids = _registry()
    aid = next((i for i, a in CB.ASTEROIDS.items() if a['name'].lower() == str(name or '').strip().lower()), None)
    if asteroids is None or aid is None or (asteroids.get(str(aid)) or {}).get('state', 'vacant') != 'vacant':
        return False
    s = cbs(k)
    old = s.get('target')
    if old and old != aid:
        a = asteroids.get(str(old)) or {}
        with h.lock:
            r = (a.get('race') or {}).pop(str(k['id']), None)
            a['version'] = a.get('version', 0) + 1
        if r:
            CB.refund_race(k['id'], r.get('modules'))
    s['target'] = aid
    s['plan'] = s.get('plan') or build_plan(b)
    return True


# ------------------------------------------------------------------------------------------------------------ karar
def value(aid, k):
    """Asteroidin klana değeri: 4-x en değerli (PvP bölgesi, her firmaya açık), sonra X-BL, X-5..7, X-3/4; kendi firmasının haritası
    öne, düşman firmanınki geri."""
    m = int(CB.ASTEROIDS[aid]['map'])
    name = H.name(m)
    on, _, last = name.partition('-')
    v = 3.0 if on == '4' else 2.5 if last.upper() == 'BL' else 2.0 if last in ('5', '6', '7') else 1.2
    owner = H.company(m)
    firma = int(k.get('company') or 0) or int((k['members'].get(k['leader']) or {}).get('company') or 0)
    return v + (0.5 if owner and owner == firma else -0.6 if owner else 0)


def build_plan(b):
    """Takım (merkez + 8 uydu) liderin tarzıyla: saldırgan lazer/roket, hırslı ve barışçı booster, temkinli onarım."""
    aggression = b.o('aggression')
    satellite = []
    if b.r.random() < 0.35 + 0.45 * (1 - b.o('risk')):
        satellite.append('module_repm-1')
    for x in BOOSTER:
        if b.r.random() < 0.12 + 0.55 * b.o('ambition') * (1 - aggression):
            satellite.append(x)
    weight = (2 + 3 * aggression, 2 + aggression, 1 + aggression, 1 + 2 * (1 - b.o('risk')), 1.5)
    while len(satellite) < CB.SLOTS - 2:
        satellite.append(b.r.choices(WEAPONS, weight)[0])
    b.r.shuffle(satellite)
    return ['module_hulm-1', 'module_defm-1'] + satellite


def _new_module(loot):
    hp = CB.level_value(CB.MODS[loot]['can'], 0)
    return {'loot': loot, 'level': 0, 'can': hp, 'kalkan': int(hp * CB.D['shield_ratio'])}


def pick_target(k, asteroids, now):
    """Yeni hedef: klanın istasyon sınırı dolmadıysa en değerli boş asteroit; önde giden rakip 6/10'u geçtiyse ve bizim yoksa o
    asteroit atlanır (yetişemez)."""
    s = cbs(k)
    limit = 1 + (len(k['members']) >= 20 and k['treasury'] > 40000000)
    if len(_mine(asteroids, k)) >= limit:
        return None
    candidate = []
    for aid in CB.ASTEROIDS:
        a = asteroids.get(str(aid)) or {}
        if a.get('state', 'vacant') != 'vacant':
            continue
        ours = len(((a.get('race') or {}).get(str(k['id'])) or {}).get('modules') or ())
        en = max([len(r.get('modules') or ()) for c, r in (a.get('race') or {}).items() if int(c) != k['id']] + [0])
        player = len(a.get('slots') or {})
        if max(en, player) >= 6 and ours < max(en, player):
            continue
        candidate.append((value(aid, k) - 0.12 * max(en, player) + random.uniform(0, 0.4), aid))
    if not candidate:
        return None
    s['target'] = max(candidate)[1]
    return s['target']


def _to_upgrade(a, b):
    """Kurulu istasyonda yükseltilecek modül (en düşük seviyeli; saldırgan lider silahları, temkinli merkezi önce)."""
    candidates = []
    for s, y in a.get('slots', {}).items():
        m = y.get('module')
        if not m or m['can'] <= 0 or m['level'] >= 15:
            continue
        md = CB.MODS[m['loot']]
        on = 0.0
        if b is not None:
            on = (0.6 * b.o('aggression') if md.get('weapon') else 0) + (0.6 * (1 - b.o('risk')) if md['center'] else 0)
        candidates.append((m['level'] - on, int(s), m))
    return min(candidates, key=lambda x: x[:2])[2] if candidates else None


def _pay(k, area, cost):
    if cost <= 0 or CMG.spendable(k, area) < cost:
        return False
    with KL.LOCK:
        k['treasury'] -= cost
        k['treasury_log'].insert(0, {'balanceUserId': 0, 'credits': -cost, 'insertDate': KL.stamp(), 'toName': '', 'fromName': '',
                                   'moneyType': 'cbs', 'reason': 'battle station'})
        del k['treasury_log'][200:]
    KL.changed(k)                                        # kasa üyelerin penceresinde ve klanlar.json'da
    return True


def to_stock(k, d):
    """Yıkılan istasyonun ya da çıkarılan modüllerin (bekleyen '@klan:<kimlik>') klanın stoğuna geçmesi."""
    pending = (d.get('pending') or {}).pop('@klan:%d' % k['id'], None)
    if pending:
        cbs(k)['stock'].extend(pending.values())


def race_step(y, b, k, h, asteroids, now):
    """Hedef asteroitte bir adım: stokta sıradaki modül varsa takar (50 sn'de bir), yoksa bütçe yettikçe alır; 10/10 olunca kurar."""
    s = cbs(k)
    aid = s.get('target')
    if aid and str(aid) not in asteroids:
        with h.lock:
            asteroids.setdefault(str(aid), {'state': 'vacant', 'slots': {}})
    a = asteroids.get(str(aid)) if aid else None
    if a is None or a.get('state', 'vacant') != 'vacant':
        if a is not None and a.get('clan') == k['id']:
            return                                       # kazandık: kuruluyor ya da kurulu
        if aid:
            b.event('cbs_lost', now, station=CB.ASTEROIDS[int(aid)]['name'])
        s['target'] = None
        aid = pick_target(k, asteroids, now)
        if aid is None:
            return
        with h.lock:
            a = asteroids.setdefault(str(aid), {'state': 'vacant', 'slots': {}})
        s['plan'] = build_plan(b)
        CMG.announce(b, CMG.kl_of(b), 'clan_announce_cbs_race', station=CB.ASTEROIDS[aid]['name'], map=H.name(CB.ASTEROIDS[aid]['map']))
        b.event('cbs_target', now, station=CB.ASTEROIDS[aid]['name'])
    r = (a.get('race') or {}).get(str(k['id'])) or {'modules': [], 't': 0}
    equipped = [m['loot'] for m in r['modules']]
    s['plan'] = s.get('plan') or build_plan(b)
    missing = list(s['plan'])
    for l in equipped:
        if l in missing:
            missing.remove(l)
    if not missing:
        minutes = b.r.randint(*setting()['build_min'])
        if CB.bot_build(int(aid), k, r['modules'], minutes, log=y.log):
            s['target'] = None
            b.event('cbs_building', now, station=CB.ASTEROIDS[int(aid)]['name'])
        return
    if now - r.get('t', 0) < CB.D['install_sec']:
        return
    loot = missing[0]
    m = next((x for x in s['stock'] if x['loot'] == loot), None)
    if m is None:
        if not _pay(k, 'ksi', price(loot)):
            return                                       # para birikiyor
        m = _new_module(loot)
    else:
        s['stock'].remove(m)
        if m['can'] <= 0:                                # yıkılıp dönmüş modül: önce onarılır
            if not _pay(k, 'ksi', int(price(loot) * setting()['repair_ratio'])):
                s['stock'].append(m)
                return
            m.update(_new_module(loot), level=m['level'])
            m['can'] = CB.level_value(CB.MODS[loot]['can'], m['level'])
            m['kalkan'] = int(m['can'] * CB.D['shield_ratio'])
            m.pop('ksi', None)                           # taban değerler: panelin KSİ can çarpanına cbs.hp_sync ölçekler
    with h.lock:
        r = a.setdefault('race', {}).setdefault(str(k['id']), {'modules': [], 't': 0})
        r['modules'].append(m)
        r['t'] = now
        a['version'] = a.get('version', 0) + 1
        h.d['cbs']['bot_clans'] = True
        h.dirty = True


def develop(y, b, k, h, asteroids, now):
    """Kurulu istasyonlar: yıkılan uydu onarılır, sonra bir modül bir seviye yükselir (yükseltme_sn'de bir)."""
    s = cbs(k)
    for aid, a in _mine(asteroids, k).items():
        if a.get('state') != 'built' or now - a.get('attack_at', 0) < 600:
            continue
        for y_ in a['slots'].values():
            m = y_.get('module')
            if m and m['can'] <= 0 and _pay(k, 'ksi', int(price(m['loot']) * setting()['repair_ratio'])):
                with h.lock:
                    m['can'] = CB.level_value(CB.MODS[m['loot']]['can'], m['level'])
                    m['kalkan'] = int(m['can'] * CB.D['shield_ratio'])
                    m.pop('ksi', None)
                    a['version'] = a.get('version', 0) + 1
                    h.dirty = True
                return
        if now - s.get('last_upgrade', 0) < setting()['upgrade_sec']:
            continue
        m = _to_upgrade(a, b)
        if m is None or not _pay(k, 'ksi', price(m['loot'], m['level'] + 1)):
            continue
        with h.lock:
            ratio = m['can'] / max(1, CB.hp_max(m))          # ölçekli canın oranı (panelin KSİ can çarpanı)
            m['level'] += 1
            m['can'] = int(CB.level_value(CB.MODS[m['loot']]['can'], m['level']) * min(1.0, ratio))
            m['kalkan'] = int(CB.level_value(CB.MODS[m['loot']]['can'], m['level']) * CB.D['shield_ratio'] * min(1.0, ratio))
            m.pop('ksi', None)
            a['version'] = a.get('version', 0) + 1
            h.dirty = True
        s['last_upgrade'] = now
        b.event('cbs_upgraded', now, module=m['loot'], level=m['level'])
        return


DEFENSE_FIRST = 2                  # saldırı başlar başlamaz yollanan üye sayısı
DEFENSE_WAVE = 1                # sonraki her dalgadaki üye sayısı
DEFENSE_GAP_SEC = 75.0            # dalgalar arası (sn): üsse yavaş yavaş akarlar, sürü olmaz
DEFENSE_LAST_SEC = 90              # saldırı bundan eski ise bitmiş sayılır, sıradakiler yollanmaz


def defense_quota(attackers):
    """Bir saldırıda yollanacak en çok üye: saldıran sayısıyla büyür (tek oyuncuya 5, her ek saldırana 3 daha; en çok 12)."""
    return min(12, 5 + 3 * max(0, attackers - 1))


def _wave(y, b, k, st, game_map, n, now):
    """Sıradaki üyelerden en çok n tanesini istasyonun haritasına yollar (klan_emir 'git') -> yollanan sayısı."""
    from . import clan_orders as CO
    outgoing = 0
    while st['queued'] and outgoing < n and st['sent'] < st['quota']:
        name = st['queued'].pop(0)
        o = y.name_index.get(name.lower())
        if o is None or not (o.online and o.dead_until <= now and o.k.get('clan') == k['id']):
            continue
        if CO.will_obey(o, b.name, True, now) and CO.apply(y, o, {'type': 'git', 'map': game_map}, b.name, None, now)[0] == 'coming':
            outgoing += 1
            st['sent'] += 1
    return outgoing


def defend(y, b, k, asteroids, now):
    """İstasyona oyuncu saldırıyor: haber ve toplu posta (savunma_sn'de bir), lider saldırana kin duyar. Çevrimiçi üyeler hepsi birden
    değil, kademeli yollanır (klan_emir 'git'): ilk SAVUNMA_ILK hemen, kalanı SAVUNMA_ARA_SN'de bir SAVUNMA_DALGA; toplam
    savunma_kota(saldıran sayısı). Saldırı SAVUNMA_SON_SN'den uzun süredir yoksa sıra bırakılır. Bekleyen sıra klanın kaydında
    (k['ksi']['savunma'], klanlar.json): sunucu yeniden başlasa da süren saldırıda kalanlar yollanır."""
    defense_state = cbs(k).setdefault('savunma', {})
    for aid, a in _mine(asteroids, k).items():
        ongoing = now - a.get('last_player', 0) <= DEFENSE_LAST_SEC
        st = defense_state.get(str(aid))
        if st is not None:
            if not ongoing:
                defense_state.pop(str(aid), None)                      # saldırı bitti: sıradakiler yollanmaz
                continue
            if a.get('last_attacker') and a['last_attacker'] not in st['attackers']:
                st['attackers'].append(a['last_attacker'])
                st['quota'] = max(st['quota'], defense_quota(len(st['attackers'])))
            if now >= st['next'] and st['queued']:
                st['next'] = now + DEFENSE_GAP_SEC
                _wave(y, b, k, st, st['map'], DEFENSE_WAVE, now)
            continue
        if not ongoing or now - cbs(k).get('last_defense', 0) < setting()['defense_sec']:
            continue
        cbs(k)['last_defense'] = now
        ist, game_map = CB.ASTEROIDS[aid]['name'], H.name(CB.ASTEROIDS[aid]['map'])
        who = a.get('last_attacker') or ''
        if who:
            b.memory.event(who, 'insult', now, multiplier=1.0)
        kl = CMG.kl_of(b)
        CMG.announce(b, kl, 'clan_announce_cbs_attack', station=ist, map=game_map)
        if KL.right(b.profile, 'roundmail'):
            CMG.bulk_mail(b, kl, 'clan_mail_cbs', station=ist, map=game_map)
        members = [o for o in y.bots if o.k.get('clan') == k['id'] and o.online and o.dead_until <= now]
        random.shuffle(members)
        st = defense_state[str(aid)] = dict(map=game_map, queued=[o.name for o in members], sent=0, quota=defense_quota(1),
                                  attackers=[who] if who else [], next=now + DEFENSE_GAP_SEC)
        outgoing = _wave(y, b, k, st, game_map, DEFENSE_FIRST, now)
        y.log('   botlar: [%s] %s istasyonu saldırı altında (%s), %d üye savunmaya (kalan %d kademeli)'
              % (k['tag'], ist, who or '?', outgoing, len(st['queued'])))
        b.event('cbs_defense', now, station=ist, attacker=who)
        return


def announce_status(b, k, asteroids, now):
    """Kuruldu / yıkıldı haberleri (önceki bakıştan bu yana değişenler)."""
    s = cbs(k)
    current_time = {str(aid): a.get('state') for aid, a in _mine(asteroids, k).items()}
    once = s.get('seen') or {}
    kl = None
    for aid, d in current_time.items():
        if d == 'built' and once.get(aid) != 'built':
            kl = kl or CMG.kl_of(b)
            CMG.announce(b, kl, 'clan_announce_cbs_built', station=CB.ASTEROIDS[int(aid)]['name'], map=H.name(CB.ASTEROIDS[int(aid)]['map']))
            b.event('cbs_built', now, station=CB.ASTEROIDS[int(aid)]['name'])
    for aid, d in once.items():
        if d == 'built' and aid not in current_time and int(aid) in CB.ASTEROIDS:
            kl = kl or CMG.kl_of(b)
            CMG.announce(b, kl, 'clan_announce_cbs_destroyed', station=CB.ASTEROIDS[int(aid)]['name'], map=H.name(CB.ASTEROIDS[int(aid)]['map']))
            b.event('cbs_destroyed', now, station=CB.ASTEROIDS[int(aid)]['name'])
    s['seen'] = current_time


def clean_up(y, h, asteroids):
    """Dağılmış klanların istasyonları yıkılır, yarışları ve bekleyen modülleri silinir."""
    d = h.d['cbs']
    for aid, a in list(asteroids.items()):
        if a.get('owner') == 'bot' and a.get('clan') not in KL.CLANS and a.get('state') in ('building', 'built'):
            CB.bot_demolish(int(aid), log=y.log)
        race = a.get('race') or {}
        for cid in [c for c in race if int(c) not in KL.CLANS]:
            with h.lock:
                race.pop(cid, None)
                a['version'] = a.get('version', 0) + 1
    for o in [o for o in (d.get('pending') or {}) if o.startswith('@klan:') and int(o[6:]) not in KL.CLANS]:
        d['pending'].pop(o, None)


def manage(y, b, k, kl, now):
    """Lider (ya da kurma hakkı olan subay) sosyal turunda: savunma, yarış adımı, gelişme, haberler."""
    if not is_open() or not kl.right('battle_station_build', k):
        return
    h, asteroids = _registry()
    if h is None:
        return
    if CMG.is_due(k, 'cbs_cleanup', now, 600):
        clean_up(y, h, asteroids)
    to_stock(k, h.d['cbs'])
    defend(y, b, k, asteroids, now)
    announce_status(b, k, asteroids, now)
    race_step(y, b, k, h, asteroids, now)
    develop(y, b, k, h, asteroids, now)
