"""Boosterlar: süreli yüzde bonuslar (profilde "boosterlar"; değerler data/items.json "boosterlar").

İstemci (kayıt): AttributeBoosterUpdateCommand {boostedAttributes: [BoosterUpdateModule {attributeType, value}] (10 tür, kayıttaki
sırayla), boostedDetailsUpdate: [BoosterPlayerDetailModule {lootId, secondsLeft}], boostedDetailsRemove: [BoosterDetailModule
{lootId}]}. Kayıttaki oyuncunun boosterı yoktu (hepsi 0); değer yüzde sayısı (istemcinin metinleri "+%BOOSTERVALUE%%"), canlıda
doğrulanmadı. Uzaylıdan düşen booster: BoosterFoundOnMapCommand {lootId, hours}.
Kurallar (wiki, belgeler/wiki/extras_cpu_tech.md): mağaza boosterı alındığı andan istemcinin saat tablosu kadar sürer (B01/B02 10, DLB
1, KAPPA 5, EP-50 24 …; items.json boosterlar.saat), çevrimdışı da işler; uzaylıdan düşenler
1-10 saat, çevrimdışı durur. Aynı türdekiler toplanır, tür başına üst sınır (hasar %35, can %30, kalkan %80 …). Aynı boosterdan
birkaç tane alınca süreler eklenir.
"""
import json, os, random, time
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['boosters']
O6 = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))['boosters']     # Ö6 (tools/esyalar_o6.py)
for _loot, _effect in O6['kinds'].items():           # bb-01 bonus kutusu, qr-01 görev ödülü, prm-b01 Hybrid Alloy/Indoctrine Oil miktarı …
    B['kinds'].setdefault(_loot, _effect)
ALIAS = O6['alias']                              # istemcinin tanımadığı boosterlar -> [[eşdeğer, saat]] (MAX-BP01, NBX, NQR, PCOMB …)
ATTRS = ['ABILITY_COOLDOWN_TIME', 'COLLECT_RESOURCES', 'COLLECT_RESOURCES_NEWBIE', 'EXPERIENCE_POINTS', 'HITPOINTS', 'HONOUR_POINTS',
         'DAMAGE', 'REPAIR', 'SHIELD', 'SHIELD_REGENERATION']                      # kayıttaki sıra
# istemcinin türü -> sunucunun bonus anahtarı (profil.mods(): formasyon ve dron tasarımlarıyla toplanır)
MOD_KEYS = {'DAMAGE': ('laser', 'rocket'), 'HITPOINTS': ('can',), 'SHIELD': ('kalkan',), 'SHIELD_REGENERATION': ('shield_regen',),
            'REPAIR': ('repair',), 'EXPERIENCE_POINTS': ('ep',), 'HONOUR_POINTS': ('honor',), 'COLLECT_RESOURCES': ('cargo',),
            'ABILITY_COOLDOWN_TIME': ('cooldown',)}


def mod(name, **f):
    f['_'] = name
    return f


def is_booster(loot):
    return loot in B['kinds'] or loot in ALIAS


def state(p):
    """Profildeki boosterlar: lootId -> {end_time: mağazadakinin bittiği an, kalan: uzaylıdan düşenin kalan saniyesi}."""
    return p.d.setdefault('boosters', {})


def left(p, loot, now=None):
    e = state(p).get(loot)
    if not e:
        return 0
    return max(0.0, e.get('end_time', 0) - (now or time.time())) + e.get('remaining', 0)


def active(p, now=None):
    now = now or time.time()
    return {l: left(p, l, now) for l in state(p) if left(p, l, now) > 0}


def values(p, now=None):
    """Tür -> yüzde (etkin boosterların toplamı, türün üst sınırıyla)."""
    out = {}
    k = SET.multiplier('booster_power')                    # panel: boosterların etkisi (üst sınırları da)
    for loot in active(p, now):
        for a, v in B['kinds'].get(loot, {}).items():
            if a in ATTRS:
                out[a] = out.get(a, 0) + v * k
    return {a: min(v, B['cap'][a] * k) if a in B['cap'] else v for a, v in out.items()}


def mods(p, now=None):
    """Sunucunun bonus anahtarlarıyla (oran): DAMAGE -> lazer ve roket, HITPOINTS -> can …; türü olmayanlar adıyla (isabet, npc)."""
    out = {}
    for a, v in values(p, now).items():
        for k in MOD_KEYS.get(a, ()):
            out[k] = out.get(k, 0) + v / 100.0
    for l in active(p, now):                       # göstergede türü olmayan etkiler: isabet (DMG-H01), npc (NPC-B01), pet_ep
        for k, v in B['kinds'][l].items():
            if k not in ATTRS:
                out[k] = out.get(k, 0) + v / 100.0
    return out


def add(p, loot, n=1, seconds=None, hours=None):
    """Mağazadan n tane (süre gerçek zamanla işler; hours: kendi süresi) ya da seconds verilirse uzaylıdan düşen (çevrimdışı durur).
    Takma ad (istemcinin tanımadığı booster): eşdeğerleri kendi saatleriyle."""
    if loot in ALIAS:
        for other, h in ALIAS[loot]:
            add(p, other, n, hours=h)
        return
    now = time.time()
    with p.lock:
        e = state(p).setdefault(loot, {'end_time': 0, 'remaining': 0})
        if seconds is None:
            h = hours or B['hour'].get(loot)
            duration = h * 3600 if h else B['sure_sn']
            e['end_time'] = max(e.get('end_time', 0), now) + n * duration * SET.multiplier('booster_sure')     # panel: booster süresi
        else:
            e['remaining'] = e.get('remaining', 0) + seconds * SET.multiplier('booster_sure')
        p.dirty = True


def tick(p, now, dt):
    """Çevrimiçi geçen süre: uzaylıdan düşen boosterın süresi (mağazadaki bitince) azalır. -> süresi biten lootId'ler."""
    gone = []
    with p.lock:
        for loot, e in list(state(p).items()):
            if e.get('remaining', 0) > 0 and e.get('end_time', 0) <= now:
                e['remaining'] = max(0, e['remaining'] - dt)
                p.dirty = True
            if left(p, loot, now) <= 0:
                del state(p)[loot]
                gone.append(loot)
                p.dirty = True
    return gone


def update_cmd(p, removed=(), now=None):
    v = values(p, now)
    return ('AttributeBoosterUpdateCommand', dict(
        boostedAttributes=[mod('BoosterUpdateModule', attributeType=a, value=float(v.get(a, 0))) for a in ATTRS],
        boostedDetailsUpdate=[mod('BoosterPlayerDetailModule', lootId=l, secondsLeft=int(s)) for l, s in sorted(active(p, now).items())],
        # kaldırılan da BoosterPlayerDetailModule: istemci satırı (sınıf kimliği + lootId) anahtarıyla siler (BoosterModel.RemoveItem);
        # taban sınıf BoosterDetailModule gidince anahtar tutmuyor, satır süresi donmuş kalıyordu (canlı deneme 2026-10-17)
        boostedDetailsRemove=[mod('BoosterPlayerDetailModule', lootId=l, secondsLeft=0) for l in removed]))


def drop_for(npc_name):
    """Boss/Uber uzaylıdan booster düşer mi (wiki: "Boss/Uber-Alien (1-10h)" ve 1 saatlik DLB/NPC/REP-S01 türleri; olasılık uyarlama).
    Türler eşit ağırlıkla. -> (lootId, saat) ya da None."""
    d = B['drop']
    kind = 'boss' if npc_name.startswith('..::{') else 'uber' if npc_name.startswith('( Uber') else None
    if not kind or random.random() >= SET.chance('drop', d['probability'][kind], 'booster'):
        return None
    loot, hours = random.choice([(l, None) for l in d['kinds']] + [(l, 1) for l in d.get('kinds_1h', ())])     # 1 saatlik türler sabit 1 sa
    return loot, hours or random.randint(*d['hour'])
