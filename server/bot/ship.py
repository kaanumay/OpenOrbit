"""Somut botlar: oyuncunun haritasındaki botların gemisi (BotGemi, dunya.World.npcs içinde) ve taktik davranışı.

Bot uzaylı tablosunda durur ama istemciye oyuncu gibi görünür (ShipCreateCommand npc=False, firma, rütbe, klan etiketi, dronlar):
görüş, seçme, oyuncunun lazeri/roketi/yetenekleri, ortak harita paylaşımı dünyanın uzaylı yolundan kendiliğinden çalışır. Ayrıldığı
yerler (world.py kancaları):
  ship_create   -> gorunum         oyuncu görünümü
  think         -> dusun           taktik: portala git, kaç, karşılık ver, PvP, uzaylı avla, dinlen
  think (NPC)   -> npc_bota        bot vurduğu uzaylı ona döner ve ateş eder
  laser_start   -> saldiri_hatasi  oyuncunun saldırı kuralları (DMZ, başlangıç haritasında kendi firması)
  hit_npc       -> vuruldu         aynı kurallar + bot saldıranı hatırlar
  kill          -> olduruldu       PvP ödülü (oyuncu_savas.on_kill), bot ölür, üste döner
  hero_death    -> oyuncu_oldu     botun zaferi (onur, hafıza)
  step (lider)  -> tick            yöneticinin bu haritadaki botlarıyla eşitleme (saniyede bir)
  stop          -> ayril           gemiler kaldırılır, botlar soyut benzetime döner

Taktik düşünme insan tepki süresiyle (kişiliğin tepki_sn'si) aralıklı; ateş 1,1 sn'de bir. Savaş görselleri yalnız iki ucu da
tanıyan istemcilere gider (görüş dışındaki bot uzaylı keserken gönderilmez).
"""
import math, random, time

import world as WD
import map_links as H
from legacy_protocol import legacy
from . import catalog as K
from . import abstract_sim as S
from . import appearance as GR
from . import society as T
from . import manager as MGR
from .goals.pvp import order_grudge

CARRIER = next(iter(WD.CFG['tipler']))       # NPC.__init__ için var olan bir tür (sonra botun değerleriyle değiştirilir)
LASER_RANGE = WD.COMBAT['laser_range']
COMBAT_SEC = 8.0                                 # son hasardan bu kadar sonra yenilenir
REGEN_RATE = 0.02                               # savaş dışında saniyede azami can+kalkanın payı
JUMP_SEC = H.JUMP_DELAY_SEC
ARRIVAL_SEC = 10.0                 # atlayan bot bu süre içinde gövdelenirse varış portalında doğar (sonra uçup gitmiştir)
COMBAT_INTERVAL = WD.COMBAT['laser_interval_sec']


class BotShip(WD.NPC):
    def __init__(self, bot, x, y, now=None):
        WD.NPC.__init__(self, bot.uid, CARRIER, x, y)
        self.bot = bot
        self.tip = 'bot'
        self.summoned = True                    # uzaylı gibi yeniden doğmaz (botu yönetici doğurur)
        self.target = None                       # ateş ettiği (kimlik)
        self.fire = False
        self.attacker = {}                      # kimlik -> son vuruş anı
        self.last_damage = 0.0
        self.portal_time = 0.0
        self.movement = None                     # son gönderilen hedef nokta
        self.intent_time = 0.0                      # PvP başlatma kararının son anı
        self.spawn = now or time.time()
        self.next_think = self.spawn + random.uniform(0.3, 1.5)
        self.takeoff = random.triangular(1.5, 18, 4)     # doğunca yola hemen çıkmaz: herkes aynı anda tek sıra kalkmasın
        self.route = None                        # (hedef, [ara noktalar]): uzun yolda eğri rota (_rota)
        self.approach_points = {}                         # portal -> yanaşma noktası (portalın çevresinde, bota özgü)
        self.next_shot = 0.0
        d = bot.value()
        self.d = {}
        self.refresh()
        self.hp, self.shield = d['can'], d['kalkan']

    def refresh(self):
        """Donanım değişti: görünüm, değerler, dronlar."""
        b = self.bot
        d = b.value()
        e = b.k['ekip']
        self.model = e['gemi']
        self.d = dict(ad=b.name, hp=int(d['can']), kalkan=int(d['kalkan']), hasar=0, hiz=int(d['hiz']), saldirgan=False,
                      odul=dict(ep=0, onur=0, kredi=0, uridyum=0), kargo={}, npc_kimlik=0,
                      genisleme=3 if d['lazer'] >= 12 else 2 if d['lazer'] >= 6 else 1, bot=True)
        self.behavior = {}
        self.hp, self.shield = min(self.hp, d['can']), min(self.shield, d['kalkan'])
        # dronlar yalnız ek_gorunum'dan (gorunum.mesajlar: formasyon, dron seviyesi, tasarımlar); burada formasyonu 0 olan ikinci bir
        # dizgi show()'da ondan sonra gidip formasyonu eziyordu (oyuncu bildirimi 2026-11-01: hiçbir bot formasyon kullanmıyor)
        self.images = {}

    def speed(self):
        return self.d['hiz']


# ------------------------------------------------------------------------------------------------------------ görünüm
def appearance(w, n):
    b = n.bot
    x, y = n.mover.pos(time.time())
    T.profile(b)
    pl = b.profile.d['pilot']
    return ('ShipCreateCommand', dict(
        userId=n.id, typeId=GR.tip(b), expansionStage=n.d['genisleme'], userName=b.name, x=int(x), y=int(y),
        clanTag='CM' if b.__dict__.get('moderator') else pl.get('clanTag', ''),        # sohbet moderatörü (bot/moderasyon.py)
        factionId=b.firma, clanId=int(pl.get('clanId') or 0), dailyRank=pl.get('dailyRank', 1), warnBox=False,
        clanDiplomacy=WD.mod('ClanRelationModule', type=relation(w, b)), galaxyGatesDone=GR.rings(b), useSystemFont=False, npc=False,
        cloaked=False, motherShipId=0, positionIndex=0, designSet='', modifier=[],
        minimapStrategyModule=WD.mod('MinimapStrategyModule', minimapStrategy=0), specialNpcType=''))


def extra_look(n):
    return GR.messages(n)


def relation(w, b):
    """Klanlar arası ilişki (ClanRelationModule.type: 1 ittifak, 2 saldırmazlık, 3 savaş) ya da 0."""
    try:
        import clan as KL
        return KL.relation(w.p, T.profile(b))
    except Exception:
        return 0


# ------------------------------------------------------------------------------------------------------------ eşitleme
def tick(w, now):
    """Saniyede bir: yöneticinin bu haritadaki çevrimiçi, yaşayan, yoldan çıkmamış botları gemi olarak var olur; ayrılanlar kalkar."""
    y = MGR.ACTIVE
    if y is None or now < getattr(w, '_bot_t', 0):
        return
    w._bot_t = now + 1.0
    try:
        m = int(w.map_id)
    except ValueError:
        return
    if is_gate_world(w):
        return gate_tick(w, now, y)
    with y.lock:
        wanted = {b.uid: b for b in y.on_map.get(m, ()) if b.online and b.dead_until <= now
                   and now - b.__dict__.get('in_gate', 0) > 5}           # oyuncuyla kapıdaki bot başka haritada görünmez
    var = {uid: n for uid, n in w.npcs.items() if n.bot is not None}
    msgs = []
    for uid, n in var.items():
        if uid not in wanted:
            msgs += remove(w, n)
    limit = y.setting('somut_en_cok', 40) or 9999
    count = len(var) - sum(1 for u in var if u not in wanted)
    if len(wanted) > limit:                             # sınır doluysa: sana yakın, seninle geçmişi olan, grubundaki botlar önce
        hx, hy = w.hero_pos(now)
        name = str(w.p.d['pilot'].get('userName', '')).lower()

        def priority(b):
            x, yy = b.k.get('x') or 0, b.k.get('y') or 0
            is_acquaintance = name in (b.k.get('hafiza') or {})
            return (not w.is_group_member(b.uid), not is_acquaintance, math.hypot(x - hx, yy - hy))
        wanted = dict(sorted(wanted.items(), key=lambda kv: priority(kv[1])))
    for uid, b in wanted.items():
        if b.body is not None and (not b.body.alive or w.npcs.get(b.body.id) is not b.body):
            b.body = None                                # dışarıdan silinmiş gemi (hata ayıklama, çöken dünya): bot donmasın
        if uid in var or count >= limit or b.body is not None:
            continue
        x, yy = spawn_point(w, b)
        n = BotShip(b, x, yy, now)
        if b.__dict__.pop('in_place_repair', None):       # yerinde tamir: canın %10'u, kalkansız, 10 sn koruma (oyuncununki gibi)
            n.hp, n.shield = max(1, int(n.hp * K.ITEMS['death_screen']['in_place_hp_ratio'])), 0
            n.immune_until = now + K.ITEMS['death_screen']['in_place_protection_sec']
        w.npcs[n.id] = n
        b.body = n
        b.k['x'], b.k['y'] = x, yy
        count += 1
    if msgs:
        w.send(msgs)


def is_gate_world(w):
    """Kapı ya da örnek harita (Galaksi Kapısı, Hades, LoW, QZ, etkinlik kapıları): olağan harita değil."""
    try:
        m = int(w.map_id)
    except ValueError:
        return True
    return m not in K.MAPS or getattr(w, 'gate', None) is not None and bool(getattr(w.gate, 'key', None)) \
        or getattr(w, 'low', None) is not None


def gate_tick(w, now, y):
    """Kapı dolgusu (oyuncu isteği 2026-10-31): kahramanın grubundaki botlar kapıya onunla girer (kapının yanında doğar), grubun
    hedefini (Grup) izleyip uzaylılara ateş eder; kendi kapısında ya da modunda olan, ölü ya da çevrimdışı bot gelmez. İzin
    'kapi_dolgu'; kapalıysa kapıda bot yok (eskisi gibi)."""
    import group as GR
    wanted = {}
    if y.permission('kapi_dolgu') and not w.hero_dead:
        g = GR.group_of(w.hid)
        with y.lock:
            for b in y.bots:
                if (g is not None and b.uid in g.members and b.online and b.dead_until <= now
                        and (b.target is None or b.target.name not in ('kapi', 'mod', 'duello'))):
                    wanted[b.uid] = b
    msgs = []
    for uid, n in [(u, n) for u, n in w.npcs.items() if n.bot is not None]:
        if uid not in wanted:
            msgs += remove(w, n)
    hx, hy = w.hero_pos(now)
    for uid, b in wanted.items():
        b.in_gate = now
        if b.target is None or b.target.name != 'grup':
            from . import brain as BR
            BR.force(b, 'grup', pay=2.0, duration=3600, now=now)
        if b.body is not None and (not b.body.alive or w.npcs.get(b.body.id) is not b.body):
            b.body = None
        if uid in w.npcs or b.body is not None:
            continue
        a = random.uniform(0, 2 * math.pi)
        x, yy = int(hx + math.cos(a) * random.uniform(150, 400)), int(hy + math.sin(a) * random.uniform(150, 400))
        x, yy = max(300, min(w.map_w - 300, x)), max(300, min(w.map_h - 300, yy))
        n = BotShip(b, x, yy, now)
        w.npcs[n.id] = n
        b.body = n
        b.event('kapiya_girdi', kapi=str(getattr(getattr(w, 'gate', None), 'key', '') or w.map_id))
    if msgs:
        w.send(msgs)


def spawn_point(w, b):
    arrival = getattr(b, 'arrival', None)
    b.arrival = None
    # portalda yalnız az önce atlayan doğar: oyuncu yokken atlayıp soyut kalanlar oyuncu gelince hep birlikte portaldan çıkıyordu
    # (oyuncu bildirimi: 2-1'de portalda bekleyip 2-2'ye geçince 10-20 bot oyuncuyla aynı anda portaldan çıktı)
    if arrival is not None and time.time() - arrival[1] < ARRIVAL_SEC:
        gx, gy = H.arrival(arrival[0], int(w.map_id), b.firma)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(80, 280)      # portalın çevresinde dağınık (üst üste değil)
        return int(gx + math.cos(a) * r), int(gy + math.sin(a) * r)
    x, y = b.k.get('x') or 0, b.k.get('y') or 0
    if 300 < x < w.map_w - 300 and 300 < y < w.map_h - 300:
        return int(x), int(y)
    s = w.station
    if s and s.get('type') == b.firma:          # yeni giren ya da üste dönen: kendi istasyonunun çevresinde (gerçek oyundaki gibi)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(250, 1300)
        return (int(max(400, min(w.map_w - 400, s['posX'] + math.cos(a) * r))),
                int(max(400, min(w.map_h - 400, s['posY'] + math.sin(a) * r))))
    return w.random_spot()


def remove(w, n):
    """Gemi haritadan kalkar (çıkış, atlama, ölüm sonrası): konum kayda, bot soyut benzetime."""
    n.alive = False
    b = n.bot
    x, y = n.mover.pos(time.time())
    b.k['x'], b.k['y'] = int(x), int(y)
    if b.body is n:
        b.body = None
    b.last_abstract = time.time()
    return w.remove_npc(n) + ([('AttackAbortLaserCommand', {'uid': n.id})] if n.fire else [])


def detach(w):
    """Dünya duruyor: ortak haritada başka oyuncu kalmadıysa gemiler kaldırılır (harita durumu saklanmadan önce)."""
    if w.shared is not None and any(o is not w and o.running for o in w.shared.members):
        return
    with w.lock:
        for n in [n for n in w.npcs.values() if n.bot is not None]:
            remove(w, n)


# ------------------------------------------------------------------------------------------------------------ yardımcılar
def _position(w, uid, now):
    n = w.npcs.get(uid)
    if n is not None:
        return n.mover.pos(now) if n.alive else None
    o = _player(w, uid)
    return o.hero_pos(now) if o is not None else None


def _player(w, uid):
    """Kimliği uid olan kahramanın dünyası (bu dünya ya da ortak haritadaki öteki oyuncu) ya da None."""
    if uid == w.hid:
        return w
    if w.shared is not None:
        return next((o for o in w.shared.members if o.hid == uid and o.running), None)
    return None


def _broadcast(w, msgs, *uids):
    """Savaş görseli: bu dünyanın istemcisi iki ucu da tanıyorsa ona; ortak haritada öteki oyunculara (yansit kendisi süzer)."""
    if not msgs:
        return
    if all(w.knows(u) for u in uids):
        w.send(msgs)
    elif w.shared is not None:
        w.shared.mirror(w, msgs)


def _go_to(w, n, x, y, now, threshold=80):
    x = max(200, min(w.map_w - 200, x))
    y = max(200, min(w.map_h - 200, y))
    h = n.movement
    if h is not None and math.hypot(h[0] - x, h[1] - y) < threshold and n.mover.t1 > now:
        return
    n.movement = (x, y)
    ms = n.mover.go(x, y, n.speed(), now)
    w.send([('MoveCommand', dict(userId=n.id, x=int(x), y=int(y), timeToTarget=ms))])


def _waypoints(w, n, sx, sy, x, y):
    """Uzun yolun ara noktaları: rotaya dik, hafif bir yay (sinüs) üstünde; yönü ve genişliği bota ve yolculuğa göre tohumlu (her
    botun yolu başka, aynı yolculukta değişmez). Kısa yol doğrudan."""
    d = math.hypot(x - sx, y - sy)
    k = 0 if d < 1500 else 1 if d < 3500 else 2 if d < 7000 else 3
    if not k:
        return []
    r = random.Random('%s|%d|%d|%d' % (n.bot.name, int(n.spawn), int(x) // 50, int(y) // 50))
    ux, uy = (x - sx) / d, (y - sy) / d
    width = r.choice((-1, 1)) * d * r.uniform(0.05, 0.17)
    out = []
    for i in range(1, k + 1):
        t = i / (k + 1.0) + r.uniform(-0.04, 0.04)
        s = width * math.sin(math.pi * t) + d * r.uniform(-0.025, 0.025)
        out.append((max(250, min(w.map_w - 250, sx + ux * d * t - uy * s)), max(250, min(w.map_h - 250, sy + uy * d * t + ux * s))))
    return out


def _route(w, n, x, y, now, threshold=150):
    """Uzun yolculuk (portal, istasyon, devriye): düz çizgi yerine ara noktalı hafif bir yay; ara noktaya varmadan sıradakine döner
    (durup kalkmaz). Oyuncu bildirimi 2026-10-31: haritaya girince botlar tek sıra, dümdüz ve aynı yoldan portala uçuyordu."""
    nx, ny = n.mover.pos(now)
    r = n.route
    if r is None or math.hypot(r[0][0] - x, r[0][1] - y) > threshold:
        r = n.route = ((x, y), _waypoints(w, n, nx, ny, x, y))
    mid = r[1]
    early = max(250, n.speed() * 1.6)                     # bir düşünme aralığında alınan yol: köşede beklemesin
    remaining = math.hypot(x - nx, y - ny)
    while mid and (math.hypot(mid[0][0] - nx, mid[0][1] - ny) < early
                   or math.hypot(x - mid[0][0], y - mid[0][1]) > remaining):     # geride kaldı (araya savaş girdi): geri dönmez
        mid.pop(0)
    hx, hy = mid[0] if mid else (x, y)
    _go_to(w, n, hx, hy, now, threshold=60)


def _stop(w, n, now):
    if n.mover.t1 > now:
        x, y = n.mover.pos(now)
        _go_to(w, n, x, y, now, threshold=0)


def hero_power(o):
    """Oyuncunun kabaca gücü (botun kararı için): lazerleri ve gemisinin canı/kalkanı."""
    try:
        lasers = sum(K.ITEMS['lazerler'].get(l, {}).get('hasar', 0) for l in o.lasers())
        g = o.p.d['gemi']
        multiplier = K.ITEMS['lazer_cephane'].get(o.p.d.get('secili', {}).get('lazer'), {}).get('carpan', 1)
        dps = lasers * min(multiplier, 3) * 0.88 * 0.8 / COMBAT_INTERVAL
        ehp = g.get('hitMax', 0) + g.get('shieldMax', 0) * 2.5 * 0.9
        return K.power_score(dps, ehp)
    except Exception:
        return 50.0


def _in_peace(w, x, y):
    return w.in_pvp_peace(x, y)


# ------------------------------------------------------------------------------------------------------------ kurallar
def attack_error(w, n, now=None):
    """Oyuncunun bu bota saldırısı -> [] serbest ya da istemcinin ret mesajları (oyuncu_savas.attack_error'ın kuralları)."""
    now = now or time.time()
    b = n.bot
    if w.hero_dead or w.jumping or not n.alive:
        return [legacy('0|A|STM|msg_grp_attack_impossible')]
    hx, hy = w.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _in_peace(w, hx, hy) or _in_peace(w, nx, ny):
        # güvenli bölge: "Saldırıya-Korumalı-Bölge" (istemcinin peacearea'sı; "Grup üyelerine saldırılamaz" yazıyordu, oyuncu
        # bildirimi 2026-10-30)
        return [legacy('0|A|STM|peacearea')]
    pl = w.p.d['pilot']
    clan = int(pl.get('clanId') or 0)
    if clan and clan == int(T.profile(b).d['pilot'].get('clanId') or 0):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if relation(w, b) in (1, 2):
        return [legacy('0|A|STM|friendlyfire_disabled')]
    if int(pl.get('factionId') or 0) == b.firma and relation(w, b) != 3 and not WD.SET.get('sirket_pvp'):
        return [legacy('0|A|STM|friendlyfire_disabled')]       # panel: kendi şirketine saldırı kapalı (savaştaki klan hariç)
    if int(pl.get('factionId') or 0) == b.firma and H.company(w.map_id) == b.firma and H.name(w.map_id).split('-')[-1] in ('1', '2'):
        return [legacy('0|A|STM|no_attack_on_start_maps')]
    return []


def was_hit(w, n, attacker=None):
    """hit_npc: vuruş geçerli mi; geçerliyse bot saldıranı (kahraman ya da P.E.T.'i) hatırlar."""
    now = time.time()
    from . import active_items as AC
    # Insta-Shield süresinde vurulmaz; gizliyken yalnız onu seçmiş olan vurur (wiki: "Cloaked ships can still be attacked (if
    # targeted)"; oyuncu bildirimi 2026-10-31: gizlenen bota saldırılamıyordu)
    if attack_error(w, n, now) or now < n.__dict__.get('immune_until', 0) or (n.__dict__.get('hidden') and w.target != n.id):
        return False
    n.attacker[w.hid] = now
    n.last_damage = now
    if n.next_think > now + 0.3:
        n.next_think = now + min(0.6, n.bot.k['kisilik']['reaction_sec'])
    return True


# ------------------------------------------------------------------------------------------------------------ ölüm
def was_killed(w, n):
    """Oyuncu (ya da P.E.T.'i, mayını, yeteneği) botu yok etti -> mesajlar (kill'in yerine)."""
    import player_combat as OS
    b = n.bot
    x, y = n.mover.pos(time.time())
    msgs = remove(w, n)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0)))
    p = T.profile(b)
    p.d['gemi']['hitPoints'] = 0

    class Victim:
        pass
    victim = Victim()
    victim.p = p
    try:
        msgs += OS.on_kill(w, victim)
    except Exception as e:
        w.log('   bot ödülü verilemedi: %s' % e)
    name = w.p.d['pilot'].get('userName', '')
    if b.target is not None and b.target.name == 'duello':
        b.plan['bitti'] = True                           # düelloyu kaybetti
        b.k['intent'] = None
    y_ = MGR.ACTIVE
    if y_ is not None:
        with y_.lock:
            S.death(b, y_, reason='oyuncu', killer=name, now=time.time())
    w.log('   bot %s yok edildi (%s)' % (b.name, H.name(w.map_id)))
    return msgs


def player_died(w, n):
    """Bot oyuncuyu yok etti: onur ve hafıza (oyuncunun ölüm ekranı dünyada)."""
    b = n.bot
    name = w.p.d['pilot'].get('userName', '')
    kill_rewards = K.ITEMS['player_kill']
    y = MGR.ACTIVE
    speed = y.speed(b) if y is not None else 1.0
    b.reward(None, speed, ep=kill_rewards['ep_points'], onur=kill_rewards['honor_points'])
    b.ist('oyuncu')
    b.ist('oyuncu_puan', T.ship_rank_points(w.p.ship()['lootId']))
    b.memory.event(name, 'oldurdum')
    b.mood.it(moral=0.12, ozguven=0.1, ofke=-0.3)
    b.event('oyuncu_oldurdum', ad=name)
    if b.target is not None and b.target.name == 'duello':
        b.plan['bitti'] = True                           # düelloyu kazandı
        b.k['intent'] = None
    n.target = None


def bot_damage(w, t, dmg, source_id, now, killer_bot=None, npc=None):
    """Bot gemisi hasar aldı (uzaylıdan ya da başka bottan): kalkan emer, can biterse bot ölür."""
    from . import active_items as AC
    if not t.alive or AC.is_protected(t, now):
        return
    absorb = t.bot.value()['emme']
    to_shield = min(int(t.shield), int(dmg * absorb))
    t.shield -= to_shield
    t.hp = max(0, t.hp - (dmg - to_shield))
    t.last_damage = now
    t.attacker[source_id] = now
    msgs = [('AttackHitCommand', dict(attackType=WD.attack_type(1), attackerId=source_id, victimId=t.id, victimHitpoints=int(t.hp),
                                      victimShield=int(t.shield), victimNanoHull=0, damage=int(dmg), skilled=False, strike=False,
                                      cannonType=0))]
    if w.target == t.id:
        msgs.append(w.selection(t))
    _broadcast(w, msgs, source_id, t.id)
    if t.hp <= 0:
        bot_die(w, t, killer_bot, npc)


def bot_die(w, t, killer_bot=None, npc=None):
    b = t.bot
    msgs = remove(w, t)
    if any(m[0] == 'ShipRemoveCommand' for m in msgs):
        msgs.insert(0, ('ShipDestroyedCommand', dict(destroyedUserId=t.id, explosionTypeId=0)))
    w.send(msgs)
    y = MGR.ACTIVE
    if y is None:
        return
    with y.lock:
        if killer_bot is not None:
            S.pvp_reward(killer_bot, b, y, time.time())
        S.death(b, y, reason='oyuncu' if killer_bot else 'npc', killer=killer_bot.name if killer_bot else None, now=time.time())


def kill_npc(w, m, n, now):
    """Bot uzaylıyı öldürdü: uzaylı kalkar ve yeniden doğar (kill'in ödülsüz hâli), ödül bota, kargo kutusu yanına (botun; başkaları
    mavi görür). Uzaylı başkasının etiketliyse (oyuncunun ya da başka botun) dünyanın kill'i ödülü ona verir."""
    who = WD.tag_owner(m, now)
    if (who is not None and tuple(who) != ('b', n.id)) or getattr(m, 'damage_split', None):     # hasar_dagilim: grup uzaylısı, dünya böler
        w.send(w.kill(m))
        n.target = None
        return
    m.alive = False
    w.npcs.pop(m.id, None)
    x, y = m.mover.pos(now)
    msgs = w.pet.npc_gone(m.id) if w.pet else []
    if m.id in w.visible:
        w.visible.discard(m.id)
        msgs += [('ShipDestroyedCommand', dict(destroyedUserId=m.id, explosionTypeId=0)), ('ShipRemoveCommand', {'userId': m.id})]
    if w.target == m.id:
        w.target, w.attacking = None, False
        msgs.append(('ShipDeselectionCommand', {}))
    if not m.gate and not m.summoned and not m.d.get('uncounted'):
        w.schedule(random.uniform(*w.respawn_range(m)), 'npc', m.tip)
    try:
        msgs += w.alien.on_kill(m, x, y)
    except Exception:
        pass
    w.send(msgs)
    # grup (grup.py): bot kahramanla gruptaysa ödül haritadaki kahramanla ve gruptaki botlarla paylaşılır, kahramanın görevine sayılır
    pay = [w] if w.is_group_member(n.id) and w.running and not w.hero_dead and not w.jumping else []
    bots = [n.bot] + ([o for o in group_bots(w) if o is not n.bot] if pay else [])
    for b in bots:
        npc_reward(b, m, len(pay) + len(bots))
    for h in pay:
        h.npc_reward(m, x, y, len(pay) + len(bots), own=False)
    drop_cargo(w, m, n.id, x, y)
    if is_boss(m):
        n.bot.event('patron_oldurdum', ad=m.d.get('ad', ''))
        witness(w, 'patron', x, y, exclude=n.id, ad=m.d.get('ad', ''), kim=n.bot.name)
    n.target = None
    n.next_think = now + random.uniform(0.8, 2.5) * n.bot.k['kisilik']['reaction_sec']      # öldürünce kısa duraklama (ganimete bakar)


# ------------------------------------------------------------------------------------------------------------ ateş
def _ammo(n, target, m, o):
    """Bu atışın cephanesi stoktan (silah.lazer_sec: dayanıklı uzaylıya x2/x3, PvP'de RSB/x3; hedef başına bir kez seçilir, gerçek
    oyuncu gibi) ve harcanması: lazer sayısı kadar mermi -> cephane ya da None (mermi yok, ateş edemez)."""
    from . import weapons as WP
    b = n.bot
    if getattr(n, 'ammo_target', (None,))[0] != target or WP.stock(b).get(n.ammo_target[1], 0) <= 0:
        pvp = o is not None or (m is not None and m.bot is not None)
        ehp = 0 if pvp or m is None else m.d.get('hp', 0) + m.d.get('kalkan', 0)
        n.ammo_target = (target, WP.pick_laser(b, ehp, pvp))
    ammo = n.ammo_target[1]
    if ammo is None:
        return None
    laser = max(1, len(K.outfit(b.k['ekip'], b.shield_share())['lazer']))
    if not WP.spend(b, ammo, laser):
        return None
    from . import lab as LB
    n.lab_shot = LB.bonus(b, LB.LAZER)                   # bu atışın laboratuvar bonusu
    LB.spend(b, LB.LAZER, laser)
    return ammo


def _color(b, ammo=None):
    laser_colors = K.ITEMS['laser_colors']
    e = b.k['ekip']
    c = ammo or e['cephane']
    lasers = [l for l, k in e['lazer'].items() if k]
    if len(lasers) == 1 and c in laser_colors['full_set'].get(lasers[0], {}):
        return laser_colors['full_set'][lasers[0]][c]
    return laser_colors['cephane'].get(c, 0)


def _fire(b, pvp=False, ammo=None):
    y = K.outfit(b.k['ekip'], b.shield_share())
    multiplier = K.ITEMS['lazer_cephane'].get(ammo or b.k['ekip']['cephane'], {}).get('carpan', 1)
    lab = b.body.lab_shot if b.body is not None and hasattr(b.body, 'lab_shot') else 0.0
    return int(sum(y['lazer']) * multiplier * (1 + lab) * random.uniform(*K.ITEMS['damage_random']))


def fire(w, n, now):
    """Hedefe ateş (1,1 sn'de bir): uzaylıya, oyuncuya ya da başka bota."""
    if n.target is None:
        if n.fire:
            n.fire = False
            _broadcast(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    if now < n.next_shot:
        return
    pos = _position(w, n.target, now)
    if pos is None:
        n.target = None
        return
    nx, ny = n.mover.pos(now)
    if math.hypot(pos[0] - nx, pos[1] - ny) > LASER_RANGE:
        return
    n.next_shot = now + COMBAT_INTERVAL
    target = n.target
    m = w.npcs.get(target)
    o = _player(w, target) if m is None else None
    if o is not None and not can_attack_player(w, n, o, now):
        n.target = None
        return
    if m is not None and m.bot is not None and not can_attack_bot(w, n, m, now):
        n.target = None
        return
    ammo = _ammo(n, target, m, o)
    if ammo is None:                                      # mermisi bitti: ateş edemez (ikmal karar anında)
        if n.fire:
            n.fire = False
            _broadcast(w, [('AttackAbortLaserCommand', {'uid': n.id})], n.id)
        return
    n.fire = True
    rocket(w, n, target, m, o, now)
    salvo(w, n, target, m, o, now)
    from . import active_items as AC, weapons as WP
    AC.decloak(w, n)                                       # ateş eden gizli bot görünür olur
    if m is not None and m.bot is None:
        AC.chain_impulse(w, n, now)
    run = ('AttackLaserRunCommand', dict(attackerId=n.id, targetId=target, laserColor=_color(n.bot, ammo), isDiminishedBySkillShield=False,
                                         skilledLaser=False, visualType=0))
    is_hard = o is not None or (m is not None and (m.bot is not None or (m.d.get('hp', 0) + m.d.get('kalkan', 0))
                                               / max(1, n.bot.value()['dps']) > WP.HARD_SEC))
    landed = random.random() < AC.aim(n, WD.COMBAT['lazer_isabet'], is_hard)      # AIM CPU (Xenomit)
    if o is not None:
        msgs = [run]
        if landed:
            dmg = _fire(n.bot, pvp=True, ammo=ammo)
            AC.leech(n, dmg, n.bot.value()['can'], now)
            msgs += o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=now)
        else:
            msgs.append(('AttackMissedCommand', dict(attackType=WD.attack_type(1), targetUserId=target, skillColorId=0)))
        o.send(msgs)
        return
    if m is None or not m.alive:
        n.target = None
        return
    if not landed:
        _broadcast(w, [run, ('AttackMissedCommand', dict(attackType=WD.attack_type(1), targetUserId=target, skillColorId=0))], n.id, target)
        return
    dmg = _fire(n.bot, pvp=m.bot is not None, ammo=ammo)
    AC.leech(n, dmg, n.bot.value()['can'], now)
    if m.bot is not None:
        _broadcast(w, [run], n.id, target)
        bot_damage(w, m, dmg, n.id, now, killer_bot=n.bot)
        return
    hit_npc(w, n, m, dmg, now, 1, [run], ammo=ammo)


def salvo(w, n, target, m, o, now):
    """Roket fırlatıcısının salvosu (dayanıklı uzaylıya ya da PvP'de): kapasite kadar roket, yarım saniye arayla; görseli roketin
    eski metni (fırlatıcı roketinin kimliğiyle), hasarı her roket varınca."""
    from . import technology as TECH, weapons as WP
    b = n.bot
    if now < getattr(n, 'salvo_ready', 0):
        return
    pvp = o is not None or (m is not None and m.bot is not None)
    is_hard = m is not None and m.bot is None and (m.d.get('hp', 0) + m.d.get('kalkan', 0)) / max(1, b.value()['dps']) > WP.HARD_SEC
    fr = TECH.pick_launcher_rocket(b) if (pvp or is_hard) else None
    pos = _position(w, target, now)
    nx, ny = n.mover.pos(now)
    if not fr or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > TECH.LAUNCHER['menzil']:
        return
    capacity, mid = TECH.salvo(b)
    capacity = WP.spend(b, fr, capacity)
    if not capacity:
        return
    n.salvo_ready = now + mid
    r = TECH.LAUNCHER_AMMO[fr]
    dmg = int(r.get('pvp_hasar' if pvp else 'hasar', r['hasar']))
    for i in range(capacity):
        def at(i=i):
            t = time.time()
            if not n.alive:
                return
            _broadcast(w, [legacy('0|v|%d|%d|H|%d|0|0' % (n.id, target, r.get('kimlik', 9)))], n.id, target)

            def hit():
                t2 = time.time()
                if not n.alive:
                    return                                # ölmüş botun salvosu vurmaz
                if o is not None:
                    if can_attack_player(w, n, o, t2):
                        o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t2))
                    return
                x = w.npcs.get(target)
                if x is not None and x.alive:
                    if x.bot is not None:
                        bot_damage(w, x, dmg, n.id, t2, killer_bot=b)
                    else:
                        hit_npc(w, n, x, dmg, t2, 0, ammo=fr)
            w.later(WD.COMBAT['rocket_flight_sec'], hit)
        w.later(i * 0.5, at)
    b.ist('salvo')


def player_near(w, m, now, reach=1500):
    """Oyuncu uzaylının yakınında mı: bot vuruşunun tetiklediği oyuncuya yönelik etkiler (EMP, ters kontrol) yalnız o zaman."""
    if w.hero_dead or w.jumping:
        return False
    hx, hy = w.hero_pos(now)
    mx, my = m.mover.pos(now)
    return math.hypot(hx - mx, hy - my) <= reach


def hit_npc(w, n, m, dmg, now, atype, once=(), shield=False, ammo=None):
    """Botun lazeri (atype 1) ya da roketi (0) uzaylıya: kalkan emer, gövde; ölürse npc_oldur, yoksa uzaylı bota döner.
    kalkan: yalnız kalkana (Chain Impulse). Uzaylının mekanikleri oyuncunun vuruşundaki gibi (dunya.hit_npc): yardımcıları yaşarken
    dokunulmazlık, yalnız belirli cephane, hasar azaltma, gizli komandonun görünmesi, vurulunca çağırma (yardımcılar botun çevresinde
    doğar, bota saldırır), can tabanı, can eşiğinde çağırma ve kaybolma (uzayli.on_hit; oyuncuya yönelik EMP ve ters kontrol yalnız
    oyuncu yakınsa). Önceden bot vuruşu bunları atlıyordu: Cubikon bota Protegit çağırmıyordu (kullanıcı bildirimi 2026-10-30)."""
    if not m.alive:
        return
    only = m.d.get('ammo_only')
    if (m.invulnerable and m.invulnerable()) or m.effect.invulnerable(now) or w.guarded(m) or (only and ammo not in only):
        dmg = 0
    red = getattr(m, 'damage_reduction', None)
    if red:
        dmg = int(dmg * max(0.0, 1 - red()))
    if getattr(m, 'hidden', False):                       # gizli komando vurulunca görünür (sizma.py)
        m.hidden = False
        w.send([legacy('0|n|INV|%d|0' % m.id)])
    w.alien.attacked(m, n.id, now)
    w.npc_summon(m, now, hitter=n)
    absorb = 1.0 if shield else m.d.get('kalkan_emme', WD.COMBAT['npc_shield_absorb'])
    to_shield = min(int(m.shield), int(round(dmg * absorb)))
    m.shield -= to_shield
    m.hp = max(0, m.hp - (dmg - to_shield))
    floor = getattr(m, 'hp_floor', 0)                  # Guardian 1 HP'de "düşer" (evreler)
    if floor and m.hp < floor:
        m.hp = floor
        if getattr(m, 'at_floor', None):
            m.at_floor(m)
    m.last_hit = now
    w.alien.on_hit(m, dmg, n.id, now, to_player=player_near(w, m, now))
    if not m.alive or m.id not in w.npcs:                 # kayboldu ya da kalktı (uzayli.on_hit)
        return
    who = ('h', w.hid) if is_helping(w, n, m, now) else ('b', n.id)
    WD.tag_alien(m, who, now)
    WD.record_damage(m, who, dmg)                            # grup uzaylısında ödül hasara göre bölünür (etiket_oyuncu)
    hit = ('AttackHitCommand', dict(attackType=WD.attack_type(atype), attackerId=n.id, victimId=m.id, victimHitpoints=int(m.hp),
                                    victimShield=int(m.shield), victimNanoHull=0, damage=dmg, skilled=False, strike=False, cannonType=0))
    msgs = list(once) + [hit] + ([w.selection(m)] if w.target == m.id and m.hp > 0 else [])
    _broadcast(w, msgs, n.id, m.id)
    if m.hp <= 0:
        kill_npc(w, m, n, now)
    elif m.bot_target is None and not m.engaged and m.d['hasar'] > 0:
        m.bot_target = n.id                     # uzaylı bota döner
        m.next_think = now


def rocket(w, n, target, m, o, now):
    """Roket (bekleme 4 sn, R0K-T01 ile 2): menzildeyse stoktaki en güçlüsü; görseli oyuncununki gibi eski metin (0|v|…), ~0,8 sn
    sonra vuruş (isabet roketin kendi oranı)."""
    from . import weapons as WP
    b = n.bot
    if now < getattr(n, 'rocket_ready', 0):
        return
    rocket = WP.pick_rocket(b)
    pos = _position(w, target, now)
    nx, ny = n.mover.pos(now)
    if not rocket or pos is None or math.hypot(pos[0] - nx, pos[1] - ny) > WD.COMBAT['rocket_range'] or not WP.spend(b, rocket, 1):
        return
    n.rocket_ready = now + WP.rocket_cooldown(b)
    r = K.ITEMS['roketler'][rocket]
    landed = random.random() < r.get('isabet', WD.COMBAT['roket_isabet'])
    _broadcast(w, [legacy('0|v|%d|%d|%s|%d|0|0' % (n.id, target, 'H' if landed else 'M', r.get('kimlik', 1)))], n.id, target)
    if not landed:
        return
    from . import lab as LB
    dmg = int(r.get('pvp_hasar' if (o is not None or (m is not None and m.bot is not None)) else 'hasar', r['hasar'])
              * random.uniform(0.85, 1.0) * (1 + LB.bonus(b, LB.ROCKET)))
    LB.spend(b, LB.ROCKET, 1)

    def hit():
        t = time.time()
        if not n.alive:
            return
        if o is not None:
            if can_attack_player(w, n, o, t):
                o.send(o.hurt_hero(dmg, killer=n, cause=0, source_asset=True, now=t))
            return
        x = w.npcs.get(target)
        if x is None or not x.alive:
            return
        if x.bot is not None:
            bot_damage(w, x, dmg, n.id, t, killer_bot=b)
        else:
            hit_npc(w, n, x, dmg, t, 0, ammo=rocket)
    w.later(WD.COMBAT['rocket_flight_sec'], hit)


def npc_reward(b, m, pay=1):
    """Uzaylının ödülü bota (paketin hızı, X-1 kesintisi), ek ganimeti ve görev ilerlemesi. pay: grupta paydaş sayısı (ödül
    bölünür, ganimet ve görev tam; dunya.npc_reward gibi)."""
    from . import loot as LT, events as EV
    LT.extra_loot(b, m.tip, 1)
    EV.drop(b, b.game_map, m.tip)                         # etkinlik düşmeleri (Candy Corn …)
    y_ = MGR.ACTIVE
    speed = y_.speed(b) if y_ is not None else 1.0
    o = m.d.get('odul', {})
    x1 = S.x1_cut(b) / pay                           # oyuncudaki gibi dört ödüle de
    b.reward('npc', speed, ep=o.get('ep', 0) * x1, kredi=o.get('kredi', 0) * x1, uridyum=o.get('uridyum', 0) * x1,
           onur=o.get('onur', 0) * x1)
    b.ist('npc')
    b.ist('npc_puan', T.npc_rank_points(m.tip))
    if y_ is not None:
        with y_.lock:
            y_.npc_killed(b, m.tip, 1)


def group_bots(w):
    """Kahramanın grubundaki, bu haritada yaşayan botlar (uzaylı ödülünün paydaşları; group.py)."""
    return [m.bot for m in list(w.npcs.values()) if m.bot is not None and m.alive and w.is_group_member(m.id)]


def drop_cargo(w, m, uid, x, y):
    """Uzaylının kargo kutusu (cevherleri) botun adına: yalnız bot gemisi haritadaysa (toplayacak biri var)."""
    t = w.npcs.get(uid)
    if t is None or t.bot is None or not t.bot.permission.get('kargo', True):
        return
    cargo = {str(k): v for k, v in K.npc_cargo(m.tip, t.bot.level, w.map_id).items()}
    if not cargo:
        return
    owner_tag = ('b', uid) if WD.SET.get('kargo_sahipligi') else None
    w.later(WD.COMBAT['box_delay_sec'], lambda: w.drop_box('FROM_SHIP', x, y, cargo, WD.COMBAT['box_life_sec'], owner_tag=owner_tag))


def _bot(uid):
    y_ = MGR.ACTIVE
    return next((b for b in y_.bots if b.uid == uid), None) if y_ is not None else None


def bot_firma(uid):
    b = _bot(uid)
    return b.firma if b is not None else None


def tag_reward(w, m, uid, x, y):
    """Botun etiketlediği uzaylıyı başkası bitirdi: ödül, görev ve kargo kutusu botun (dunya.World.etiket_paydaslari)."""
    b = _bot(uid)
    if b is None or not b.online:
        return
    npc_reward(b, m)
    drop_cargo(w, m, uid, x, y)


def bot_online(uid):
    b = _bot(uid)
    return b is not None and b.online


def split_reward(w, m, uid, ratio, x, y, box=False):
    """Grup uzaylısında botun hasara göre payı (dunya.World.hasara_gore): ödül oran kadar (npc_odulu pay=1/oran), en çok hasar
    veren botsa kargo kutusu da onun."""
    b = _bot(uid)
    if b is None or not b.online:
        return
    npc_reward(b, m, 1.0 / ratio)
    if box:
        drop_cargo(w, m, uid, x, y)


def on_box_taken(owner_tag, name):
    """Oyuncu botun kargo kutusunu topladı: bot onu unutmaz (hafızasında hakaret gibi)."""
    if not owner_tag or owner_tag[0] != 'b':
        return
    b = _bot(owner_tag[1])
    if b is not None and name:
        b.memory.event(name, 'hakaret', b.hour(), multiplier=0.5)
        b.event('kutu_calindi', ad=name)


def can_attack_player(w, n, o, now):
    if o.hero_dead or o.jumping or o.hidden(now) or not o.running:
        return False
    import admin_mode as YM
    from . import admin_warnings as AW
    if YM.mi(profile=o.p) or YM.spectator(o.p) or AW.active(n.bot, 'pvp', now):
        return False                                     # yöneticiye saldırılmaz (wiki Administrator: "should not be shot at"); PvP uyarısı
    if now < o.invuln_until or o.invulnerable or o.hero_effects.invulnerable(now):
        return False
    hx, hy = o.hero_pos(now)
    nx, ny = n.mover.pos(now)
    if _in_peace(w, hx, hy) or _in_peace(w, nx, ny) or relation(o, n.bot) in (1, 2):
        return False                                     # klanı müttefik ya da saldırmazlıkta
    return int(o.p.d['pilot'].get('factionId') or 0) != n.bot.firma or not (
        H.company(w.map_id) == n.bot.firma and H.name(w.map_id).split('-')[-1] in ('1', '2'))


def can_attack_bot(w, n, m, now):
    from . import admin_warnings as AW
    if not m.alive or m.bot.firma == n.bot.firma or AW.active(n.bot, 'pvp', now):
        return False
    if (n.bot.k.get('klan') and n.bot.k.get('klan') == m.bot.k.get('klan')) or T.clan_relation(n.bot, m.bot) in (1, 2):
        return False
    nx, ny = n.mover.pos(now)
    mx, my = m.mover.pos(now)
    return not (_in_peace(w, nx, ny) or _in_peace(w, mx, my))


# ------------------------------------------------------------------------------------------------------------ uzaylının bota karşılığı
def npc_to_bot(w, m, now):
    """Bot vurduğu uzaylı bota döner (oyuncuyla savaşmıyorsa): kovalar ve ateş eder -> işlendi mi (think'in kalanı atlanır)."""
    t = w.npcs.get(m.bot_target)
    if m.engaged or t is None or not t.alive or t.bot is None:
        m.bot_target = None
        return False
    if now < m.next_think and now < m.next_shot:
        return True
    tx, ty = t.mover.pos(now)
    mx, my = m.mover.pos(now)
    dist = math.hypot(tx - mx, ty - my)
    post = w.ward_of(m)
    if dist > 2500 or (post and w.leashed(m, post, tx, ty, now)):
        # koruyucu (Cubikon'un Protegit'leri) botu çağıranından uzağa, portala dek kovalamaz: oyuncudaki tasmayla (dunya.leashed) aynı
        m.bot_target = None
        return False
    if w.in_peace(tx, ty) and t.id not in m.attackers:
        # güvenli bölge: oyuncunun kuralı (dunya.npc_retaliating), yalnız botun vurduğu uzaylı peşinden girer; çağrılan yardımcılar
        # bölgeye dalıp ateş ediyordu
        m.bot_target = None
        w.alien_ceasefire(m)
        w.stop_npc_motion(m, now)
        return False
    if now >= m.next_think:
        m.next_think = now + 1.0
        if dist > m.keep + 60:
            a = math.atan2(my - ty, mx - tx) + m.spread
            gx, gy = tx + math.cos(a) * m.keep, ty + math.sin(a) * m.keep
            ms = m.mover.go(gx, gy, m.speed(), now)
            w.send([('MoveCommand', dict(userId=m.id, x=int(gx), y=int(gy), timeToTarget=ms))])
    if now >= m.next_shot and dist <= w.npc_range(m) and m.d['hasar'] > 0:
        m.next_shot = now + m.d.get('shot_interval_sec', WD.COMBAT['npc_attack_interval_sec'])
        _broadcast(w, [('AttackLaserRunCommand', dict(attackerId=m.id, targetId=t.id, laserColor=0, isDiminishedBySkillShield=False,
                                                  skilledLaser=False, visualType=0))], m.id, t.id)
        if random.random() < m.d.get('isabet', WD.COMBAT['npc_isabet']):
            bot_damage(w, t, int(m.d['hasar'] * random.uniform(0.8, 1.0)), m.id, now, npc=m)
    return True


# ------------------------------------------------------------------------------------------------------------ taktik
def think(w, n, now):
    """Botun dünya döngüsündeki aklı (think'in yerine; her adım çağrılır, kendi aralığıyla düşünür)."""
    if not n.alive:
        return
    b = n.bot
    fire(w, n, now)
    if now < n.next_think:
        return
    n.next_think = now + b.k['kisilik']['reaction_sec'] * random.uniform(0.6, 1.4)
    d = b.value()
    if now - n.last_damage > COMBAT_SEC:                     # yenilenme
        from . import extras as EX
        k = REGEN_RATE * b.k['kisilik']['reaction_sec'] * 1.0
        rep = EX.repair_sec(b)
        n.shield = min(d['kalkan'], n.shield + d['kalkan'] * k * 2)
        n.hp = min(d['can'], n.hp + d['can'] * max(k, b.k['kisilik']['reaction_sec'] / rep if rep else 0))     # onarım robotu
    nx, ny = n.mover.pos(now)
    b.k['x'], b.k['y'] = int(nx), int(ny)
    if b.__dict__.get('exit_request') and not any(now - t < 6 for t in n.attacker.values()):
        return go_logout(w, n, now)                     # oturum bitti: istasyona ya da portala uçup orada çıkar
    if (n.target is None and not any(now - t < 6 for t in n.attacker.values()) and not b.en_route
            and (b.target is None or b.target.name != 'kapi') and collect_box(w, n, now)):
        return                                           # yolunun üstündeki kutuyu alır (her işte; dövüşte değilken)
    if b.target is not None and b.target.concrete(b, n, w, now):
        return
    ratio = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    attackers = [u for u, t in n.attacker.items() if now - t < 6]
    from . import active_items as AC
    if AC.combat(w, n, now, d, ratio, attackers):         # Insta-Shield, Backup Shields, Battle Repair, Smart Bomb, Energy Leech
        ratio = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    # 1) tehlike: canı azaldı ve vuruluyor -> kaç
    in_gate = is_gate_world(w)
    if attackers and ratio < 0.18 + 0.32 * (1 - b.o('risk')) and not in_gate:
        return flee(w, n, now)
    # 2) portal yolunda
    if b.en_route and not attackers and not in_gate:
        return portala(w, n, now)
    # 2b) hasarlı ve kimse vurmuyor: durup toparlanır
    if not attackers and recover(w, n, now, d):
        return
    # 3) saldırıya karşılık ya da kaç
    if attackers and (n.target is None or n.target not in attackers):
        u = attackers[-1]
        if u in w.npcs and w.npcs[u].bot is None:
            n.target = u                                  # uzaylı vurdu: karşılık
        else:
            opponent = _power(w, u)
            if opponent / max(0.5, d['power']) > 1.3 + b.o('risk') + 0.5 * b.mood['ofke'] and ratio < 0.9:
                return flee(w, n, now)
            n.target = u
            b.memory.event(_name(w, u), 'hakaret', now, multiplier=0.3)
    # 4) PvP fırsatı
    if n.target is None or n.target in w.npcs and w.npcs[n.target].bot is None:
        t = pvp_target(w, n, now)
        if t is not None:
            n.target = t
    # 4b) eşlik: sana ya da arkadaşı olan bir bota katıldıysa onun hedefine ateş eder, yoksa yanında uçar
    if escort(w, n, now):
        return
    # 5) hedefe yaklaş / hedefe göre davran
    if n.target is not None:
        pos = _position(w, n.target, now)
        if pos is None:
            n.target = None
        else:
            return approach(w, n, pos, now)
    h = b.target.name if b.target is not None else 'kasilma'
    if h == 'dinlenme':
        return rest(w, n, now)
    return go_hunt(w, n, now)


def _name(w, uid):
    o = _player(w, uid)
    if o is not None:
        return o.p.d['pilot'].get('userName', '')
    m = w.npcs.get(uid)
    if m is not None:
        return m.bot.name if m.bot is not None else m.d.get('ad', '')
    # haritada değil (ayrılmış ya da ölmüş bot, oyuncunun P.E.T.'i): önceden "" dönüyor, botlar adsız birinden "hakaret" biriktiriyordu
    b = _bot(uid)
    if b is not None:
        return b.name
    if getattr(w, 'pet', None) is not None and w.pet.owned and w.pet.pid == uid:      # P.E.T.'i yoksa pid okunamaz (canlı test)
        return w.p.d['pilot'].get('userName', '')
    return ''


def _power(w, uid):
    o = _player(w, uid)
    if o is not None:
        return hero_power(o)
    m = w.npcs.get(uid)
    return m.bot.value()['power'] if m is not None and m.bot is not None else 1.0


def approach(w, n, pos, now):
    """Hedefle savaş mesafesi: lazer menzilinin içinde, kişiliğe göre yakın ya da uzak; hedefin çevresinde hafif döner."""
    nx, ny = n.mover.pos(now)
    dist = math.hypot(pos[0] - nx, pos[1] - ny)
    wanted = 280 + 300 * (1 - n.bot.o('saldirganlik'))
    if dist > wanted + 120 or dist < 120:
        a = math.atan2(ny - pos[1], nx - pos[0]) + random.uniform(-0.5, 0.5)
        _go_to(w, n, pos[0] + math.cos(a) * wanted, pos[1] + math.sin(a) * wanted, now)
    elif n.mover.t1 <= now and random.random() < 0.25 + 0.4 * n.bot.o('saldirganlik'):
        # menzilde: hedefin çevresinde döner (gerçek oyuncu dururken değil, dönerek ateş eder); yön botun huyuna göre sabit
        direction = n.__dict__.setdefault('orbit_direction', random.choice((-1, 1)))
        a = math.atan2(ny - pos[1], nx - pos[0]) + direction * random.uniform(0.25, 0.6)
        _go_to(w, n, pos[0] + math.cos(a) * wanted, pos[1] + math.sin(a) * wanted, now, threshold=40)


def pvp_target(w, n, now):
    """Görüşteki düşman oyuncu ya da bot: saldırmaya değer mi (kişilik, güç oranı, kin, PvP hedefi)."""
    b = n.bot
    y = MGR.ACTIVE
    if y is None or now - n.intent_time < 4:
        return None
    n.intent_time = now
    nx, ny = n.mover.pos(now)
    sight = WD.COMBAT['gorus_mesafesi']
    candidates = []
    if y.permission('oyuncuya_saldir') and y.permission('pvp'):
        for o in ([w] + [x for x in (w.shared.members if w.shared else []) if x is not w]):
            if not o.running or int(o.p.d['pilot'].get('factionId') or 0) == b.firma:
                continue
            hx, hy = o.hero_pos(now)
            if math.hypot(hx - nx, hy - ny) > sight or not can_attack_player(w, n, o, now):
                continue
            candidates.append((o.hid, hero_power(o), o.p.d['pilot'].get('userName', ''), relation(o, b)))
    if y.permission('pvp'):
        for m in w.npcs.values():
            if m.bot is None or m is n or not m.alive:
                continue
            mx, my = m.mover.pos(now)
            if math.hypot(mx - nx, my - ny) > sight or not can_attack_bot(w, n, m, now):
                continue
            candidates.append((m.id, m.bot.value()['power'], m.bot.name, T.clan_relation(b, m.bot)))
    if not candidates:
        return None
    own = max(0.5, b.value()['power'])
    ev = H.company(w.map_id) == b.firma                  # kendi firmasının haritası: istilacıya karşı haritasını savunur
    hunt = b.target is not None and b.target.name in ('pvp', 'yardim', 'duello')
    rival = str(b.plan.get('ad', '')).lower() if b.target is not None and b.target.name == 'duello' else ''
    en, ep = None, 0.0
    for uid, power, name, rel in candidates:
        ratio = power / own
        grudge = -min(0.0, b.memory.relation(name, now)) + (0.6 if rel == 3 else 0.0)     # klan savaşı: düşman klanın üyesi
        grudge += order_grudge(b, name, now)                      # klan emri: avlanacak kişi / odaktaki klan (hedefler/pvp.py)
        if rival and str(name).lower() == rival:
            return uid                                   # düello: meydan okuyana hemen saldırır
        defending = ev and uid not in w.npcs                    # kendi haritasındaki yabancı firma oyuncusu
        p = (0.04 + 0.5 * b.o('saldirganlik') * b.o('rekabet')) * (2.2 if hunt else 1.0)
        if defending:
            p = max(p, 0.06) * (2.0 + b.o('saldirganlik'))
        # evinde biraz daha güçlüye de kafa tutar (yardım çağırır); önceden 1,6 kat güçlüde olasılık evde de sıfırdı (canlı 2026-11-01)
        p *= max(0.0, (2.4 if defending else 1.6) - ratio) * (0.5 + b.mood['ozguven']) + grudge * 0.8
        if ratio > 1.2 + b.o('risk') + grudge + (0.5 if defending else 0.0):
            p *= 0.1
        if p > ep:
            en, ep = uid, p
    # saniyede değil karar başına (4 sn'de bir) olasılık: hemen değil, bir süre sonra saldırır gibi
    if en is None or random.random() >= min(0.9, ep * 0.5):
        return None
    if ev and en not in w.npcs:
        call_defense(w, n, en, now)
    return en


DEFENSE_MAX = 2                # bir istilacıya karşı çağrılan en çok yardımcı (sürü değil)
DEFENSE_COOLDOWN = 60.0           # aynı haritada iki çağrı arası (sn)


def call_defense(w, n, uid, now):
    """Kendi haritasında yabancı oyuncuya saldıran bot, haritadaki boşta kalan firma botlarından en çok SAVUNMA_AZAMI tanesini çağırır
    (yakın olanlar, saldırganlığa göre; bekleme süresi var; PvP kuralları oyuncuya_saldirabilir ile aynı)."""
    if now < w.__dict__.get('defense_time', 0):
        return
    o = _player(w, uid)
    if o is None:
        return
    w.defense_time = now + DEFENSE_COOLDOWN
    nx, ny = n.mover.pos(now)
    candidates = []
    for m in w.npcs.values():
        if m is n or m.bot is None or not m.alive or m.bot.firma != n.bot.firma or m.target is not None:
            continue
        if m.bot.target is not None and m.bot.target.name in ('kapi', 'mod', 'duello', 'grup'):
            continue
        if now - m.last_damage < COMBAT_SEC or m.bot.en_route or not can_attack_player(w, m, o, now):
            continue
        mx, my = m.mover.pos(now)
        distance = math.hypot(mx - nx, my - ny)
        if distance < 6000 and random.random() < 0.3 + 0.6 * m.bot.o('saldirganlik'):
            candidates.append((distance, m))
    for _, m in sorted(candidates, key=lambda x: x[0])[:DEFENSE_MAX]:
        m.target = uid
        m.intent_time = now


def flee(w, n, now):
    """Kaç: en yakın portala (ya da kendi üssündeyse istasyona); varınca atlayıp haritadan çıkar. Oyuncudan kaçarken arkasına
    mayın bırakır (stokta varsa, beklemesi dolduysa; güvenli bölgede ve başlangıç haritalarında değil)."""
    b = n.bot
    n.target = None
    nx, ny = n.mover.pos(now)
    if any(_player(w, u) is not None for u, t in n.attacker.items() if now - t < 6):
        from . import active_items as AC
        AC.emp(w, n, now)                                # kilitlenen oyuncunun seçimi düşer
        if b.o('risk') < 0.6:
            AC.cloak(w, n, now)                         # gizlenme CPU'su
        drop_mine(w, n, nx, ny, now)
    gs = [g for g in H.gates(w.map_id, b.firma) if not g.get('ucret') and g['hedef'] in K.MAPS
          and K.can_enter(g['hedef'], b.firma, b.level)]
    s = w.station
    if s and s.get('type') == b.firma:
        sx, sy = s['posX'], s['posY']
        if not gs or math.hypot(sx - nx, sy - ny) < min(math.hypot(g['x'] - nx, g['y'] - ny) for g in gs):
            _go_to(w, n, sx, sy, now)
            return
    if not gs:
        return
    g = min(gs, key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
    y = MGR.ACTIVE
    if y is not None and y.mode == 'basit':
        _go_to(w, n, g['x'] + random.uniform(-200, 200), g['y'] + random.uniform(-200, 200), now)    # basit: portalın güvenli bölgesine
        return
    if not b.en_route or b.en_route[0] != g['hedef']:
        b.en_route = [g['hedef']]
        b.event('kacti', harita=H.name(w.map_id))
    portala(w, n, now, urgent=True)


def drop_mine(w, n, x, y, now):
    """Botun mayını (oyuncunun gemisine yaklaşınca patlar: savas_esya.alien_mine) -> bırakıldı mı."""
    from . import weapons as WP
    b = n.bot
    m = WP.pick_mine(b)
    if m is None or now < getattr(n, 'mine_ready', 0) or w.items.start_map() or w.in_pvp_peace(x, y):
        return False
    if not WP.spend(b, m, 1):
        return False
    n.mine_ready = now + WP.MINE_COOLDOWN
    w.items.alien_mine(m, x, y, n.id, now)
    b.ist('mayin')
    return True


def portala(w, n, now, urgent=False):
    """Yolun sıradaki haritasının portalına uç; varınca ATLAMA_SN sonra haritadan çık (yönetici botu yeni haritaya geçirir)."""
    b = n.bot
    if not b.en_route:
        return
    if len(b.en_route) > 2 and not urgent:                     # atlama CPU'su: uzun yolu tek atlamada üsse
        from . import extras as EX
        cpu = EX.jump(b, b.en_route[-1])
        y = MGR.ACTIVE
        if cpu and y is not None and EX.use(b, cpu):
            target = b.en_route[-1]
            w.send(remove(w, n))
            with y.lock:
                S.jump_to(b, target, y)
                b.en_route = None
                b.arrival = (int(w.map_id), time.time())
                b.ist('atlama_cpu')
            return
    g = next((g for g in H.gates(w.map_id, b.firma) if g['hedef'] == b.en_route[0]), None)
    if g is None:
        b.en_route = None
        return
    nx, ny = n.mover.pos(now)
    if not urgent and now < n.spawn + n.takeoff:             # yeni geldi: biraz oyalanır, sonra kendi vaktinde yola çıkar
        if n.movement is None:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(100, 350)
            _go_to(w, n, nx + math.cos(a) * r, ny + math.sin(a) * r, now)
        return
    p = n.approach_points.get(g['hedef'])
    if p is None:                                         # portalın çevresinde kendi yanaşma noktası (hep aynı noktaya değil)
        a, r = random.uniform(0, 2 * math.pi), random.uniform(30, 140)
        p = n.approach_points[g['hedef']] = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
    if math.hypot(g['x'] - nx, g['y'] - ny) > 180:
        n.portal_time = 0.0
        if urgent:
            _go_to(w, n, p[0], p[1], now)                   # kaçarken dosdoğru
        else:
            _route(w, n, p[0], p[1], now)
        return
    if not n.portal_time:
        n.portal_time = now + JUMP_SEC * (0.8 if urgent else random.uniform(1.0, 2.5))
        n.target = None
        return
    if now < n.portal_time:
        return
    y = MGR.ACTIVE
    target = b.en_route.pop(0)
    w.send(remove(w, n))
    if y is not None:
        with y.lock:
            S.jump_to(b, target, y)
            b.arrival = (int(w.map_id), time.time())
            b.en_route_time = time.time() + S.jump_duration(b)


def can_kill(b, m):
    """Haritanın sabit listesinde olmayan uzaylı (etkinlik, Urgent Missions hedefi, Hitac taşıyıcısı …): gücü yetiyorsa (türe göre
    önbellekli; gerçek oyuncu gördüğü ve kesebildiği her şeye ateş eder)."""
    c = b.__dict__.setdefault('_can_kill', {})
    v = c.get(m.tip)
    if v is None or v[1] != b.value()['power']:
        d = b.value()
        ehp = m.d.get('hp', 0) + m.d.get('kalkan', 0)
        incoming = m.d.get('hasar', 0) * K.COMBAT['npc_isabet'] / K.NPC_INTERVAL
        duration = ehp / max(1.0, d['dps'])
        v = c[m.tip] = (duration < 180 and duration * incoming < d['ehp'] * (0.4 + 0.5 * b.o('risk')), d['power'])
    return v[0]


def _killable(b, m_id):
    from . import events as EV
    d = b.value()
    courage = max(0.0, min(1.0, 0.3 + 0.6 * b.o('risk') + 0.2 * b.mood['ozguven'] - 0.3))
    out = set(K.evaluate_map(int(m_id), d['dps'], d['ehp'], courage)['hedefler'])
    return out | EV.event_types(b, int(m_id)) if b.permission.get('etkinlik', True) else out      # etkinlik uzaylıları da


def go_hunt(w, n, now):
    """Uzaylı avı: öldürmeye cesaret ettiği türlerden en yakını (görevin istediği önce); oyuncunun savaştığını kapmaz (kaba botlar
    ara sıra kapar). Yakında bonus kutusu varsa önce onu alır. Hedef yoksa amaçlı devriye: uzak bir ara noktaya uçar, yalnız varınca
    yenisini seçer (önceden her saniye kısa rastgele sıçramalar sağa sola kıpırdanma gibi görünüyordu)."""
    b = n.bot
    nx, ny = n.mover.pos(now)
    if collect_box(w, n, now):
        return
    types = _killable(b, w.map_id)
    wanted = b.plan.get('tip')
    rude = random.random() < 0.15 * b.o('saldirganlik') * (1 - b.o('yardimseverlik'))
    en, best_score = None, 1e18
    for m in w.npcs.values():
        if m.bot is not None or not m.alive or m.d.get('dost') or getattr(m, 'hidden', False):
            continue                                     # gizli komandoyu (Infiltration) göremez
        if m.tip not in types and not can_kill(b, m):
            continue
        if (m.engaged or w.target == m.id) and not rude:
            continue
        if m.bot_target not in (None, n.id) and w.npcs.get(m.bot_target) is not None:
            continue                                     # başka bot onunla savaşıyor
        if WD.tag_owner(m, now) not in (None, ('b', n.id)):
            continue                                     # başkasının etiketlisi: kazancı olmaz
        mx, my = m.mover.pos(now)
        dd = math.hypot(mx - nx, my - ny) * (0.5 if m.tip == wanted else 1.0)
        if dd < best_score:
            en, best_score = m, dd
    if en is not None and best_score < 3500:
        n.target = en.id
        n.patrol = None
        return approach(w, n, en.mover.pos(now), now)
    start_escort(w, n, now)
    if _leader(w, n, now) is not None:
        return                                           # eşliğe başladı: bir sonraki düşüncede liderin yanına
    patrol_point = getattr(n, 'patrol', None)
    if patrol_point is None or math.hypot(patrol_point[0] - nx, patrol_point[1] - ny) < 300:
        if patrol_point is not None and random.random() < 0.4:
            n.next_think = now + random.uniform(2, 6)    # vardı: biraz bakınır
            n.patrol = None
            return
        a = random.uniform(0, 2 * math.pi)
        r = random.uniform(2500, 6000)
        patrol_point = n.patrol = (max(600, min(w.map_w - 600, nx + math.cos(a) * r)), max(600, min(w.map_h - 600, ny + math.sin(a) * r)))
    _route(w, n, patrol_point[0], patrol_point[1], now, threshold=400)


def go_logout(w, n, now):
    """Oturumu biten bot: kendi istasyonu bu haritadaysa ona, değilse en yakın portala uçar; varınca yönetici çıkışını yapar."""
    b = n.bot
    n.target = None
    nx, ny = n.mover.pos(now)
    s = w.station
    if s and s.get('type') == b.firma:
        hx, hy = s['posX'], s['posY']
    else:
        g = min(H.gates(w.map_id, b.firma) or [{'x': nx, 'y': ny}], key=lambda g: math.hypot(g['x'] - nx, g['y'] - ny))
        hx, hy = g['x'], g['y']
    if math.hypot(hx - nx, hy - ny) > 250:
        p = n.approach_points.get('cikis')
        if p is None or math.hypot(p[0] - hx, p[1] - hy) > 200:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(20, 140)
            p = n.approach_points['cikis'] = (hx + math.cos(a) * r, hy + math.sin(a) * r)
        _route(w, n, p[0], p[1], now)
    else:
        b.logout_ready = True


ESCORT_RANGE = 1600


def is_helping(w, n, m, now):
    """Bot oyuncunun hedefine yardım mı ediyor (eşlik eden ya da onunla gruptaki bot, oyuncunun seçtiği uzaylı): etiket, ödül
    ve kutu oyuncunun (eşlikçi bot önce ateş edip kutuyu alıyordu: kullanıcı bildirimi 2026-10-30)."""
    if m.id != w.target:
        return False
    l = _leader(w, n, now)
    if l is not None and l[0] == 'h':
        return True
    import group as GR
    g = GR.group_of(n.bot.uid)
    return g is not None and w.hid in g.members


def _leader(w, n, now):
    """Eşlik edilen: ('h', None) kahraman ya da ('b', gemi); gitti, öldü ya da uzaklaştıysa None."""
    e = n.__dict__.get('escort')
    if not e or now > e[1]:
        return None
    if e[0] == 'h':
        if w.hero_dead or w.jumping:
            return None
        return ('h', None)
    m = w.npcs.get(e[0])
    return ('b', m) if m is not None and m.alive and m.bot is not None else None


def start_escort(w, n, now):
    """İşi yokken (avlanırken hedefsiz) arada: aynı firmadan sana (yakındaysan) ya da arkadaşı olan bir bota katılır.
    Olasılık sosyallik, sana karşı ilişki ve yardımseverlikle; süre 1-3 dakika."""
    b = n.bot
    if n.__dict__.get('escort') and now <= n.escort[1]:
        return
    if now < n.__dict__.get('escort_check', 0):
        return
    n.escort_check = now + random.uniform(20, 40)
    nx, ny = n.mover.pos(now)
    duration = random.uniform(60, 180)
    name = str(w.p.d['pilot'].get('userName', ''))
    if (w.p.d['pilot'].get('factionId') == b.firma and not w.hero_dead and not w.jumping
            and math.hypot(*(a - c for a, c in zip(w.hero_pos(now), (nx, ny)))) < ESCORT_RANGE):
        p = 0.08 * (0.3 + b.o('sosyallik')) * (0.5 + b.o('yardimseverlik')) * (1 + 3 * max(0.0, b.memory.relation(name, now)))
        if random.random() < p:
            n.escort = ('h', now + duration, random.uniform(0, 2 * math.pi))
            b.memory.event(name, 'birlikte_avlandik', now)
            return
    allies = set(b.memory.allies(0.25, now))
    for m in w.npcs.values():
        if m is n or m.bot is None or not m.alive or m.bot.firma != b.firma or m.bot.name not in allies:
            continue
        if math.hypot(*(a - c for a, c in zip(m.mover.pos(now), (nx, ny)))) < ESCORT_RANGE and random.random() < 0.3:
            n.escort = (m.id, now + duration, random.uniform(0, 2 * math.pi))
            return


def escort(w, n, now):
    """Eşlik: liderin hedefi (senin seçtiğin uzaylı ya da arkadaş botun hedefi) gücü yetiyorsa onunki; hedef yoksa liderin
    yanında, kendi yerinde (formasyon) uçar -> bu düşüncede iş yaptı mı."""
    leader = _leader(w, n, now)
    if leader is None:
        n.__dict__.pop('escort', None)
        return False
    if n.target is None:
        t = w.target if leader[0] == 'h' else leader[1].target
        m = w.npcs.get(t) if t is not None else None
        if m is not None and m.alive and m.bot is None and not m.d.get('dost') and can_kill(n.bot, m):
            n.target = m.id
            return False                                 # hedefe yaklaşmayı olağan akış yapar
    if n.target is not None:
        return False
    lx, ly = w.hero_pos(now) if leader[0] == 'h' else leader[1].mover.pos(now)
    a = n.escort[2]
    hx, hy = lx + math.cos(a) * 280, ly + math.sin(a) * 280
    nx, ny = n.mover.pos(now)
    if math.hypot(hx - nx, hy - ny) > 200:
        _go_to(w, n, hx, hy, now, threshold=120)
    return True


def is_boss(m):
    name = str(m.d.get('ad', ''))
    return m.bot is None and ('Boss' in name or 'Uber' in name or bool(m.d.get('patron')))


def witness(w, kind, x, y, exclude=None, **f):
    """Haritada görülen olay (patron öldü, oyuncu öldü): 1.500 birimdeki botlardan en çok ikisi, konuşkanlığına göre, sohbette
    tepki verir (olay 'tanik'; kalıplar speech.py, Gelişmiş kipte dil modeli)."""
    count = 0
    for m in list(w.npcs.values()):
        if m.bot is None or not m.alive or m.id == exclude or count >= 2:
            continue
        mx, my = m.mover.pos(time.time())
        if math.hypot(mx - x, my - y) > 1500 or random.random() > 0.35 * m.bot.o('konuskanlik'):
            continue
        m.bot.event('tanik', sub=kind, **f)
        count += 1


def collect_box(w, n, now):
    """Yakındaki kutuya uçar ve alır (gerçek oyuncular gibi; kutu oyuncunun ekranından da kalkar) -> bununla meşgul mü.
    Bonus kutusu (yerine yenisi doğar), kendi kargo kutusu (cevherler kargosuna) ve kaba botlar ara sıra başkasınınkini (izin
    'kutu_calma'; aynı firmadansa onur kaybeder, oyuncu gibi). Grupta yalnız birine düşen ganimete (sahip) dokunmaz."""
    if n.target is not None and n.target in w.npcs:
        return False
    b = n.bot
    nx, ny = n.mover.pos(now)
    own = ('b', n.id)
    decision = n.__dict__.setdefault('stealing', {})
    en, best_score = None, 900.0
    for h, k in w.boxes.items():
        tip = k.get('tip')
        if k.get('event'):                                 # etkinlik kutusu: anahtarsız, herkes toplar
            if not b.permission.get('etkinlik', True) or k.get('sahip') is not None:
                continue
        elif k.get('keyed'):                          # anahtarlı ganimet kutusu: anahtarı varsa ya da yeşil anahtarı alırsa
            from . import loot as LT
            k_ = decision.get(h)
            if k_ is None or (k_ is not True and now > k_):         # "açamam" kararı 60 sn'de bir yeniden (anahtar gelmiş olabilir)
                decision[h] = True if tip in LT.LOOT.BOXES and LT.can_open(b, tip) else now + 60
            if decision[h] is not True:
                continue
        elif k.get('sahip') is not None or (tip != 'BONUS_BOX' and tip not in WD.CARGO_BOXES):
            continue
        if tip in WD.CARGO_BOXES and (not b.permission.get('kargo', True) or b.cargo_fill() >= 1):
            continue                                   # kargo kapalı ya da dolu
        owner_tag = k.get('owner_tag')
        if tip in WD.CARGO_BOXES and owner_tag is not None and tuple(owner_tag) != own and WD.SET.get('kargo_sahipligi'):
            if h not in decision:                         # başkasının kargosu: kaba bot ara sıra alır (kutu başına bir karar)
                decision[h] = is_theft(w, b, owner_tag)
            if not decision[h]:
                continue
        dd = math.hypot(k['x'] - nx, k['y'] - ny)
        if dd < best_score:
            en, best_score = h, dd
    if en is None:
        return False
    k = w.boxes[en]
    if best_score > 60:
        _go_to(w, n, k['x'], k['y'], now, threshold=40)
        return True
    if k.get('event'):
        from . import events as EV
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        decision.pop(en, None)
        if k['event'].get('yeniden_sn'):
            w.schedule(random.uniform(*k['event']['yeniden_sn']) * WD.SET.multiplier('kutu_yenilenme'), 'etk_kutu', k['tip'])
        EV.open_box(b, k['event'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k.get('keyed'):                               # açılış ganimet.ACMA_SN sürer (oyuncudaki gibi), sonra kutu alınır
        from . import loot as LT
        opening = getattr(n, 'opening', None)
        if not opening or opening[0] != en:
            n.opening = (en, now + LT.LOOT.OPEN_SEC)
            return True
        if now < opening[1]:
            return True
        n.opening = None
        del w.boxes[en]
        w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
        decision.pop(en, None)
        w.schedule(LT.LOOT.respawn_delay(k['tip']) * WD.SET.multiplier('kutu_yenilenme'), 'booty', k['tip'])
        LT.open_box(b, k['tip'])
        n.next_think = now + random.uniform(0.3, 1.0)
        return True
    if k['tip'] in WD.CARGO_BOXES:                     # cevherler sığdığı kadar; sığmayan kutuda kalır (oyuncudaki gibi)
        claimed = b.add_cargo(k.get('contents') or {})
        remaining = {t: int(v) - claimed.get(int(t), 0) for t, v in (k.get('contents') or {}).items() if int(v) - claimed.get(int(t), 0) > 0}
        b.ist('kargo_kutusu')
        owner_tag = k.get('owner_tag')
        if owner_tag is not None and tuple(owner_tag) != own and not k.get('stolen') and WD.SET.get('kargo_sahipligi'):
            k['stolen'] = True
            theft_penalty(w, b, owner_tag)
        if remaining:
            k['contents'] = remaining
            n.next_think = now + random.uniform(0.3, 1.0)
            return True
    del w.boxes[en]
    w.send([('RemoveCollectableCommand', {'collected': False, 'hash': en})])
    decision.pop(en, None)
    if k['tip'] == 'BONUS_BOX':
        w.schedule(random.uniform(30, 60), 'bonus')
        b.reward('kutu', ep=random.randint(0, 100), kredi=random.choice((0, 0, 100, 500, 1000)), uridyum=random.choice((0, 0, 10, 20, 50, 100)))
        b.ist('kutu')
    n.next_think = now + random.uniform(0.3, 1.0)
    return True


def _box_company(w, owner_tag):
    return w.p.d['pilot'].get('factionId') if owner_tag[0] == 'h' and owner_tag[1] == w.hid else bot_firma(owner_tag[1]) if owner_tag[0] == 'b' else None


def _stolen_today(b):
    """Botun bugünkü kargo alma sayacı {gun, n} (o günün ilk cezası 10, her seferinde iki katı)."""
    d = b.k.setdefault('cargo_theft', {})
    day = time.strftime('%Y-%m-%d', time.localtime(b.hour()))
    if d.get('gun') != day:
        d.update(gun=day, n=0)
    return d


def is_theft(w, b, owner_tag):
    """Başkasının kargo kutusunu alır mı. Düşman firmanınki cezasız: kaba bot ara sıra alır. Kendi firmasınınki onur kaybettirir
    (o gün 10, her seferinde iki katı): gerçek oyuncu bunu bilir, nadiren ve günde en çok bir kez el uzatır. Önceden bot her kutu
    için zar atıyordu; kalabalık haritada günde onlarca kutu alıp onurunu yüzbinlerce eksiye düşürüyordu (kullanıcı 2026-10-30)."""
    from . import admin_warnings as AW
    if not b.permission.get('kutu_calma', True) or AW.active(b, 'kutu'):
        return False                                     # yöneticinin kutu uyarısı (bot/yonetici_uyari.py)
    p = 0.35 * b.o('saldirganlik') * (1 - b.o('yardimseverlik'))
    if _box_company(w, owner_tag) == b.firma:
        if _stolen_today(b)['n'] >= 1:
            return False                               # bugün bir kez ceza yedi: bir daha almaz
        p *= 0.15
    return random.random() < p


def theft_penalty(w, b, owner_tag):
    """Bot başkasının kargo kutusunu aldı: sahibi aynı firmadansa onur kaybı (oyuncuyla aynı kural: o gün 10, her seferinde x2);
    sahibi oyuncuysa bot onun gözünde kötüleşmez ama oyuncu kutusunu kaybeder."""
    fac = _box_company(w, owner_tag)
    b.ist('kutu_caldi')
    if fac != b.firma:
        return
    d = _stolen_today(b)
    b.earn(onur=-10 * 2 ** min(d['n'], 16))
    d['n'] += 1
    if owner_tag[0] == 'b':
        o = _bot(owner_tag[1])
        if o is not None:
            o.memory.event(b.name, 'hakaret', b.hour(), multiplier=0.5)


def recover(w, n, now, d):
    """Hasarlı ama kimse vurmuyor: avı bırakıp durur, kalkan ve onarım robotu dolana dek bekler (kendi üssüne yakınsa istasyona
    çekilir) -> bekliyor mu. Gerçek oyuncu yarım canla yeni uzaylıya dalmaz."""
    ratio = (n.hp + n.shield) / max(1, d['can'] + d['kalkan'])
    b = n.bot
    if getattr(n, 'recovering', False):
        if ratio >= 0.9:
            n.recovering = False
            return False
    elif ratio >= 0.3 + 0.3 * (1 - b.o('risk')):
        return False
    n.recovering = True
    n.target = None
    s = w.station
    nx, ny = n.mover.pos(now)
    if s and s.get('type') == b.firma and math.hypot(s['posX'] - nx, s['posY'] - ny) < 4000:
        return rest(w, n, now)
    _stop(w, n, now)
    n.next_think = now + random.uniform(2, 4)
    return True


def park_spot(w, n, now):
    """Dinlenecek yer, botlar arasında çeşitli (kullanıcı isteği: hepsi istasyonun aynı yerinde durmasın): kendi istasyonunun
    çevresinde geniş bir halka, bir portalın güvenli bölgesi ya da olduğu yer (haritanın ortasında "afk"). Öteki botların park
    yerlerine 300 birimden yakın olmaz."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    full = [getattr(m, 'park', None) for m in w.npcs.values() if m.bot is not None and m is not n]
    full = [p for p in full if p is not None]
    portals = [g for g in H.gates(w.map_id, b.firma) if not g.get('ucret') and math.hypot(g['x'] - nx, g['y'] - ny) < 6000]
    for _ in range(12):
        k = random.random()
        if s and s.get('type') == b.firma and k < 0.5:
            a, r = random.uniform(0, 2 * math.pi), random.uniform(350, 1700)
            p = (s['posX'] + math.cos(a) * r, s['posY'] + math.sin(a) * r)
        elif portals and k < 0.75:
            g = random.choice(portals)
            a, r = random.uniform(0, 2 * math.pi), random.uniform(150, 650)
            p = (g['x'] + math.cos(a) * r, g['y'] + math.sin(a) * r)
        else:
            p = (nx + random.uniform(-200, 200), ny + random.uniform(-200, 200))
        p = (max(400, min(w.map_w - 400, p[0])), max(400, min(w.map_h - 400, p[1])))
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 300 for q in full):
            return p
    return p


def rest(w, n, now):
    """Dinlenme: kendi istasyonunun çevresinde bir yere park eder ve orada durur ("afk", sohbet, alışveriş); arada uzun aralıklarla
    yer değiştirir. Park yeri bir kez seçilir (önceden her saniye yeni rastgele nokta seçip istasyon çevresinde zikzak çiziyordu)."""
    b = n.bot
    s = w.station
    nx, ny = n.mover.pos(now)
    park = getattr(n, 'park', None)
    if park is None or now > getattr(n, 'park_end', 0):
        park = park_spot(w, n, now)
        n.park, n.park_end = park, now + random.uniform(90, 400)
    if math.hypot(park[0] - nx, park[1] - ny) > 60:
        _go_to(w, n, park[0], park[1], now, threshold=100)
    else:
        n.next_think = now + random.uniform(3, 8)        # duruyor
