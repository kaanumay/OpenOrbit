"""Ship abilities of the bot pilots' ships (bot/ship.py's bodies): which abilities a bot's ship has, when it uses them, their effect on
the map and what the client sees. The player's abilities are ship_ability.py (profile bound); data: data/ship_abilities.json, the same
values (the ship's own duration/cooldown/effect, the design multipliers; the cooldown starts when the effect ends).

The face the team tactics (bot/tactics.py) and the body (bot/ship.py) use:
  kinds(n) -> the ability classes the ship has (KINDS); has(n, kind)
  think(w, n, now) -> True when an ability was used at this think step (the body calls it; the ship uses what the moment asks for)
  allies(w, n, now) -> the uids on the bot's side here (w.hid for the player)
  support_wish(w, n, now) -> None or (uid, x, y, reach): an ally in need this ship has a ready ability for; the caller flies it there
  request(w, n, kind, now, target=None) -> True when a ready ability of that class was used on the tactics' order

State: cooldowns on the pilot (b.ab_ready: they survive the body leaving the map, death and a new body), the running effects on the body
(n.ab_on: they end with it). Effects reach the others through the paths that already exist: a bot through bot/ship.bot_damage, fire,
speed (n.effect for slow/freeze/marker/weak shield, like the player's abilities on aliens), the player's hits on a bot through
BotShip.damage_reduction / damage_hook / hp_floor (world.hit_npc), the player through hero_effect (slow, frozen, 'skill' mods into
hurt_hero), set_hull (heal, Shield Disarray) and hurt_hero (area damage, beam, reflected damage).
What the client sees: the messages ship_ability.Engine sends for the player's own use, with the bot as activator (visual_on / visual_off);
a heal or shield beam to the ally (AbilityEffectActivationCommand 101 / 104: AbilityEffectActivationAssemblyHelper draws HealBeamEffect /
ShieldBeamEffect from the activator to targetIds[0]) and Nano-Cluster's targets (0|n|SD|A|1|..|targets: EventAssemblySkills.SolaceEffect
draws on every target). Abilities left out (LEFT_OUT) have no effect that the bots' mechanics can make real; they are never used.
"""
import math, random, time

import ship_ability as SA
from legacy_protocol import legacy

ABILITIES, SHIPS = SA.ABILITIES, SA.SHIPS
KINDS = ('heal_self', 'heal_ally', 'shield_ally', 'defense', 'burst', 'debuff', 'control', 'area', 'speed', 'cloak', 'taunt', 'vision')

CLASS = {
    'ability_solace': ('heal_self', 'heal_ally'), 'ability_solace-plus_nano-cluster-repairer-plus': ('heal_self', 'heal_ally'),
    'ability_aegis_hp-repair': ('heal_self', 'heal_ally'), 'ability_aegis_repair-pod': ('heal_self', 'heal_ally'),
    'ability_aegis_shield-repair': ('shield_ally',), 'ability_liberator-plus_self-repair': ('heal_self',),
    'ability_spectrum': ('defense',), 'ability_sentinel': ('defense',), 'ability_citadel_fortify': ('defense',),
    'ability_citadel-plus_prismatic-endurance': ('defense',), 'ability_spectrum-plus_prismatic-reflecting': ('defense',),
    'ability_berserker_rvg': ('defense',), 'ability_paladin_last-stand': ('defense',), 'ability_tempest_volt-backup': ('defense',),
    'ability_orcus_assimilate': ('defense',),
    'ability_tartarus_rapid-fire': ('burst',), 'ability_tartarus-plus_rapid-fire-plus': ('burst',), 'ability_berserker_bsk': ('burst',),
    'ability_basilisk_heightened-valour': ('burst',), 'ability_holo_self-reversal': ('burst',), 'ability_mimesis_scramble': ('burst',),
    'ability_retiarus_chs': ('burst',), 'ability_retiarus-plus_chsp': ('burst',), 'ability_tempest_volt-discharge': ('burst',),
    'ability_hecate_particle-beam': ('burst',), 'ability_hecate-plus_particle-beam-plus': ('burst',),
    'ability_diminisher': ('debuff',), 'ability_venom': ('debuff',), 'ability_spearhead_target-marker': ('debuff',),
    'ability_spearhead-plus_neutralizing-marker': ('debuff',), 'ability_disruptor_shield-disarray': ('debuff',),
    'ability_disruptor_ddol': ('debuff',), 'ability_pusat-plus_speed-sap': ('debuff', 'speed'),
    'ability_goliath-x_frozen-claw': ('control',), 'ability_hyperion_ga': ('control', 'area'), 'ability_keres_sle': ('control', 'speed'),
    'ability_solaris_inc': ('area',), 'ability_solaris-plus_incinerate-plus': ('area',), 'ability_paladin_ripper': ('area', 'defense'),
    'ability_tempest_voltage-link': ('area',), 'ability_zephyr_tbr': ('area',),
    'ability_lightning': ('speed',), 'ability_citadel_travel': ('speed',), 'ability_tartarus_speed-boost': ('speed',),
    'ability_tartarus-plus_speed-boost-plus': ('speed',), 'ability_retiarus_spc': ('speed',), 'ability_retiarus-plus_spcp': ('speed',),
    'ability_spearhead_ultimate-cloak': ('cloak',),
    'ability_citadel_draw-fire': ('taunt',), 'ability_citadel_protection': ('taunt', 'shield_ally'),
}
LEFT_OUT = {      # never used by a bot: no effect the map can make real (the reason goes into the report)
    'ability_spearhead_double-minimap': 'Recon only widens the hero\'s minimap; AbilityStopCommand 111 would clear the player\'s own double minimap',
    'ability_spearhead_jam-x': 'no range or effect value in the sources (data effect {})',
    'ability_spearhead-plus_jamx-creed': 'no effect value in the sources (data effect {})',
    'ability_basilisk_noxious-nebula': 'no effect value in the sources (data effect {})',
    'ability_berserker_shl': 'no share in the sources (data effect {})',
    'ability_disruptor_redirect': 'no effect value in the sources (data effect {})',
    'ability_holo_enemy-reversal': 'reverses the target\'s module negatives: bots have no modules, no values (data effect {})',
    'ability_keres_spr': 'no effect value in the sources (data effect {})',
    'ability_hammerclaw-plus_reallocate': 'shares group members\' damage dealt: no bot-side bookkeeping of that, low value',
    'ability_hyperion_qa': 'boosts the Singularity Drive: bots have none',
    'ability_hecate-plus_stockpile': 'charged by alien kills: no charge bookkeeping for bots',
    'ability_zephyr_mmt': 'charged by alien kills: no charge bookkeeping for bots',
    'ability_mimesis_phase-out': 'a 50-unit hop: no tactical use for a bot',
}
PROTECTION = 'ability_citadel_protection'
PROTECT_SHARE = 0.25            # wiki (fandom Citadel): "25% of damage taken by group members of nearby allies is redirected to the Citadel"
RANGE = 700                     # targeted abilities: the laser range (ship_ability.Engine's range)
GROUP_RANGE = SA.GROUP_RANGE    # group abilities (Nano-Cluster, Aegis, Protection): the engine's range
EMPTY = {}

# behaviour parameters (not game values): how the pilots decide
DECIDE_SEC = 0.9                # at most one ability decision per this long per ship (the think step is ~0.3-1.4 s)
ALLY_CACHE_SEC = 1.0            # allies() is rebuilt at most once a second per ship
SUPPORT_REACH = 3000            # a healer flies to an ally in need at most this far (farther: the ally is on its own)
HEAL_SELF_AT = 0.5              # HP share under which a pilot heals itself (moved by risk and patience)
HEAL_ALLY_AT = 0.55             # an ally's HP share under which a healer helps (moved by helpfulness)
SHIELD_AT = 0.35                # shield share under which a shield repair is used (self or ally under fire)
REACT = (0.35, 1.9)             # seconds from noticing to pressing (x (1.5 - skill)): no frame-perfect play
ALLY_REACT = (0.2, 0.9)         # "heal at once": a healer reacts faster to an ally than to its own needs
FORGET = 0.12                   # chance (x (1 - focus)) to overlook an ability that just became ready for FORGET_SEC
FORGET_SEC = (15, 60)
WASTE = 0.05                    # chance per decision in a fight (x (1 - skill)) to press a self ability at a poor moment
TRAVEL = 2200                   # a trip longer than this is worth a speed ability
AREA_ALIENS = 3                 # area abilities on aliens only on this many in reach (or on a boss)
BEAM_SEC = 4.0                  # HealBeamEffect's 4,000 ms: the beam is drawn again while the repair runs
SAID_SEC = 20.0                 # the 'healed' team event at most once per this long per bot (PLAN: BK's chat)
ISH_SEC = 3.0


# ------------------------------------------------------------------------------------------------ ship data (ship_ability's, per bot)
def row(b):
    """The ship's ability row: the worn design's own row if it has one (Centurion's ability designs, Holo designs, Hammerclaw Plus)."""
    e = b.k['gear']
    t = e.get('design')
    return (SHIPS.get(t) if t and t.startswith(e['ship'] + '_design_') else None) or SHIPS.get(e['ship']) or EMPTY


def items(b):
    return [i for i in row(b).get('skills', ()) if i in ABILITIES and i not in LEFT_OUT and i in CLASS]


def effect_def(r, item):
    e = ABILITIES[item]['effect']
    o = r.get('special', {}).get(item, {}).get('effect')
    return dict(e, **o) if o else e


def factor(r, item, key):
    return r.get('multipliers', {}).get(item, {}).get(key, 1.0)


def duration(r, item):
    o = r.get('special', {}).get(item, {})
    return o['duration_sec'] if 'duration_sec' in o else ABILITIES[item]['duration_sec'] * factor(r, item, 'duration')


def cooldown(r, item, b=None):
    """The ship's own value or the design multiplier; for a pilot b x the pack's game-setting profile's ability cooldown (bot/game_settings:
    'standard' 1.0, 'player' the player's panel value), as the player's cooldown takes the panel's."""
    o = r.get('special', {}).get(item, {})
    base = o['cooldown_sec'] if 'cooldown_sec' in o else ABILITIES[item]['cooldown_sec'] * factor(r, item, 'cooldown')
    gs = getattr(b, 'game_settings', None) if b is not None else None
    return base * gs.multiplier('skill_cooldown', 'skill') if gs is not None else base


def kinds(n):
    """The ability classes of the ship (cached per ship and design)."""
    b = getattr(n, 'bot', None)
    if b is None:
        return set()
    key = (b.k['gear'].get('ship'), b.k['gear'].get('design'))
    c = n.__dict__.get('ab_kinds')
    if c is None or c[0] != key:
        c = n.__dict__['ab_kinds'] = (key, frozenset(k for i in items(b) for k in CLASS[i]))
    return c[1]


def has(n, kind):
    return kind in kinds(n)


def allowed(b):
    return bool(b.permission.get('abilities', True))         # the pack's access setting (panel key 'abilities'; on by default)


def ready_at(b, item):
    return b.__dict__.setdefault('ab_ready', {}).get(item, 0.0)


def on(n):
    return n.__dict__.setdefault('ab_on', {})


def active(n, item, now):
    s = n.__dict__.get('ab_on', EMPTY).get(item)
    return s is not None and now < s['end']


def is_ready(n, item, now):
    return now >= ready_at(n.bot, item) and item not in n.__dict__.get('ab_on', EMPTY)


# ------------------------------------------------------------------------------------------------ the running effects as numbers
def mods(n, now):
    """The bonuses of the running abilities ({laser, rocket, speed, laser_taken, damage_taken, shield_damage_taken, evasion,
    launcher_damage, fixed_speed}); fixed_speed the smallest (ship_ability.mods)."""
    a = n.__dict__.get('ab_on')
    if not a:
        return EMPTY
    out = {}
    r = row(n.bot)
    for i, s in a.items():
        if now >= s['end']:
            continue
        e = effect_def(r, i)
        for k, v in e.get('mods', EMPTY).items():
            out[k] = min(out.get(k, v), v) if k == 'fixed_speed' else out.get(k, 0) + v
        if 'rage_hp' in e:                                   # Berserk: each 1% of HP lost gives +1% laser damage
            out['laser'] = out.get('laser', 0) + max(0.0, 1 - n.hp / float(n.d['hp'] or 1)) * e['rage_hp']
        if 'reverse' in e:                                   # Self Reversal: bots have no modules -> the wiki's bonus
            for k, v in e['reverse'].items():
                out[k] = out.get(k, 0) + v
        y = e.get('cargo')
        if y:                                                # Volt Discharge: as much as the charge spent on activation
            for k, v in y.get('mods', EMPTY).items():
                out[k] = out.get(k, 0) + v * s.get('spent', 0)
    return out


def effect(n, key, now):
    """One effect key of the running abilities (mirror, absorb_hp, reflect_laser, undying ...) -> value or None."""
    a = n.__dict__.get('ab_on')
    if not a:
        return None
    r = row(n.bot)
    for i, s in a.items():
        if now < s['end']:
            v = effect_def(r, i).get(key)
            if v:
                return v
    return None


def out_factor(n, kind, now):
    """The bot's own damage: kind 'laser', 'rocket' or 'launcher'."""
    m = mods(n, now)
    if not m:
        return 1.0
    f = 1 + m.get('laser' if kind == 'laser' else 'rocket', 0)
    return max(0.0, f + (m.get('launcher_damage', 0) if kind == 'launcher' else 0))


def taken_factor(n, now, laser=True):
    """Damage taken by the bot: Fortify / Revenge / Ripper (damage_taken), Spectrum / Prismatic (laser_taken, lasers only)."""
    m = mods(n, now)
    if not m:
        return 1.0
    return max(0.0, 1 + m.get('damage_taken', 0)) * (max(0.0, 1 + m.get('laser_taken', 0)) if laser else 1.0)


def speed(n, base, now=None):
    """BotShip.speed: Afterburner, Speed Boost, Travel (fixed 450), Fortify (0), Revenge (-5%)."""
    m = mods(n, now or time.time())
    if not m:
        return base
    if 'fixed_speed' in m:
        return m['fixed_speed']
    return max(1, int(base * (1 + m.get('speed', 0))))


def protector(w, n, now):
    """A Citadel of the bot's side with Protection running within its range -> its ship or None."""
    for m in w.__dict__.get('ab_protect', ()):
        if m is not n and m.alive and active(m, PROTECTION, now) and m.bot.company == n.bot.company \
                and n.id in allies(w, m, now) and _dist(m, n, now) <= GROUP_RANGE:
            return m
    return None


def floor(n):
    """BotShip.hp_floor: 1 while Volt Back-up runs or Last Stand is set up and ready (world.hit_npc then calls at_floor)."""
    now = time.time()
    if n.__dict__.get('ab_on') and effect(n, 'undying', now):
        return 1
    armed = n.bot.__dict__.get('ab_armed')
    return 1 if armed and any(v and now >= ready_at(n.bot, i) and i in row(n.bot).get('skills', ()) for i, v in armed.items()) else 0


def at_floor(n, now=None):
    """A lethal hit while Volt Back-up runs (HP 1, then 3 s invulnerable, the ability ends) or Last Stand is set up (HP refills, the
    cooldown starts) -> True when it saved the ship (ship_ability.Engine.hold_on / last_stand)."""
    now = now or time.time()
    b, w = n.bot, n.__dict__.get('ab_w')
    r = row(b)
    sec = effect(n, 'undying', now)
    if sec:
        n.hp = max(n.hp, 1)
        n.immune_until = max(n.__dict__.get('immune_until', 0), now + sec)
        i = next(i for i, s in on(n).items() if now < s['end'] and effect_def(r, i).get('undying'))
        if w is not None:
            finish(w, n, i, now, early=True)
        return True
    for i in items(b):
        if effect_def(r, i).get('last_stand') and b.__dict__.get('ab_armed', EMPTY).get(i) and now >= ready_at(b, i):
            b.ab_armed[i] = False
            b.ab_ready[i] = now + cooldown(r, i, b)
            n.hp = n.d['hp']
            if w is not None:
                from . import ship as BG
                g = ABILITIES[i]['visual']
                v = dict(userId=n.id, modifier=g['appearance'], attribute=0, additionalAttribute='', count=0, activated=True)
                BG._broadcast(w, [('VisualModifierCommand', v)], n.id)
                w.later(SA.VISUAL_HOLD * 2, lambda: BG._broadcast(w, [('VisualModifierCommand', dict(v, activated=False))], n.id)
                        if n.alive else None)
            return True
    return False


def reduction(n, now=None, laser=True):
    """BotShip.damage_reduction (world.hit_npc: the player's hits): the bot's defence and a Citadel's Protection share. The world does
    not say yet whether the hit is a laser: laser_taken counts for every hit of the player (cross-domain: pass the attack type)."""
    now = now or time.time()
    w = n.__dict__.get('ab_w')
    keep = taken_factor(n, now, laser=laser)
    p = protector(w, n, now) if w is not None and w.__dict__.get('ab_protect') else None
    n.ab_hit = (keep, p, now)
    return 1 - keep * ((1 - PROTECT_SHARE) if p is not None else 1.0)


def cover_hero(w, dmg, now=None):
    """The player's damage under a Citadel bot's Protection (the player on its side): PROTECT_SHARE of it goes to the Citadel -> the rest.
    Called by world.hurt_hero once that hook exists (cross-domain); the source is unknown there, the Citadel takes it as an environment hit."""
    now = now or time.time()
    if dmg <= 0 or not w.__dict__.get('ab_protect'):
        return dmg
    for m in w.ab_protect:
        if m.alive and active(m, PROTECTION, now) and w.hid in allies(w, m, now) and _dist_uid(w, m, w.hid, now) <= GROUP_RANGE:
            from . import ship as BG
            BG.bot_damage(w, m, int(dmg * PROTECT_SHARE), 0, now, reactive=True)
            return int(dmg * (1 - PROTECT_SHARE))
    return dmg


def player_hit(n, dealt):
    """BotShip.damage_hook (world.hit_npc after the player's hit landed, dealt > 0): the Protection share goes to the Citadel, Revenge
    sends the raw damage back to the player, Prismatic Reflecting the laser part it took off."""
    w = n.__dict__.get('ab_w')
    hit = n.__dict__.get('ab_hit')
    if w is None or not hit or n.__dict__.get('ab_reflecting'):
        return
    keep, p, t = hit
    now = time.time()
    if now - t > 1.0:
        return
    from . import ship as BG
    share = (1 - PROTECT_SHARE) if p is not None else 1.0
    raw = dealt / max(0.05, keep * share)
    if p is not None:
        BG.bot_damage(w, p, int(raw * PROTECT_SHARE), w.hid, now, reactive=True)
    back = effect(n, 'mirror', now)
    refl = effect(n, 'reflect_laser', now)
    if (back or refl) and not w.hero_dead:
        n.ab_reflecting = True
        try:
            amount = raw * back if back else raw * share - dealt
            if amount >= 1:
                w.send(w.hurt_hero(int(amount), killer=n, source_asset=True, now=now))
        finally:
            n.ab_reflecting = False


# ------------------------------------------------------------------------------------------------ allies
def _pos(w, uid, now):
    if uid == w.hid:
        return None if w.hero_dead or w.jumping else w.hero_pos(now)
    m = w.npcs.get(uid)
    return m.mover.pos(now) if m is not None and m.alive else None


def _dist(a, b, now):
    ax, ay = a.mover.pos(now)
    bx, by = b.mover.pos(now)
    return math.hypot(ax - bx, ay - by)


def _player_side(w, n, now):
    """Is the player on this bot's side here: the same company in a team mode, its group, its escort leader, its clan."""
    b = n.bot
    if w.hero_dead or w.jumping:
        return False
    if getattr(getattr(w, 'gate', None), 'team_mode', False):
        return int(w.p.d['pilot'].get('factionId') or 0) == b.company
    if w.is_group_member(b.uid):
        return True
    e = n.__dict__.get('escort')
    if e and e[0] == 'h' and now <= e[1]:
        return True
    clan = int(w.p.d['pilot'].get('clanId') or 0)
    if clan and b.k.get('clan'):
        from . import society as T
        return clan == int(T.profile(b).d['pilot'].get('clanId') or 0)
    return False


def allies(w, n, now):
    """The uids on the bot's side on this map (w.hid for the player): its company's ships in a team mode; otherwise its group, its escort
    leader and those escorting it, its clan mates. Cached for ALLY_CACHE_SEC."""
    c = n.__dict__.get('ab_allies')
    if c is not None and now < c[0]:
        return c[1]
    b = n.bot
    team = getattr(getattr(w, 'gate', None), 'team_mode', False)
    grouped = w.is_group_member(b.uid)
    e = n.__dict__.get('escort')
    lead = e[0] if e and now <= e[1] else None
    clan = b.k.get('clan')
    out = set()
    for m in list(w.npcs.values()):
        if m is n or m.bot is None or not m.alive or m.bot.company != b.company:
            continue
        me = m.__dict__.get('escort')
        if (team or (grouped and w.is_group_member(m.bot.uid)) or m.id == lead or (me and me[0] == n.id and now <= me[1])
                or (clan and m.bot.k.get('clan') == clan)):
            out.add(m.id)
    if _player_side(w, n, now):
        out.add(w.hid)
    out = frozenset(out)
    n.ab_allies = (now + ALLY_CACHE_SEC, out)
    return out


def _ratios(w, uid):
    """(HP share, shield share) of an ally."""
    if uid == w.hid:
        g = w.p.d['ship']
        return g.get('hitPoints', 0) / float(g.get('hitMax') or 1), g.get('shield', 0) / float(g.get('shieldMax') or 1)
    m = w.npcs.get(uid)
    return m.hp / float(m.d['hp'] or 1), m.shield / float(m.d['shield'] or 1)


def _under_fire(w, uid, now):
    if uid == w.hid:
        return now - getattr(w, 'last_hurt', 0) < 4
    m = w.npcs.get(uid)
    return m is not None and any(now - t < 4 for t in m.attacker.values())


def _needy(w, n, now, reach, key=0, at=HEAL_ALLY_AT, fire=False):
    """The ally (not the ship itself) most in need within reach -> (share, uid, (x, y)) or None. key 0 HP, 1 shield."""
    best = None
    nx, ny = n.mover.pos(now)
    for uid in allies(w, n, now):
        p = _pos(w, uid, now)
        if p is None or math.hypot(p[0] - nx, p[1] - ny) > reach:
            continue
        r = _ratios(w, uid)[key]
        if r < at and (not fire or _under_fire(w, uid, now)) and (best is None or r < best[0]):
            best = (r, uid, p)
    return best


def support_wish(w, n, now):
    """The ally most in need that this ship has a ready (or nearly ready) repair, shield repair or Protection for, within SUPPORT_REACH
    -> (uid, x, y, reach) or None. reach: the ability's range (the caller flies the ship inside it)."""
    if not n.alive or not allowed(n.bot):
        return None
    k = kinds(n)
    if not k & {'heal_ally', 'shield_ally', 'taunt'}:
        return None
    b = n.bot
    soon = lambda kind: any(kind in CLASS[i] and now >= ready_at(b, i) - 2 and i not in n.__dict__.get('ab_on', EMPTY)
                            for i in items(b))
    at = HEAL_ALLY_AT + 0.1 * b.o('helpfulness')
    for kind, key, lim, fire in (('heal_ally', 0, at, False), ('shield_ally', 1, SHIELD_AT, True), ('taunt', 0, 0.8, True)):
        if kind in k and soon(kind):
            x = _needy(w, n, now, SUPPORT_REACH, key, lim, fire)
            if x is not None:
                return (x[1], x[2][0], x[2][1], GROUP_RANGE * 0.8)
    return None


# ------------------------------------------------------------------------------------------------ what the client sees
def _send(w, n, msgs, *uids):
    from . import ship as BG
    BG._broadcast(w, msgs, n.id, *uids)


def _vm(n, item, uid, attr, extra, is_on):
    """VisualModifierCommand of the ability; the ongoing ones are kept in n.vm (sent again with ShipCreateCommand: reload, view)."""
    g = ABILITIES[item]['visual']
    v = dict(userId=uid, modifier=g['appearance'], attribute=int(attr), additionalAttribute=extra, count=0, activated=is_on)
    if uid == n.id:
        if is_on:
            n.vm['ab|' + item] = v
        else:
            n.vm.pop('ab|' + item, None)
    return ('VisualModifierCommand', v)


def visual_on(w, n, item, s, now):
    """ship_ability.Engine.visual_on with the bot as activator (target: the enemy or, for repairs, the ally)."""
    g = ABILITIES[item].get('visual', EMPTY)
    t, ally = s.get('target'), s.get('ally')
    persistent = int(duration(row(n.bot), item) > 0 or bool(ABILITIES[item].get('toggle')))
    if 'appearance' in g:
        a = g.get('attr', 0)
        if a == 'mate':
            a = ally or n.id
        elif a == 'target':
            a = t or 0
        uid = t if g.get('on') == 'target' and t else n.id
        s['shown'] = (uid, a, str(t or 0) if g.get('extra') == 'target' else '')
        return [_vm(n, item, uid, a, s['shown'][2], True)]
    if 'entity' in g:                                    # Repair Pod (HEALING_POD 33) where the ship is
        x, y = n.mover.pos(now)
        SA.POD_UID[0] += 1
        s['pod'] = (SA.POD_UID[0], x, y)
        return [('AssetCreateCommand', dict(designId=0, clanId=0, showBubble=False, userName='', assetId=s['pod'][0], expansionStage=0,
                                            modifier=[], type={'_': 'AssetTypeModule', 'typeValue': g['entity']},
                                            detectedByWarnRadar=False, invisible=False, posX=int(x), posY=int(y),
                                            clanRelation={'_': 'ClanRelationModule', 'type': 0}, clanTag='', factionId=n.bot.company,
                                            visibleOnWarnRadar=False))]
    if 'effect' in g:
        if g['effect'] == 1:                             # Nano-Cluster: drawn on the ship and on every ally it repaired
            return [legacy('0|n|SD|A|1|0|%d' % n.id + ''.join('|%d' % u for u in s.get('healed', ())))]
        return [SA.sd_msg('A', g['effect'], persistent, n.id, t)]
    if 'launch' in g:
        out = [('AbilityStartCommand', dict(selectedAbilityId=g['launch'], activatorId=n.id, noStopCommand=False))]
        if g['launch'] in SA.ACTIVATION_ONLY or (g['launch'] in (101, 104) and ally):
            out.append(('AbilityEffectActivationCommand', dict(selectedAbilityId=g['launch'], activatorId=n.id, isPersistent=True,
                                                               targetIds=[(ally if g['launch'] in (101, 104) else t) or n.id])))
        if g['launch'] == SA.ULTIMATE_CLOAK:
            out.append(legacy('0|n|INV|%d|1' % n.id))
        return out
    return []


def look(n, now=None):
    """The running abilities' persistent visuals again (ship.extra_look: the ship shown anew, the map reloaded after a respawn): the old SD
    text of effects 2-6 and the 107/108 activation (Travel's speed trail, Protection's ring); VisualModifiers come with ShipCreateCommand
    (n.vm). A Repair Pod (10 s) is not created again (the asset may still be on the client)."""
    now = now or time.time()
    out = []
    for item, s in list(n.__dict__.get('ab_on', EMPTY).items()):
        g = ABILITIES[item].get('visual', EMPTY)
        if now >= s['end']:
            continue
        if g.get('effect', 1) != 1:
            out.append(SA.sd_msg('A', g['effect'], 1, n.id, s.get('target')))
        elif g.get('launch') in (107, 108):
            out.append(('AbilityEffectActivationCommand', dict(selectedAbilityId=g['launch'], activatorId=n.id, isPersistent=True,
                                                               targetIds=[n.id])))
    return out


def visual_off(w, n, item, s):
    g = ABILITIES[item].get('visual', EMPTY)
    t = s.get('target')
    if 'appearance' in g:
        sh = s.pop('shown', None)
        return [_vm(n, item, sh[0], sh[1], sh[2], False)] if sh else []
    if 'entity' in g:
        pod = s.pop('pod', None)
        return [('AssetRemoveCommand', {'assetType': {'_': 'AssetTypeModule', 'typeValue': g['entity']}, 'uid': pod[0]})] if pod else []
    if 'effect' in g:
        if g['effect'] == 1:
            return [('AbilityEffectDeActivationCommand', dict(selectedAbilityId=1, activatorId=n.id, targetIds=[n.id]))]
        return [SA.sd_msg('D', g['effect'], 0, n.id, t)]
    if 'launch' in g:
        return [('AbilityStopCommand', dict(selectedAbilityId=g['launch'], activatorId=n.id,
                                             targetIds=[(s.get('ally') if g['launch'] in (101, 104) else t) or n.id]))]
    return []


# ------------------------------------------------------------------------------------------------ effects on others
def heal(w, n, uid, hp=0, shield=0):
    """Repair an ally (the player or a bot ship) by the bot: the "+amount" line with the bot as healer (0|A|HL|healer|target|HPT/SHD|
    new|amount, world.heal_msgs) -> repaired amount."""
    if uid == w.hid:
        if w.hero_dead:
            return 0
        g = w.p.d['ship']
        h0, s0 = g.get('hitPoints', 0), g.get('shield', 0)
        w.p.set_hull(hp=h0 + hp if hp else None, shield=s0 + shield if shield else None)
        msgs = [legacy('0|A|HL|%d|%d|%s|%d|%d' % (n.id, w.hid, k, int(v), int(v) - int(v0)))
                for k, v0, v in (('HPT', h0, g['hitPoints']), ('SHD', s0, g.get('shield', 0))) if int(v) > int(v0)]
        if g['hitPoints'] > h0:
            msgs.insert(0, w.hp_msg())
        if g.get('shield', 0) > s0:
            msgs.insert(0, ('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)}))
        if msgs:
            w.send(msgs)
        return (g['hitPoints'] - h0) + (g.get('shield', 0) - s0)
    m = w.npcs.get(uid)
    if m is None or not m.alive:
        return 0
    h0, s0 = m.hp, m.shield
    m.hp, m.shield = min(m.d['hp'], m.hp + hp), min(m.d['shield'], m.shield + shield)
    msgs = [legacy('0|A|HL|%d|%d|%s|%d|%d' % (n.id, m.id, k, int(v), int(v) - int(v0)))
            for k, v0, v in (('HPT', h0, m.hp), ('SHD', s0, m.shield)) if int(v) > int(v0)]
    if msgs and w.target == m.id:
        msgs.append(w.selection(m))
    _send(w, n, msgs, m.id)
    return (m.hp - h0) + (m.shield - s0)


def _helped(w, n, uid, amount, now, stat=True):
    """Bookkeeping of help to an ally: heal statistics and the team callout (BK's chat; at most once per SAID_SEC)."""
    if amount <= 0 or uid == n.id:
        return
    if stat:
        n.bot.ist('ability_heal', int(amount))
        w.__dict__['ab_healed'] = w.__dict__.get('ab_healed', 0) + amount         # the lab's measure
    if now - n.__dict__.get('ab_said', 0) >= SAID_SEC:
        n.ab_said = now
        who = w.p.d['pilot'].get('userName', '') if uid == w.hid else w.npcs[uid].bot.name if uid in w.npcs else ''
        n.bot.event('team', sub='healed', who=who)


def _hit(w, n, uid, dmg, now, hull=False):
    """Ability damage from the bot to a unit: the player (hurt_hero), a bot ship (bot_damage) or an alien (ship.hit_npc)."""
    from . import ship as BG
    if dmg <= 0:
        return
    if uid == w.hid:
        if BG.can_attack_player(w, n, w, now) and (not hull or hull_ok(w)):
            w.send(w.hurt_hero(int(dmg), killer=n, source_asset=True, now=now, **({'hull_only': True} if hull else {})))
        return
    m = w.npcs.get(uid)
    if m is None or not m.alive:
        return
    if m.bot is not None:
        if BG.can_attack_bot(w, n, m, now):
            BG.bot_damage(w, m, int(dmg), n.id, now, killer_bot=n.bot, hull=hull)
    elif not m.d.get('friendly'):
        BG.hit_npc(w, n, m, int(dmg), now, 1, hull=hull)


def hull_ok(w):
    """Does the world's hurt_hero take hull_only (Venom's poison passes the shield; cross-domain hook)? Without it Venom is not used
    on the player (a shield-absorbed poison would be a different ability)."""
    v = HULL[0]
    if v is None:
        import inspect
        v = HULL[0] = 'hull_only' in inspect.signature(type(w).hurt_hero).parameters
    return v


HULL = [None]


def enemies(w, n, now, radius, center=None, aliens=True):
    """Enemy units within radius of the ship (or a point): [(uid, kind)] with kind 'player', 'bot', 'alien'."""
    from . import ship as BG
    cx, cy = center or n.mover.pos(now)
    out = []
    if not w.hero_dead and int(w.p.d['pilot'].get('factionId') or 0) != n.bot.company and BG.can_attack_player(w, n, w, now):
        hx, hy = w.hero_pos(now)
        if math.hypot(hx - cx, hy - cy) <= radius:
            out.append((w.hid, 'player'))
    for m in list(w.npcs.values()):
        if not m.alive or m is n:
            continue
        mx, my = m.mover.pos(now)
        if math.hypot(mx - cx, my - cy) > radius:
            continue
        if m.bot is not None:
            if BG.can_attack_bot(w, n, m, now):
                out.append((m.id, 'bot'))
        elif aliens and not m.d.get('friendly') and not getattr(m, 'hidden', False):
            out.append((m.id, 'alien'))
    return out


def _debuff(w, n, uid, kind, sec, value, item, now, **extra):
    """A status effect on a target: n.effect of a ship or alien; the player's hero effects (slow, frozen, or 'skill' mods)."""
    src = '%s|%d' % (item, n.id)
    if uid == w.hid:
        if kind == 'skill':
            w.hero_effect('skill', sec, value, src)
        else:
            w.hero_effect(kind, sec, value, src)
        return
    m = w.npcs.get(uid)
    if m is not None and m.alive:
        m.effect.add(kind, sec, value, src, now, **extra)


# ------------------------------------------------------------------------------------------------ activation
def use(w, n, item, now, target=None, ally=None):
    """Activate a ready ability of the bot's ship -> True. target: the enemy uid for targeted abilities; ally: the ally it is used for."""
    from . import ship as BG
    b = n.bot
    a = ABILITIES[item]
    r = row(b)
    e = effect_def(r, item)
    if not n.alive or now < ready_at(b, item) or (item in on(n) and not a.get('toggle')):
        return False
    if e.get('last_stand'):                              # set up once; refills HP on a lethal hit (at_floor)
        b.__dict__.setdefault('ab_armed', {})[item] = True
        return True
    if a.get('targeted'):
        p = _pos(w, target, now) if target is not None else None
        nx, ny = n.mover.pos(now)
        if p is None or math.hypot(p[0] - nx, p[1] - ny) > (BG.WD.COMBAT['sight_range'] if e.get('teleport_to_target') else RANGE):
            return False
    stop, cd = duration(r, item), cooldown(r, item, b)
    if a.get('toggle'):                                  # Speed Boost: on/off, cooldown between two presses
        s = on(n).get(item)
        b.ab_ready[item] = now + cd
        if s is not None:
            del on(n)[item]
            _send(w, n, visual_off(w, n, item, s))
        else:
            s = on(n)[item] = dict(end=float('inf'), start=now)
            _send(w, n, visual_on(w, n, item, s, now))
        respeed(w, n, now)
        return True
    b.ab_ready[item] = now + stop + cd
    s = on(n)[item] = dict(end=now + (stop if stop > 0 else SA.VISUAL_HOLD), start=now, target=target, ally=ally, last=now - 1)
    if 'mods' in e and 'fixed_speed' in e['mods']:
        if e['mods']['fixed_speed'] == 0:
            BG._stop(w, n, now)                           # Fortify: immobile
    healed = []
    if 'hp_percent' in e:                                # Nano-Cluster: at once, the ship and its allies in range
        k = e['hp_percent'] * factor(r, item, 'effect')
        n.hp = min(n.d['hp'], n.hp + n.d['hp'] * k)
        for uid in allies(w, n, now):
            if _pos(w, uid, now) is not None and _dist_uid(w, n, uid, now) <= GROUP_RANGE:
                mx = w.p.d['ship'].get('hitMax', 0) if uid == w.hid else w.npcs[uid].d['hp']
                amount = heal(w, n, uid, hp=mx * k)
                if amount > 0:
                    healed.append(uid)
                    _helped(w, n, uid, amount, now)
        s['healed'] = healed
    if 'target_shield_damage' in e:                      # Weaken Shields: the target's shield melts 1.5x (world.hit_npc, bot_damage,
        if target == w.hid:                              # hurt_hero's shield_damage_taken)
            _debuff(w, n, target, 'skill', stop, {'mods': {'shield_damage_taken': e['target_shield_damage'] - 1}}, item, now)
        else:
            _debuff(w, n, target, 'shield_damage_taken', stop, e['target_shield_damage'], item, now)
    if 'poison' in e:                                    # Venom: to the hull once a second (a world-level list: it outlives the caster)
        z = e['poison']
        w.__dict__.setdefault('ab_dots', []).append(dict(src=n, target=target, next=now, value=z['first'], increase=z['increase'],
                                                          max=z['max_count'], left=z['total'], end=now + stop + 1, hull=True))
    if 'target_damage' in e:                             # Target / Neutralizing Marker
        if target == w.hid:
            _debuff(w, n, target, 'skill', stop, {'mods': {'damage_taken': e['target_damage']}}, item, now)
        else:
            _debuff(w, n, target, 'damage_bonus', stop, e['target_damage'], item, now)
            if w.hid in allies(w, n, now):              # its side's minimap ping (MarkTargetCommandHandler) when the player is an ally
                tx, ty = _pos(w, target, now)
                w.send([('MarkTargetCommand', dict(userId=target, targetId=target, positionX=int(tx), positionY=int(ty)))])
    if 'draw_fire' in e:                                 # Draw Fire: aliens and enemy bots in range turn on the Citadel
        for uid, kind in enemies(w, n, now, e['draw_fire']):
            m = w.npcs.get(uid)
            if kind == 'alien' and m.d.get('damage', 0) > 0:
                m.bot_target, m.next_think = n.id, now
            elif kind == 'bot':
                m.target = n.id
    if e.get('cloak'):
        n.hidden = True
        b.ist('hidden')
    if 'target_shield_off' in e:                         # Shield Disarray: half of the target's shield off, back when it ends
        _disarray(w, n, target, e['target_shield_off'], stop, now)
    if 'target_fire_interval' in e:                      # DDoL: the target's laser fires every 3-5 s
        _debuff(w, n, target, 'shot_disrupted', stop, 0, item, now, interval=e['target_fire_interval'])
    if e.get('teleport_to_target'):                      # Sleight: to the target's position (instant MoveCommand)
        x, y = (int(c) for c in _pos(w, target, now))
        n.mover = BG.WD.Mover(x, y)
        n.movement = None
        _send(w, n, [('MoveCommand', dict(userId=n.id, x=x, y=y, timeToTarget=0))])
    if 'target_freeze' in e:                             # Frozen Claw
        _debuff(w, n, target, 'frozen', e['target_freeze'], 1.0, item, now)
    if 'target_slow' in e:                               # Speed Sap, Sleight
        _debuff(w, n, target, 'slow', stop, e['target_slow'], item, now)
    if 'area_slow' in e:                                 # Gravitational Anchor: the field at the target's position
        z = e['area_slow']
        for uid, kind in enemies(w, n, now, z['radius'], _pos(w, target, now)):
            _debuff(w, n, uid, 'slow', stop, SA.PVP_SLOW if kind == 'player' else z['ratio'], item, now)
    if 'chain_damage' in e:                              # Voltage Link: the target and the next nearest, more with each jump
        z, hit, cur, dmg = e['chain_damage'], [], target, float(e['chain_damage']['first'])
        while cur is not None and len(hit) < z['target']:
            hit.append(cur)
            _debuff(w, n, cur, 'frozen', 1.0, 1.0, item, now)
            _hit(w, n, cur, dmg, now)
            dmg *= 1 + z.get('increase', 0)
            c = _pos(w, cur, now)
            near = [(math.hypot(p[0] - c[0], p[1] - c[1]), u) for u, _ in enemies(w, n, now, z['range'], c)
                    if u not in hit for p in [_pos(w, u, now)] if p is not None] if c else []
            cur = min(near)[1] if near else None
        for i in items(b):                               # Volt Discharge: each jump is one charge
            y = effect_def(r, i).get('cargo')
            if y and y['source'] == 'chain':
                ch = b.__dict__.setdefault('ab_charge', {})
                ch[i] = min(y['maximum'], ch.get(i, 0) + len(hit) - 1)
    if 'cargo' in e:
        s['spent'] = b.__dict__.setdefault('ab_charge', {}).pop(item, 0)
    if 'triangle_blast' in e:                            # Triple Barrage: three blasts in a triangle behind the target
        u, (hx, hy), (tx, ty) = e['triangle_blast'], n.mover.pos(now), _pos(w, target, now)
        d = math.hypot(tx - hx, ty - hy) or 1.0
        ux, uy, gap = (tx - hx) / d, (ty - hy) / d, u['distance']
        for cx, cy in ((tx + ux * gap, ty + uy * gap), (tx + 2 * ux * gap - uy * gap, ty + 2 * uy * gap + ux * gap),
                       (tx + 2 * ux * gap + uy * gap, ty + 2 * uy * gap - ux * gap)):
            for uid, _ in enemies(w, n, now, u['radius'], (cx, cy)):
                _hit(w, n, uid, u['damage'], now)
    if 'rocket_cooldown_ms' in e:                        # Rapid Fire: the rocket ready at once
        n.rocket_ready = now
    if 'reload' in e:                                    # Charge Shot: charges on the target, strikes at the end
        s['charge'] = now
    if item in SA.HECATE_BEAM:                           # Particle Beam: 5 s at the target (forum 143093)
        h = SA.HECATE_BEAM[item]
        w.__dict__.setdefault('ab_dots', []).append(dict(src=n, target=target, next=now + 1, value=h['first'], increase=h['increase'],
                                                          max=None, left=None, end=now + h['duration_sec'], slow=h['slow'], item=item))
    if item == PROTECTION:
        w.__dict__.setdefault('ab_protect', []).append(n)
        w.ab_protect = [m for m in w.ab_protect if m.alive and m.__dict__.get('ab_on')]
    _send(w, n, visual_on(w, n, item, s, now), *([target] if target is not None else []))
    if 'mods' in e or 'reverse' in e:
        respeed(w, n, now)
    b.ist('ability')
    if ally is not None and ally != n.id and not healed and item not in ('ability_aegis_hp-repair', 'ability_aegis_shield-repair',
                                                                          'ability_aegis_repair-pod'):
        _helped(w, n, ally, 1, now, stat=False)          # Protection / Draw Fire for an ally under fire
    return True


def _dist_uid(w, n, uid, now):
    p = _pos(w, uid, now)
    if p is None:
        return float('inf')
    x, y = n.mover.pos(now)
    return math.hypot(p[0] - x, p[1] - y)


def _disarray(w, n, uid, share, sec, now):
    if uid == w.hid:
        g = w.p.d['ship']
        off = int(g.get('shield', 0) * share)
        w.p.set_hull(shield=g.get('shield', 0) - off)
        w.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])

        def back():
            if not w.hero_dead:
                w.p.set_hull(shield=g.get('shield', 0) + off)
                w.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
    else:
        m = w.npcs.get(uid)
        off = int(m.shield * share)
        m.shield -= off

        def back():
            if m.alive:
                m.shield = min(max(m.d.get('shield', 0), m.shield), m.shield + off)
    w.later(max(sec, SA.VISUAL_HOLD), back)


def respeed(w, n, now):
    """Speed changed (an ability on or off): the ongoing flight is sent again at the new speed (the client re-tweens only on a MoveCommand)."""
    from . import ship as BG
    if n.mover.t1 > now and n.movement is not None:
        x, y = n.movement
        n.movement = None
        BG._go_to(w, n, x, y, now)


def finish(w, n, item, now, early=False):
    """The effect ended (time, death of the ship, Volt Back-up triggered, cloak broken by firing): the visual goes, Weaken Shields takes 30% of
    the bot's own shield, Charge Shot strikes; an early end moves the cooldown forward by the time left (Engine.end_now)."""
    s = on(n).pop(item, None)
    if s is None:
        return
    b = n.bot
    r = row(b)
    e = effect_def(r, item)
    if early and now < s['end'] < float('inf'):
        b.ab_ready[item] = ready_at(b, item) - (s['end'] - now)
    msgs = visual_off(w, n, item, s)
    if 'reload' in e and n.alive:
        _discharge(w, n, item, s, e, now)
    if 'shield_loss' in e and n.alive:
        n.shield = n.shield * (1 - e['shield_loss'])
    if e.get('cloak') and n.__dict__.get('hidden'):
        n.hidden = False
        msgs.append(legacy('0|n|INV|%d|0' % n.id))
    if n.alive:
        _send(w, n, msgs)
        if 'mods' in e or 'reverse' in e:
            respeed(w, n, now)


def _discharge(w, n, item, s, e, now):
    """Charge Shot: the charged damage to the target (in Plus split among those within the split radius) and its visuals (Engine.discharge)."""
    d, t = e['reload'], s.get('target')
    dmg = min(d['maximum'], d['per_second'] * (now - s.get('charge', now)))
    c = _pos(w, t, now)
    if c is None or dmg <= 0:
        return
    hit = [t] + ([u for u, _ in enemies(w, n, now, d['split_radius'], c) if u != t] if d.get('split_radius') else [])
    if ABILITIES[item].get('visual', EMPTY).get('appearance') == 147:
        out, shot, hv = SA.CHSP_VISUALS[False]
        _send(w, n, [('PlayVisualEffectCommand', dict(activatorId=n.id, targetIds=[], visualEffect=out)),
                     ('PlayVisualEffectCommand', dict(activatorId=n.id, targetIds=[t], visualEffect=shot))] +
              [('PlayVisualEffectCommand', dict(activatorId=u, targetIds=[], visualEffect=hv)) for u in hit], t)
    for u in hit:
        _hit(w, n, u, dmg / len(hit), now)


def on_remove(w, n, now=None):
    """The ship leaves the map (death, jump, the player's map change): its effects end, the cooldowns move forward by the time left
    (visuals are not sent: the ship is gone). A Repair Pod's asset is removed."""
    now = now or time.time()
    for item in list(n.__dict__.get('ab_on', EMPTY)):
        s = on(n)[item]
        if s.get('pod'):
            _send_all(w, visual_off(w, n, item, dict(s)))
        if now < s['end'] < float('inf'):
            n.bot.ab_ready[item] = ready_at(n.bot, item) - (s['end'] - now)
        del on(n)[item]


def _send_all(w, msgs):
    if msgs:
        w.send(msgs)


# ------------------------------------------------------------------------------------------------ over time
def tick(w, n, now):
    """Every step of the body (cheap when nothing runs): ends, repairs per second, area damage, shield melt, Charge Shot range,
    the cloak broken by firing; the map's damage-over-time list once a second (Venom, Particle Beam: they outlive the caster)."""
    n.__dict__['ab_w'] = w
    if now >= w.__dict__.get('ab_dot_t', 0) and w.__dict__.get('ab_dots'):
        w.ab_dot_t = now + 0.25
        dots(w, now)
    a = n.__dict__.get('ab_on')
    if not a or now < n.__dict__.get('ab_next', 0):
        return
    n.ab_next = now + 0.25
    r = row(n.bot)
    for item, s in list(a.items()):
        e = effect_def(r, item)
        if now >= s['end']:
            finish(w, n, item, now)
            continue
        if e.get('cloak') and not n.__dict__.get('hidden'):
            finish(w, n, item, now, early=True)          # fired: visible again (active_items.decloak sent INV 0)
            continue
        if now - s['last'] < 1.0:
            continue
        s['last'] = now
        stop = max(duration(r, item), 1)
        if 'hp_repair' in e or 'shield_repair' in e:     # Aegis / Hammerclaw / Liberator Plus / Repair Pod: an equal share per second
            key = 'hp_repair' if 'hp_repair' in e else 'shield_repair'
            own = e[key] * factor(r, item, 'effect') / stop
            n.hp, n.shield = (min(n.d['hp'], n.hp + own), n.shield) if key == 'hp_repair' else (n.hp, min(n.d['shield'], n.shield + own))
            if item.startswith('ability_aegis'):         # HP / Shield Repair: the selected ally (ALLY_REPAIR: 280k / 125k), the Repair Pod:
                part = (SA.ALLY_REPAIR.get(item, {}).get(key) or e[key]) / stop      # every ally around it (fandom Aegis)
                c = s['pod'][1:] if s.get('pod') else None
                for uid in (allies(w, n, now) if c else [s['ally']] if s.get('ally') else []):
                    p = _pos(w, uid, now)
                    x, y = c or n.mover.pos(now)
                    if p is not None and math.hypot(p[0] - x, p[1] - y) <= GROUP_RANGE:
                        got = heal(w, n, uid, **{('hp' if key == 'hp_repair' else 'shield'): part})
                        _helped(w, n, uid, got, now)
                g = ABILITIES[item].get('visual', EMPTY).get('launch')
                if g in (101, 104) and s.get('ally') and now - s.get('beam', s['start']) >= BEAM_SEC:
                    s['beam'] = now                      # the beam effect is 4 s / 6 s on the client: drawn again while it runs
                    _send(w, n, [('AbilityEffectActivationCommand', dict(selectedAbilityId=g, activatorId=n.id, isPersistent=True,
                                                                         targetIds=[s['ally']]))])
        if 'area_damage' in e and 'per_second' in e['area_damage']:      # Incinerate, Ripper (+80% of the laser per second)
            z = e['area_damage']
            from . import ship as BG
            dmg = z['per_second'] + (BG._fire(n.bot) * z['laser_share'] if z.get('laser_share') else 0)
            for uid, _ in enemies(w, n, now, z['radius']):
                _hit(w, n, uid, dmg, now)
        if 'shield_melt' in e:                           # Scramble, Supercharge Plus: 10% of the maximum shield per second
            n.shield = max(0, n.shield - n.d['shield'] * e['shield_melt'])
            if n.shield <= 0 and e.get('close_at_zero'):
                finish(w, n, item, now, early=True)
                continue
        if 'reload' in e and (_dist_uid(w, n, s.get('target'), now) > RANGE
                              or e['reload']['per_second'] * (now - s['charge']) >= e['reload']['maximum']):
            finish(w, n, item, now, early=True)          # Charge Shot: strikes when full or when the target leaves range


def dots(w, now):
    """Venom's poison (to the hull, +increase each second up to max, total limit) and Particle Beam (8,050 + 6,000 x elapsed s, slow)."""
    keep = []
    for d in w.ab_dots:
        n, t = d['src'], d['target']
        if now >= d['end'] or (d['left'] is not None and d['left'] <= 0) or _pos(w, t, now) is None:
            continue
        keep.append(d)
        if now < d['next']:
            continue
        d['next'] += 1.0
        dmg = d['value'] if d['left'] is None else min(d['value'], d['left'])
        if d['left'] is not None:
            d['left'] -= dmg
        d['value'] = d['value'] + d['increase'] if d['max'] is None else min(d['value'] + d['increase'], d['max'])
        _hit(w, n, t, dmg, now, hull=d.get('hull', False))
        if d.get('slow'):
            _debuff(w, n, t, 'slow', 1.5, d['slow'], d['item'], now)
    w.ab_dots = keep


# ------------------------------------------------------------------------------------------------ decisions
def _skill(b, pvp):
    from . import playstyle as PL
    try:
        return PL.skill(b, 'pvp' if pvp else 'combat')
    except Exception:
        return 0.5


def _hoard(b):
    from . import playstyle as PL
    return 0.5 * b.o('patience') + (0.3 if PL.has(b, 'hoarder') else 0.0)


def situation(w, n, now):
    from . import ship as BG, weapons as WP
    b = n.bot
    d = n.d
    att = [u for u, t in n.attacker.items() if now - t < 4]
    pvp_att = [u for u in att if u == w.hid or (u in w.npcs and w.npcs[u].bot is not None)]
    t, kind, tdist, hard, tratio, tsh = n.target, None, float('inf'), False, 1.0, 0.0
    if t is not None:
        p = _pos(w, t, now)
        if p is not None:
            nx, ny = n.mover.pos(now)
            tdist = math.hypot(p[0] - nx, p[1] - ny)
            m = w.npcs.get(t)
            if t == w.hid:
                kind, (tratio, tsh) = 'player', _ratios(w, t)
            elif m is not None and m.bot is not None:
                kind, tratio, tsh = 'bot', m.hp / float(m.d['hp'] or 1), m.shield / float(m.d['shield'] or 1)
            elif m is not None:
                kind = 'alien'
                ehp = m.d.get('hp', 0) + m.d.get('shield', 0)
                hard = BG.is_boss(m) or ehp / max(1.0, b.value()['dps']) > WP.HARD_SEC
                tratio, tsh = m.hp / float(m.d['hp'] or 1), m.shield / float(m.d['shield'] or 1)
    mv = n.movement
    nx, ny = n.mover.pos(now)
    trip = math.hypot(mv[0] - nx, mv[1] - ny) if mv is not None and n.mover.t1 > now else 0.0
    return dict(hp=n.hp / float(d['hp'] or 1), sh=n.shield / float(d['shield'] or 1),
                ratio=(n.hp + n.shield) / float((d['hp'] + d['shield']) or 1), att=att, pvp_att=pvp_att, target=t, kind=kind,
                tdist=tdist, hard=hard, tratio=tratio, tsh=tsh, fleeing=n.__dict__.get('shelter') is not None, trip=trip,
                fight=bool(att) or (t is not None and tdist <= RANGE * 1.2), worth=kind in ('player', 'bot') or hard)


def _want(w, n, item, sit, now):
    """-> None (not now) or (target, ally, from_ally) for this ability at this moment, by its class."""
    b = n.bot
    cls = CLASS[item]
    r = row(b)
    e = effect_def(r, item)
    a = ABILITIES[item]
    risk = b.o('risk')
    target = sit['target'] if a.get('targeted') and sit['kind'] is not None and sit['tdist'] <= RANGE else None
    if a.get('targeted') and target is None and not e.get('teleport_to_target'):
        return None
    if e.get('last_stand'):
        return (None, None, False) if not b.__dict__.get('ab_armed', EMPTY).get(item) else None
    if 'heal_ally' in cls or 'shield_ally' in cls:
        key = 1 if 'shield_ally' in cls and 'heal_ally' not in cls else 0
        lim = (HEAL_ALLY_AT + 0.1 * b.o('helpfulness')) if key == 0 else SHIELD_AT
        x = _needy(w, n, now, GROUP_RANGE * (0.9 if not e.get('hp_percent') else 1.0), key, lim, fire=key == 1)
        if x is not None and item != PROTECTION:
            return (None, x[1], True)
    if item == PROTECTION:                               # an ally under fire in range and the Citadel can take it
        x = _needy(w, n, now, GROUP_RANGE * 0.9, 0, 0.85, fire=True)
        return (None, x[1], True) if x is not None and sit['ratio'] > 0.45 else None
    if 'heal_self' in cls:
        at = HEAL_SELF_AT + 0.15 * (1 - risk) - 0.15 * _hoard(b)
        if sit['hp'] < at and (sit['att'] or sit['hp'] < at * 0.6):
            return (None, None, False)
        return None
    if 'shield_ally' in cls:
        return (None, None, False) if sit['sh'] < SHIELD_AT and sit['att'] else None
    if 'taunt' in cls:                                   # Draw Fire: aliens or enemy ships on an ally nearby, the Citadel healthy
        x = _needy(w, n, now, e.get('draw_fire', GROUP_RANGE) * 0.9, 0, 0.75, fire=True)
        return (None, x[1], True) if x is not None and sit['ratio'] > 0.5 else None
    if 'defense' in cls:
        if e.get('undying'):
            return (None, None, False) if sit['pvp_att'] and sit['ratio'] < 0.3 + 0.1 * (1 - risk) else None
        if e.get('absorb_hp'):                           # Assimilate: in a hard alien fight
            return (None, None, False) if sit['att'] and not sit['pvp_att'] and sit['hp'] < 0.7 and sit['hard'] else None
        if 'fixed_speed' in e.get('mods', EMPTY) and (sit['fleeing'] or sit['trip'] > 600):
            return None                                  # Fortify immobilizes: not while leaving
        laser = 'laser_taken' in e.get('mods', EMPTY)
        focus = len(sit['pvp_att']) if laser or e.get('mirror') else len(sit['att'])
        at = 0.7 - 0.2 * _hoard(b) + 0.1 * (1 - risk)
        if (focus >= 1 and sit['pvp_att'] and sit['ratio'] < at) or (focus >= 2 and sit['ratio'] < at + 0.15):
            return (None, None, False)
        if 'area' in cls:
            return _area(w, n, item, e, sit, now)
        return None
    if 'area' in cls or 'control' in cls and 'area_slow' in e:
        return _area(w, n, item, e, sit, now)
    if 'control' in cls:                                 # Frozen Claw / Sleight: finish a fleeing or weak enemy, or shake off a chaser
        if sit['kind'] in ('player', 'bot') and (sit['tratio'] < 0.4 or sit['fleeing']):
            return (sit['target'], None, False) if sit['target'] is not None and sit['tdist'] <= (RANGE if not e.get('teleport_to_target')
                                                                                                  else 2500) else None
        return None
    if 'burst' in cls:
        if not sit['worth'] or not sit['fight'] or sit['fleeing']:
            return None
        if 'rocket_cooldown_ms' in e and now >= n.__dict__.get('rocket_ready', 0):
            return None                                  # Rapid Fire when the rocket is cooling down
        if e.get('rage_hp') and sit['hp'] > 0.75:
            return None                                  # Berserk pays more the more HP is gone
        if 'cargo' in e and not b.__dict__.get('ab_charge', EMPTY).get(item):
            return None
        if e.get('shield_melt') and sit['sh'] < 0.5:
            return None
        if item in SA.HECATE_BEAM and sit['kind'] == 'alien':
            return None                                  # Particle Beam hits players (and beacon towers), not aliens (forum 143093)
        return (target, None, False)
    if 'debuff' in cls:
        if not sit['worth'] or sit['fleeing'] or target is None or ('poison' in e and target == w.hid and not hull_ok(w)):
            return None
        if 'speed' in cls and sit['kind'] == 'alien':
            return None
        if ('target_shield_damage' in e or 'target_shield_off' in e) and sit['tsh'] < 0.5:
            return None                                  # shield abilities on a target with shield left
        if 'shield_loss' in e and sit['sh'] > 0.35 and sum(1 for u in allies(w, n, now) if u in w.npcs and w.npcs[u].target == target) < 2:
            return None                                  # Weaken Shields costs 30% of its own shield (ab_lab: a net loss in a duel): when
                                                         # its own shield is low already or two allies fire at the same target
        return (target, None, False)
        return (target, None, False)
    if 'cloak' in cls:                                   # to get away, or to close in on a player or bot from afar (aggressive pilots)
        if sit['fleeing'] and sit['pvp_att']:
            return (None, None, False)
        if sit['kind'] in ('player', 'bot') and 1200 < sit['tdist'] < 4000 and not sit['att'] and b.o('aggression') > 0.55:
            return (None, None, False)
        return None
    if 'speed' in cls:
        if a.get('toggle'):
            return None                                  # handled by _toggle
        far = sit['trip'] > TRAVEL and not sit['fight']
        chase = sit['kind'] in ('player', 'bot') and RANGE < sit['tdist'] < 2500
        return (None, None, False) if far or chase or (sit['fleeing'] and sit['att']) else None
    return None


def _area(w, n, item, e, sit, now):
    """Area abilities: on 2+ enemy ships, or 1 ship in a fight worth it, or AREA_ALIENS aliens (a boss)."""
    if sit['fleeing'] and not e.get('area_slow'):
        return None
    if 'area_damage' in e:
        rad = e['area_damage']['radius']
        center = None
    elif 'area_slow' in e:
        rad = e['area_slow']['radius']
        center = _pos(w, sit['target'], now) if sit['target'] is not None and sit['tdist'] <= RANGE else None
        if center is None:
            return None
    elif 'chain_damage' in e:
        rad, center = e['chain_damage']['range'], _pos(w, sit['target'], now) if sit['tdist'] <= RANGE else None
        if center is None:
            return None
    else:                                                # Triple Barrage
        rad, center = e['triangle_blast']['radius'] * 2 + e['triangle_blast']['distance'], \
            _pos(w, sit['target'], now) if sit['tdist'] <= RANGE else None
        if center is None:
            return None
    found = enemies(w, n, now, rad, center)
    ships = sum(1 for _, k in found if k != 'alien')
    aliens = sum(1 for _, k in found if k == 'alien')
    targeted = ABILITIES[item].get('targeted')
    if ships >= 2 or (ships >= 1 and sit['kind'] in ('player', 'bot')) or aliens >= AREA_ALIENS or (aliens and sit['hard']):
        return (sit['target'] if targeted else None, None, False)
    return None


def _noticed(n, item, now, quick, pvp):
    """The pilot presses after its reaction time since it noticed the moment (skill: pvp or combat); reset when the moment passes."""
    seen = n.__dict__.setdefault('ab_seen', {})
    if item not in seen:
        b = n.bot
        lo, hi = ALLY_REACT if quick else REACT
        seen[item] = now + random.uniform(lo, hi) * (1.5 - _skill(b, pvp))
    return now >= seen[item]


def _toggle(w, n, sit, now):
    """Speed Boost (toggle): on to travel, chase or flee; off in a fight in range (it costs laser damage)."""
    for item in items(n.bot):
        if not ABILITIES[item].get('toggle') or now < ready_at(n.bot, item):
            continue
        is_on = item in on(n)
        want = (sit['trip'] > TRAVEL and not sit['fight']) or (sit['fleeing'] and sit['att']) or \
            (sit['kind'] in ('player', 'bot') and RANGE < sit['tdist'] < 2500)
        if want != is_on and (not want or not sit['fight'] or sit['fleeing']):
            return use(w, n, item, now)
    return False


def think(w, n, now):
    """At the body's think step: one ability at most, when the moment asks for it (see _want), after the pilot's reaction time; pilots
    overlook a ready ability now and then, hold defensive ones too long (patience, the hoarder quirk) or waste one in a fight."""
    b = n.bot
    if not n.alive or not allowed(b) or not kinds(n) or now < n.__dict__.get('ab_decide', 0):
        return False
    n.ab_decide = now + DECIDE_SEC * random.uniform(0.7, 1.3)
    n.__dict__['ab_w'] = w
    sit = situation(w, n, now)
    if _toggle(w, n, sit, now):
        return True
    forget = n.__dict__.setdefault('ab_forget', {})
    seen = n.__dict__.setdefault('ab_seen', {})
    pvp = bool(sit['pvp_att']) or sit['kind'] in ('player', 'bot')
    for item in items(b):
        if ABILITIES[item].get('toggle') or not is_ready(n, item, now) or now < forget.get(item, 0):
            seen.pop(item, None)
            continue
        if forget.get(item) is None or forget[item] < ready_at(b, item):   # newly ready: maybe overlooked for a while
            forget[item] = now + (random.uniform(*FORGET_SEC) if random.random() < FORGET * (1 - _skill(b, False)) else 0)
            if now < forget[item]:
                continue
        x = _want(w, n, item, sit, now)
        if x is None:
            seen.pop(item, None)
            continue
        if not _noticed(n, item, now, x[2], pvp):
            continue
        seen.pop(item, None)
        if use(w, n, item, now, x[0], x[1]):
            return True
    if sit['fight'] and random.random() < WASTE * (1 - _skill(b, pvp)):     # a press at a poor moment (human error)
        own = [i for i in items(b) if is_ready(n, i, now) and not ABILITIES[i].get('targeted') and not ABILITIES[i].get('toggle')
               and not effect_def(row(b), i).get('last_stand') and set(CLASS[i]) & {'defense', 'burst', 'speed'}]
        if own:
            return use(w, n, random.choice(own), now)
    return False


def request(w, n, kind, now, target=None):
    """The tactics' order: use a ready ability of this class now (speed to reach a point, burst at the start of a focus, defence when
    pushed, area on a crowded point, a repair or Protection for the ally `target`) -> True when one was used."""
    if not n.alive or not allowed(n.bot):
        return False
    n.__dict__['ab_w'] = w
    for item in items(n.bot):
        if kind not in CLASS[item] or not is_ready(n, item, now):
            continue
        a = ABILITIES[item]
        if a.get('toggle'):
            if item not in on(n) and use(w, n, item, now):
                return True
            continue
        t = None
        if a.get('targeted'):
            t = target if target is not None and target not in allies(w, n, now) else n.target
            if t is None:
                continue
        ally = target if target is not None and target in allies(w, n, now) else None
        if use(w, n, item, now, t, ally):
            return True
    return False
