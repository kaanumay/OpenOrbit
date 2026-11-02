"""Boosters: timed percentage bonuses (in the profile "boosters"; values data/items.json "boosters").

Client (record): AttributeBoosterUpdateCommand {boostedAttributes: [BoosterUpdateModule {attributeType, value}] (10 types, in the
record's order), boostedDetailsUpdate: [BoosterPlayerDetailModule {lootId, secondsLeft}], boostedDetailsRemove: [BoosterDetailModule
{lootId}]}. The player in the record had no boosters (all 0); the value is a percentage number (the client's texts "+%BOOSTERVALUE%%"),
not verified live. Booster dropped by an alien: BoosterFoundOnMapCommand {lootId, hours}.
Rules (wiki, belgeler/wiki/extras_cpu_tech.md): a shop booster lasts, from the moment it is bought, as long as the client's hour table says
(B01/B02 10, DLB 1, KAPPA 5, EP-50 24 …; items.json boosters); ones dropped by aliens last 1-10 hours. Every booster's time runs only
while online (the client's FAQ booster_main_p: "Time will only be deducted on the space map"; Fandom Booster: "only runs out in game, not
when you are logged out"; player report 2026-11-02: a 10-hour shop booster was gone after a night offline). Boosters of the same type are summed, with a per-type cap (damage 35%, HP 30%, shield 80% …). When
several of the same booster are obtained, their durations add up.
"""
import json, os, random, time
import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))['boosters']
O6 = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))['boosters']     # Ö6 (tools/items_o6.py)
for _loot, _effect in O6['kinds'].items():           # bb-01 bonus box, qr-01 quest reward, prm-b01 amount of Hybrid Alloy/Indoctrine Oil …
    B['kinds'].setdefault(_loot, _effect)
ALIAS = O6['alias']                              # boosters the client does not know -> [[equivalent, hours]] (MAX-BP01, NBX, NQR, PCOMB …)
ATTRS = ['ABILITY_COOLDOWN_TIME', 'COLLECT_RESOURCES', 'COLLECT_RESOURCES_NEWBIE', 'EXPERIENCE_POINTS', 'HITPOINTS', 'HONOUR_POINTS',
         'DAMAGE', 'REPAIR', 'SHIELD', 'SHIELD_REGENERATION']                      # order in the record
# client type -> the server's bonus key (player_profile.mods(): summed with formation and drone designs)
MOD_KEYS = {'DAMAGE': ('laser', 'rocket'), 'HITPOINTS': ('hp',), 'SHIELD': ('shield',), 'SHIELD_REGENERATION': ('shield_regen',),
            'REPAIR': ('repair',), 'EXPERIENCE_POINTS': ('ep',), 'HONOUR_POINTS': ('honor',), 'COLLECT_RESOURCES': ('cargo',),
            'ABILITY_COOLDOWN_TIME': ('cooldown',)}


def mod(name, **f):
    f['_'] = name
    return f


def is_booster(loot):
    return loot in B['kinds'] or loot in ALIAS


def state(p):
    """Boosters in the profile: lootId -> {remaining: seconds left (counted down online by tick), end_time: old saves only}."""
    st = p.d.setdefault('boosters', {})
    for e in st.values():
        if e.get('end_time'):           # old save: a shop booster ran on the wall clock; what is left of it from now on runs online only
            e['remaining'] = e.get('remaining', 0) + max(0.0, e['end_time'] - time.time())
            e['end_time'] = 0
            p.dirty = True
    return st


def left(p, loot, now=None):
    e = state(p).get(loot)
    if not e:
        return 0
    return max(0.0, e.get('end_time', 0) - (now or time.time())) + e.get('remaining', 0)


def active(p, now=None):
    now = now or time.time()
    return {l: left(p, l, now) for l in state(p) if left(p, l, now) > 0}


def values(p, now=None):
    """Type -> percentage (sum of the active boosters, capped by the type's limit)."""
    out = {}
    k = SET.multiplier('booster_power')                    # panel: the effect of the boosters (and their caps)
    for loot in active(p, now):
        for a, v in B['kinds'].get(loot, {}).items():
            if a in ATTRS:
                out[a] = out.get(a, 0) + v * k
    return {a: min(v, B['cap'][a] * k) if a in B['cap'] else v for a, v in out.items()}


def mods(p, now=None):
    """By the server's bonus keys (ratio): DAMAGE -> laser and rocket, HITPOINTS -> HP …; ones without a type by their name (hit, npc)."""
    out = {}
    for a, v in values(p, now).items():
        for k in MOD_KEYS.get(a, ()):
            out[k] = out.get(k, 0) + v / 100.0
    for l in active(p, now):                       # effects without a type in the display: hit (DMG-H01), npc (NPC-B01), pet_ep
        for k, v in B['kinds'][l].items():
            if k not in ATTRS:
                out[k] = out.get(k, 0) + v / 100.0
    return out


def add(p, loot, n=1, seconds=None, hours=None):
    """n of them from the shop (hours: its own duration), or if seconds is given, one dropped by an alien; both run online only.
    Alias (a booster the client does not know): the equivalents with their own hours."""
    if loot in ALIAS:
        for other, h in ALIAS[loot]:
            add(p, other, n, hours=h)
        return
    with p.lock:
        e = state(p).setdefault(loot, {'end_time': 0, 'remaining': 0})
        if seconds is None:
            h = hours or B['hour'].get(loot)
            seconds = n * (h * 3600 if h else B['duration_sec'])
        e['remaining'] = e.get('remaining', 0) + seconds * SET.multiplier('booster_duration')     # panel: booster duration
        p.dirty = True


def tick(p, now, dt):
    """Time spent online: the boosters' remaining time decreases. -> lootIds whose time ran out."""
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
        # the removed one is also a BoosterPlayerDetailModule: the client deletes the row by its key (class id + lootId)
        # (BoosterModel.RemoveItem); when the base class BoosterDetailModule was sent, the key did not match and the row's time stayed
        # frozen (live test 2026-10-17)
        boostedDetailsRemove=[mod('BoosterPlayerDetailModule', lootId=l, secondsLeft=0) for l in removed]))


def drop_for(npc_name):
    """Does a Boss/Uber alien drop a booster (wiki: "Boss/Uber-Alien (1-10h)" and the 1-hour DLB/NPC/REP-S01 types; probability is an
    adaptation). Types with equal weight. -> (lootId, hours) or None."""
    d = B['drop']
    kind = 'boss' if npc_name.startswith('..::{') else 'uber' if npc_name.startswith('( Uber') else None
    if not kind or random.random() >= SET.chance('drop', d['probability'][kind], 'booster'):
        return None
    loot, hours = random.choice([(l, None) for l in d['kinds']] + [(l, 1) for l in d.get('kinds_1h', ())])     # 1-hour types are fixed at 1 h
    return loot, hours or random.randint(*d['hour'])
