"""Ship abilities ("ship_abilities" in the profile; data in data/ship_abilities.json <- the wiki, the client's menu and code).

Client: abilities are in the shortcut menu's "ship_abilities" category (the recorded MenuInitializationCommand: 65 items, all hidden);
the active ship's abilities are made visible and usable, the player can drag them to the bar. On click MenuActionRequest {menuItemId,
actionType 0: timer item, from the client's code; the tests send 1 too}. Timer MenuItemTimerCommand {activatable, timerState
(the client's TimerState: READY 0, ACTIVE 1, COOLING_DOWN 2), menuItemId, maxTime, time}: milliseconds, time is the time left (like MenuItemCooldownGroupTimerCommand in the rocket cooldown).
Visuals from the client's code: skill code 1 Solace, 2 Diminisher, 3 Spectrum, 4 Sentinel, 5 Venom, 6 speed effect. The client's
AbilityEffectActivationCommand handler draws only 1 (and 111, 140, 145); 2-6 with the old text: 0|n|SD|A or D|code|permanent|
activator[|target] (SkillAssemblyHelper -> EventAssemblySkills; Frida trace and live view, 2026-10-23). AbilityStartCommand
(102 Draw Fire, 106 Target Marker, 110 EMP visual, 111 Recon) and AbilityStopCommand. The visual ids of the others were not found.
Rules (wiki): the cooldown starts when the effect ends; a CD booster shortens the cooldown; Elite designs have a duration/cooldown/effect multiplier. Speed
Boost toggles on/off (10 s between two presses). Cloaking ends on attacking, collecting a box, jumping. Ongoing effects end on death.
Cooldowns stay in the profile (map change, re-login); effects bound to a target (Venom, Diminisher, marker) stay on the map.
"""
import json, math, os, random, time

from legacy_protocol import legacy, stm
import settings as SET
import map_links as H

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'ship_abilities.json'), encoding='utf8'))
ABILITIES = D['skills']
SHIPS = D['ships']
READY, ACTIVE, COOLING = 0, 1, 2           # the client's TimerState
VISUAL_HOLD = 1.0                          # the visual of instant abilities is removed after this long


def mod(name, **f):
    f['_'] = name
    return f


def state(p):
    return p.d.setdefault('ship_abilities', {})


def sd_msg(op, effect, persistent, activator, target=None):
    """Old text: 0|n|SD|<A on, D off>|<effect>|<permanent>|<activator>[|<target>] (SkillAssemblyHelper; on the activator if there is no target)."""
    return legacy('0|n|SD|%s|%d|%d|%d' % (op, effect, persistent, activator) + ('|%d' % target if target else ''))


def row(p):
    """The ship's ability row: the worn design's own row if it has one (Centurion's ability designs, the Holo designs'
    cooldown, Hammerclaw Plus's Repair Pod; tools/ship_abilities.py)."""
    s = p.ship()
    return SHIPS.get(s.get('design') or '') or SHIPS.get(s['lootId'], {})


def ship_items(p):
    return row(p).get('skills', [])


def factor(p, item, key):
    return row(p).get('multipliers', {}).get(item, {}).get(key, 1.0)


def special(p, item):
    """The ship's own values for this ability (the client's ship data: sure_sn, cooldown_sec; wiki: effect)."""
    return row(p).get('special', {}).get(item, {})


def effect_def(p, item):
    """The ability's effect, with the ship's own values (Cyborg's Singularity, Hammerclaw's repairs)."""
    e = ABILITIES[item]['effect']
    o = special(p, item).get('effect')
    return dict(e, **o) if o else e


def duration(p, item):
    o = special(p, item)
    return o['duration_sec'] if 'duration_sec' in o else ABILITIES[item]['duration_sec'] * factor(p, item, 'duration')


def cooldown(p, item):
    """Cooldown: the ship's own value or the design multiplier, CD booster (ABILITY_COOLDOWN_TIME, booster.py 'cooldown')."""
    o = special(p, item)
    base = o['cooldown_sec'] if 'cooldown_sec' in o else ABILITIES[item]['cooldown_sec'] * factor(p, item, 'cooldown')
    return base * max(0.0, 1 - p.mods().get('cooldown', 0)) * SET.multiplier('skill_cooldown', 'skill')       # panel: ability cooldown


def is_active(p, item, now=None):
    if item not in ABILITIES:
        return False
    s = state(p).get(item, {})
    if ABILITIES[item].get('toggle'):
        return bool(s.get('on'))
    return (now or time.time()) < s.get('end_time', 0)


def active_items(p, now=None):
    return [i for i in ship_items(p) if is_active(p, i, now)]


def effect(p, key, now=None):
    """One effect of the active abilities (e.g. gorus, gizlen, rocket_cooldown_ms) -> value or None."""
    for i in active_items(p, now):
        e = effect_def(p, i)
        if key in e:
            return e[key]
    return None


def mods(p, now=None):
    """The bonuses of the active abilities (added to player_profile.mods); fixed_speed the smallest (Fortify 0, Travel 450)."""
    out = {}
    for i in active_items(p, now):
        e = effect_def(p, i)
        for k, v in e.get('mods', {}).items():
            out[k] = min(out.get(k, v), v) if k == 'fixed_speed' else out.get(k, 0) + v
        if 'rage_hp' in e:                       # Berserk: each 1% of HP lost gives +1% laser damage
            g = p.d['ship']
            lost = 1 - g.get('hitPoints', 0) / float(g.get('hitMax') or 1)
            out['laser'] = out.get('laser', 0) + max(0.0, lost) * e['rage_hp']
        y = e.get('cargo')
        if y:                                     # Momentum, Stockpile, Volt Discharge: as much as the charge spent on activation
            n = state(p).get(i, {}).get('spent', 0)
            for k, v in y.get('mods', {}).items():
                out[k] = out.get(k, 0) + v * n
            for k, v in y.get('ramp', {}).items():           # Stockpile: each charge is 0.2% more than the one before
                out[k] = out.get(k, 0) + v * n * (n + 1) / 2.0
            if 'max_speed' in y:
                out['max_speed'] = min(out.get('max_speed', y['max_speed']), y['max_speed'])
        if 'reverse' in e:                     # Holo Self Reversal: the negatives of the fitted modules become positives; if no negatives, damage and speed
            import ship_module as GM
            neg = {k: v for k, v in GM.mods(p, p.ship()['lootId'], p.config().get('upgrades', []), p.d['pilot'].get('level')).items()
                   if v < 0}
            for k, v in ({k: -2 * v for k, v in neg.items()} if neg else e['reverse']).items():
                out[k] = out.get(k, 0) + v
    return out


def charge(p, kind, n=1):
    """Charge for the charge-accumulating abilities (Momentum, Stockpile: alien kill 'oldurme'; Volt Discharge: Voltage Link jump
    'zincir'), at most the maximum."""
    for i in ship_items(p):
        y = effect_def(p, i).get('cargo')
        if y and y['source'] == kind and n > 0:
            with p.lock:
                st = state(p).setdefault(i, {})
                st['cargo'] = min(y['maximum'], st.get('cargo', 0) + n)
                p.dirty = True


def range_bonus(p, now=None):
    """Laser range increase of the inactive charge-accumulating abilities (Momentum, Stockpile: +5 per charge)."""
    return sum(effect_def(p, i)['cargo'].get('range', 0) * state(p).get(i, {}).get('cargo', 0) for i in ship_items(p)
               if effect_def(p, i).get('cargo') and not is_active(p, i, now))


def take(p, key):
    """An effect that applies once to the next shot (Quantum Amplifier: Singularity Drive +10%) -> value or 0."""
    for i in ship_items(p):
        if key in effect_def(p, i) and state(p).get(i, {}).get('pending'):
            with p.lock:
                p.dirty = True
                return state(p)[i].pop('pending')
    return 0


def timer_fields(p, item, now=None):
    now = now or time.time()
    s = state(p).get(item, {})
    if is_active(p, item, now):
        if ABILITIES[item].get('toggle'):
            return dict(activatable=now >= s.get('ready', 0), timerState=ACTIVE, maxTime=0, time=0)
        return dict(activatable=False, timerState=ACTIVE, maxTime=s.get('duration_ms', 0), time=max(0, int((s['end_time'] - now) * 1000)))
    if now < s.get('ready', 0):
        return dict(activatable=False, timerState=COOLING, maxTime=s.get('cooldown_ms', 0), time=int((s['ready'] - now) * 1000))
    return dict(activatable=True, timerState=READY, maxTime=0, time=0)


HECATE_BEAM = {k: dict(duration_sec=5, first=8050, increase=6000, slow=0.1, npc=('experiment_beacon',))      # forum 143093 (Plutus Deneyleri)
               for k in ('ability_hecate_particle-beam', 'ability_hecate-plus_particle-beam-plus')}
GROUP_RANGE = 1000          # range of the group abilities (not in the source: adaptation)
PVP_SLOW = 0.4             # forum 160373: Hyperion Anchor slows the player by 40%
ALLY_REPAIR = {'ability_aegis_hp-repair': {'hp_repair': 280000}, 'ability_aegis_shield-repair': {'shield_repair': 125000}}
REPEAT_END = ('ability_retiarus-plus_chsp', 'ability_solaris-plus_incinerate-plus')


def tartarus_set(p, pet):
    """Tartarus full set: the Chimera P.E.T. design and the Phantom design in the same color on all drones (forum 160373)."""
    es = p.d['items']
    pet = pet.design() or ''
    designs = {es.get(str(p.drone_design_id(d, 'design', p.active_config)), '') for d in p.d.get('drones', [])}
    return 'chimera' in pet and len(p.d.get('drones', [])) >= 10 and len(designs) == 1 and 'phantom' in next(iter(designs))


def timer_msg(p, item, now=None):
    f = timer_fields(p, item, now)
    return ('MenuItemTimerCommand', dict(activatable=f['activatable'], timerState=mod('TimerStateModule', timerStateValue=f['timerState']),
                                         menuItemId=item, maxTime=f['maxTime'], time=f['time']))


def line(item, stop=False):
    """The ability's "... activated" / "... deactivated" line (the client's text, ship_abilities.json "text"; empty if none)."""
    key = (ABILITIES[item].get('text') or [None, None])[1 if stop else 0]
    return [stm(key)] if key else []


def menu_status(p, item, st):
    """The ability item in the shortcut menu: only the active ship's abilities are visible; selected while Last Stand is set."""
    owned = item in ship_items(p)
    st.update(visible=owned, available=owned, activatable=owned and timer_fields(p, item)['activatable'])
    if owned:                                  # %DURATION% in the tooltip (Incinerate, Shield Disarray ...): the client fills it only in the shop
        rep = {'_': 'MessageWildcardReplacementModule', 'wildcard': '%DURATION%', 'replacement': '%g' % duration(p, item),
               'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}}
        for k in ('toolTipSlotBar', 'toolTipItemBar'):
            for line_ in (st.get(k) or {}).get('commandList', []):
                line_['wildCardReplacements'] = [dict(rep)]
    if owned and ABILITIES[item].get('effect', {}).get('last_stand'):
        st['selected'] = bool(state(p).get(item, {}).get('built'))
    return st


POD_UID = [980000]                 # ids of the ability objects (they do not collide with the map's entities)


class Engine:
    """Abilities in the world: activation, effects over the duration (repair, poison), end and cooldown notifications."""

    def __init__(self, world, laser_range=700):
        self.w, self.p, self.range = world, world.p, laser_range
        self.pods = {}             # ability -> the id of its object on the map (Repair Pod)
        self.ending = {}           # ability -> end moment (when it ends the visual is removed, the cooldown starts)
        self.charging = {}         # ability -> [target, start] (Charge Shot charge)
        self.beams = {}            # Hecate Particle Beam: ability -> {target, start, last}
        self.shown = {}            # ability -> (unit, attribute, additionalAttribute) of its VisualModifierCommand (removed the same way)
        self.flash = {}            # ability -> moment its brief visual is removed (Last Stand on the lethal hit)
        self.waiting = set()       # those on cooldown: READY when it ends
        self.next_heal = 0.0
        self.flags = dict(cloak=False, vision=1.0, rocket=None)   # frequently asked: computed once per loop (refresh)
        now = time.time()
        for i in ship_items(self.p):
            s = state(self.p).get(i, {})
            if not ABILITIES[i].get('toggle') and now < s.get('end_time', 0):
                self.ending[i] = s['end_time']
            elif now < s.get('ready', 0):
                self.waiting.add(i)
        self.refresh(now)

    def refresh(self, now=None):
        self.flags = dict(cloak=bool(effect(self.p, 'cloak', now)), vision=effect(self.p, 'vision', now) or 1.0,
                          rocket=effect(self.p, 'rocket_cooldown_ms', now))

    # ------------------------------------------------------------ sorgular (world.py)
    def cloaked(self, now=None):
        return self.flags['cloak']

    def view_factor(self, now=None):
        return self.flags['vision']

    def rocket_ms(self, ms, now=None):
        fast = self.flags['rocket']
        return min(ms, fast) if fast else ms

    # ------------------------------------------------------------ activation
    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def stats(self):
        return self.w.stats_msgs() if self.w.stats_msgs else []

    def appearance(self, item, target, on):
        """VisualModifierCommand of an ability (the client's VisualModifierAssemblyHelper): on the ship or, with on=target, on the selected
        target; attr: the linked unit (target, the nearest group member) or a number (Noxious Nebula radius); extra=target: additionalAttribute
        is the target (Charge Shot fires its laser at it when the effect ends)."""
        g, w = ABILITIES[item]['visual'], self.w
        if on:
            if target is None and w.target in w.npcs and w.npcs[w.target].alive:
                target = w.target                    # untargeted abilities aimed at the selection (Enemy Reversal)
            a = g.get('attr', 0)
            if a == 'mate':                          # Shield Link: a group member (player, then group bot), otherwise the ship itself
                now = time.time()
                a = next(iter([o.hid for o in self.mates(now)] + [n.id for n in self.mate_bots(now)]), w.hid)
            elif a == 'target':
                a = target or 0
            self.shown[item] = (target if g.get('on') == 'target' else w.hid, a, str(target or 0) if g.get('extra') == 'target' else '')
        uid, a, extra = self.shown.pop(item, (None, 0, '')) if not on else self.shown[item]
        if uid is None:
            return []
        return [('VisualModifierCommand', dict(userId=uid, modifier=g['appearance'], attribute=int(a), additionalAttribute=extra,
                                               count=0, activated=on))]

    def visual_on(self, item, target):
        g = ABILITIES[item].get('visual', {})
        if 'appearance' in g:                        # ship look (the client's VisualModifier: 8 FORTIFY armor, 9 PROTECT_OWNER ring)
            return self.appearance(item, target, True)
        if 'entity' in g:                         # object placed on the map (Aegis Repair Pod: HEALING_POD 33), stays in place for the duration of the effect
            hx, hy = self.w.hero_pos()
            self.pods[item] = POD_UID[0] = POD_UID[0] + 1
            return [('AssetCreateCommand', dict(designId=0, clanId=0, showBubble=False, userName='', assetId=self.pods[item],
                                                expansionStage=0, modifier=[], type={'_': 'AssetTypeModule', 'typeValue': g['entity']},
                                                detectedByWarnRadar=False, invisible=False, posX=int(hx), posY=int(hy),
                                                clanRelation={'_': 'ClanRelationModule', 'type': 0}, clanTag='',
                                                factionId=self.p.d['pilot'].get('factionId', 0), visibleOnWarnRadar=False))]
        if 'effect' in g:
            persistent = duration(self.p, item) > 0 or bool(ABILITIES[item].get('toggle'))
            if g['effect'] != 1:                    # the client's binary command draws only Solace; 2-6 with the old "SD" text (EventAssemblySkills)
                return [sd_msg('A', g['effect'], int(persistent), self.w.hid, target)]
            return [('AbilityEffectActivationCommand', dict(selectedAbilityId=g['effect'], activatorId=self.w.hid,
                                                            isPersistent=persistent, targetIds=[target or self.w.hid]))]
        if 'launch' in g:
            return [('AbilityStartCommand', dict(selectedAbilityId=g['launch'], activatorId=self.w.hid, noStopCommand=False))]
        return []

    def visual_off(self, item, target):
        g = ABILITIES[item].get('visual', {})
        if 'appearance' in g:
            return self.appearance(item, target, False)
        if 'entity' in g:
            uid = self.pods.pop(item, None)
            return [('AssetRemoveCommand', {'assetType': {'_': 'AssetTypeModule', 'typeValue': g['entity']}, 'uid': uid})] if uid else []
        if 'effect' in g:
            if g['effect'] != 1:
                return [sd_msg('D', g['effect'], 0, self.w.hid, target)]
            return [('AbilityEffectDeActivationCommand', dict(selectedAbilityId=g['effect'], activatorId=self.w.hid,
                                                              targetIds=[target or self.w.hid]))]
        if 'launch' in g:
            return [('AbilityStopCommand', dict(selectedAbilityId=g['launch'], activatorId=self.w.hid, targetIds=[target or self.w.hid]))]
        return []

    def mates(self, now, radius=GROUP_RANGE):
        """On the same map, within radius, the other players in its group (local multi-client)."""
        w = self.w
        if not w.shared:
            return []
        hx, hy = w.hero_pos(now)
        return [o for o in w.shared.members if o is not w and o.running and not o.hero_dead and w.is_group_member(o.hid)
                and math.hypot(*(a - b for a, b in zip(o.hero_pos(now), (hx, hy)))) <= radius]

    def mate_bots(self, now, radius=GROUP_RANGE):
        """On the map, within radius, the ships of the bots in its group (bot/govde; player report 2026-10-31: Solace did not repair them)."""
        w = self.w
        hx, hy = w.hero_pos(now)
        return [n for n in list(w.npcs.values()) if n.bot is not None and n.alive and w.is_group_member(n.bot.uid)
                and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (hx, hy)))) <= radius]

    def heal_bot(self, n, hp=0, shield=0):
        h0, s0 = n.hp, n.shield
        n.hp, n.shield = min(n.d['hp'], n.hp + hp), min(n.d['shield'], n.shield + shield)
        # player report 2026-11-01: the repair was not visible; "+amount" above the bot (world.heal_msgs's HL line, the healing hero)
        msgs = [legacy('0|A|HL|%d|%d|%s|%d|%d' % (self.w.hid, n.id, kind, int(v), int(v) - int(v0)))
                for kind, v0, v in (('HPT', h0, n.hp), ('SHD', s0, n.shield)) if int(v) > int(v0)]
        if self.w.target == n.id:
            msgs.append(self.w.selection(n))
        if msgs:
            self.w.send(msgs)

    def foes(self, now, e=None, radius=None):
        """Enemy players the ability affects: those within the area (radius or area_slow), if the attack rule holds."""
        w = self.w
        if not w.shared:
            return []
        import player_combat as OS_
        r = radius or ((e or {}).get('area_slow') or {}).get('radius') or (self.range if (e or {}).get('target_slow') else 0)
        if not r:
            return []
        hx, hy = w.hero_pos(now)
        return [o for o in w.shared.members if o is not w and not OS_.attack_error(w, o, now)
                and math.hypot(*(a - b for a, b in zip(o.hero_pos(now), (hx, hy)))) <= r]

    def foe_target(self, now):
        """The world of the selected target if it is a player."""
        return self.w.player(self.w.target) if self.w.target is not None else None

    def heal_mates(self, item, key, stop, now):
        """Aegis / Hammerclaw repair also to group members in range (to a friend Aegis HP 280,000, shield 125,000: wiki GEMILER-4)."""
        amount = ALLY_REPAIR.get(item, {}).get(key) or effect_def(self.p, item)[key]
        for o in self.mates(now):
            other_ship = o.p.d['ship']
            if key == 'hp_repair':
                h0 = other_ship.get('hitPoints', 0)
                o.p.set_hull(hp=h0 + amount / stop)
                o.send([o.hp_msg()] + o.heal_msgs(h0))
            else:
                s0 = other_ship.get('shield', 0)
                o.p.set_hull(shield=s0 + amount / stop)
                o.send([('AttributeShieldUpdateCommand', {'shieldNow': int(other_ship['shield']), 'shieldMax': other_ship.get('shieldMax', 0)})])
        for n in self.mate_bots(now):
            self.heal_bot(n, **{('hp' if key == 'hp_repair' else 'shield'): amount / stop})

    def near(self, radius, now, center=None):
        """Live aliens within radius of the ship (or the center point)."""
        hx, hy = center or self.w.hero_pos(now)
        return [n for n in list(self.w.npcs.values()) if n.alive and math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= radius]

    def last_stand(self, now):
        """Paladin Last Stand: on a lethal hit, if ready, HP refills and the cooldown starts -> True."""
        p = self.p
        for i in ship_items(p):
            s = state(p).get(i, {})
            if effect_def(p, i).get('last_stand') and s.get('built') and now >= s.get('ready', 0):
                cd = cooldown(p, i)
                with p.lock:
                    state(p).setdefault(i, {}).update(end_time=now, ready=now + cd, cooldown_ms=int(cd * 1000), built=False)
                    p.dirty = True
                self.waiting.add(i)
                self.flash[i] = now + VISUAL_HOLD * 2
                self.send(self.visual_on(i, None) + [timer_msg(p, i, now), stm('msg_last_stand_stopped')] +
                          [('MenuItemStatusCommand', x) for x in [p.menu_status(i)] if x])
                return True
        return False

    def hold_on(self, now):
        """Tempest Volt Back-up: while active, on a lethal hit HP stays at 1, followed by brief invulnerability; when triggered the ability ends and the
        cooldown starts (client: "invulnerable for 3 seconds. Once the invulnerability is triggered, this skill enters cooldown") -> True."""
        for i in active_items(self.p, now):
            sec = effect_def(self.p, i).get('undying')
            if sec:
                self.w.hero_effects.add('immune_until', sec, 1.0, i, now)
                self.end_now(i, now)
                self.w.log('   Volt Back-up: HP 1, invulnerable for %d s' % sec)
                return True
        return False

    def arm_last_stand(self, item, now):
        """Last Stand is set up once ("Last Stand activated"), HP refills on a lethal hit and the cooldown starts then; pressing again
        turns it off (the client's msg_last_stand_activated/stopped texts). Before, pressing started the cooldown at once and no protection
        remained (live test H42)."""
        p = self.p
        with p.lock:
            st = state(p).setdefault(item, {})
            st['built'] = not st.get('built')
            p.dirty = True
        st_ = p.menu_status(item)
        self.send([stm('msg_last_stand_activated' if st['built'] else 'msg_last_stand_stopped')]
                  + ([('MenuItemStatusCommand', st_)] if st_ else []))
        self.w.log('   Last Stand %s' % ('installed' if st['built'] else 'turned off'))
        return True

    def activate(self, item):
        """MenuActionRequest ability_...: activate if ready -> True."""
        w, p, now = self.w, self.p, time.time()
        a = ABILITIES.get(item)
        if not a or item not in ship_items(p):
            w.log('   ability not on this ship: %s' % item)
            return False
        st = state(p).get(item, {})
        if item in REPEAT_END and is_active(p, item, now):    # forum 160989: Hyper Charge Shot and Incinerate Plus end when pressed again
            self.end_now(item, now)
            w.log('   ability ended early: %s' % item)
            return True
        if w.hero_dead or w.jumping or (not a.get('toggle') and is_active(p, item, now)) or now < st.get('ready', 0):
            self.send([timer_msg(p, item, now)])
            w.log('   ability unavailable: %s (cooling down or active)' % item)
            return False
        e = effect_def(p, item)
        if e.get('last_stand'):
            return self.arm_last_stand(item, now)
        if e.get('cargo') and not st.get('cargo'):     # Momentum, Stockpile, Volt Discharge: cannot be pressed without charge
            self.send([timer_msg(p, item, now)])
            w.log('   no charge for ability: %s' % item)
            return False
        if e.get('phase_out') and (w.gate or H.name(w.map_id).startswith('5-')):     # Phase Out: does not work in a gate or on the pirate map
            self.send([timer_msg(p, item, now)])
            w.log('   ability does not work on this map: %s' % item)
            return False
        target = None
        if a.get('targeted'):
            n = w.npcs.get(w.target)
            hx, hy = w.hero_pos(now)
            if not n or not n.alive or (math.hypot(*(c - h for c, h in zip(n.mover.pos(now), (hx, hy)))) > self.range
                                        and not e.get('teleport_to_target')):         # Sleight: teleports to the selected target with no range limit
                self.send([timer_msg(p, item, now)])
                w.log('   no target in range for ability: %s' % item)
                return False
            target = n
        if a.get('toggle'):                     # Speed Boost: on/off, cooldown between two presses
            with p.lock:
                st = state(p).setdefault(item, {})
                st['on'] = not st.get('on')
                cd = cooldown(p, item)
                st.update(ready=now + cd, cooldown_ms=int(cd * 1000))
                p.dirty = True
            self.refresh(now)
            msgs = (self.visual_on(item, None) if st['on'] else self.visual_off(item, None)) + [timer_msg(p, item, now)] +                 line(item, stop=not st['on'])
            self.waiting.add(item)                # when the cooldown between two presses ends the button can be pressed again
            pet = getattr(w, 'pet', None)
            if st['on'] and p.ship()['lootId'] == 'ship_tartarus' and pet and pet.active and tartarus_set(p, pet):
                pet.select(1)                     # forum 160373 Tartarus full set: on Speed Boost the P.E.T. comes close and switches to passive mode
            self.send(msgs + self.stats())
            w.log('   ability %s: %s' % (a['name'], 'on' if st['on'] else 'off'))
            if st['on']:
                p.ach('ability', type=a.get('achievement'))
            return True
        stop, cd = duration(p, item), cooldown(p, item)
        with p.lock:
            st = state(p).setdefault(item, {})
            st.update(end_time=now + stop, ready=now + stop + cd, duration_ms=int(stop * 1000), cooldown_ms=int(cd * 1000), target=target.id if target else None)
            if e.get('cargo'):
                st['spent'], st['cargo'] = st.get('cargo', 0), 0       # range to its initial value, charges to zero
            if 'next_gsp' in e:
                st['pending'] = e['next_gsp']
            p.dirty = True
        msgs = self.visual_on(item, target.id if target else None) + [timer_msg(p, item, now)] + line(item)
        g = p.d['ship']
        if 'hp_percent' in e:                      # Solace: instantly 35% of the maximum HP
            hp0 = g.get('hitPoints', 0)
            p.set_hull(hp=hp0 + g.get('hitMax', 0) * e['hp_percent'] * factor(p, item, 'effect'))
            msgs += [w.hp_msg()] + w.heal_msgs(hp0)
            for o in self.mates(now):            # forum 160373: Nano-Cluster also repairs group members
                other_ship = o.p.d['ship']
                h0 = other_ship.get('hitPoints', 0)
                o.p.set_hull(hp=h0 + other_ship.get('hitMax', 0) * e['hp_percent'] * factor(p, item, 'effect'))
                o.send([o.hp_msg()] + o.heal_msgs(h0))
            for n in self.mate_bots(now):
                self.heal_bot(n, hp=n.d['hp'] * e['hp_percent'] * factor(p, item, 'effect'))
        if 'target_shield_damage' in e:            # Diminisher Weaken Shields: over the duration the damage to the target's shield increases (world.hit_npc)
            target.effect.add('shield_damage_taken', stop, e['target_shield_damage'], item, now)
        if e.get('teleport_to_target'):                # Keres Sleight: teleport to the target's position (the instant MoveCommand path of Phase Out), then the target slows
            x, y = (int(c) for c in target.mover.pos(now))
            w.hero = type(w.hero)(x, y)
            msgs.append(('MoveCommand', dict(userId=w.hid, x=x, y=y, timeToTarget=0)))
        if 'target_shield_off' in e:             # Disruptor Shield Disarray: half of the shield is disabled over the duration, returns when it ends
            st['shut_off'] = int(target.shield * e['target_shield_off'])
            target.shield -= st['shut_off']
            msgs.append(w.selection(target))
        if 'target_fire_interval' in e:             # DDoL: the target's laser cooldown 3-5 s
            target.effect.add('shot_disrupted', stop, 0, item, now, interval=e['target_fire_interval'])
        if 'poison' in e:                          # Venom: to the hull once a second
            z = e['poison']
            target.effect.add('poison', stop + 1, z['first'], item, now, increase=z['increase'], max_count=z['max_count'], remaining=z['total'],
                            next=now)
        if 'target_damage' in e:
            target.effect.add('damage_bonus', stop, e['target_damage'], item, now)
            tx, ty = target.mover.pos(now)               # Target Marker / Neutralizing Marker: a red ping on the minimap (MarkTargetCommandHandler)
            msgs.append(('MarkTargetCommand', dict(userId=target.id, targetId=target.id, positionX=int(tx), positionY=int(ty))))
        if 'draw_fire' in e:                       # Draw Fire: aliens in range attack
            hx, hy = w.hero_pos(now)
            for n in w.npcs.values():
                nx, ny = n.mover.pos(now)
                if n.alive and n.d['damage'] > 0 and math.hypot(nx - hx, ny - hy) <= e['draw_fire']:
                    n.engaged, n.next_think = True, now
        if e.get('cloak'):                       # Ultimate Cloaking: pursuers let go
            for n in w.npcs.values():
                if n.engaged:
                    w.disengage(n, now)
        if item in HECATE_BEAM and w.target is not None:     # forum 143093: beam 5 s, at players and beacon towers
            self.beams[item] = dict(target=w.target, start=now, last=now)
        if 'reload' in e:                          # Retiarus Charge Shot: charges over the duration (tick), then hits
            self.charging[item] = [target.id, now]
        if 'target_freeze' in e:                   # Goliath-X Frozen Claw
            target.effect.add('frozen', e['target_freeze'], 1.0, item, now)
        if 'target_slow' in e:                 # Pusat Plus Speed Sap
            target.effect.add('slow', stop, e['target_slow'], item, now)
        for o in self.foes(now, e):               # forum 160373: on players too (Keres, Pusat Plus, Hyperion)
            if 'target_slow' in e and o is self.foe_target(now):
                o.hero_effects.add('slow', stop, e['target_slow'], item, now)
                o.send(o.effect_stats_msgs(now))
            if 'area_slow' in e:
                o.hero_effects.add('slow', stop, PVP_SLOW, item, now)
                o.send(o.effect_stats_msgs(now))
        if 'area_slow' in e:                  # Hyperion Gravitational Anchor: the field is at the target's position
            for n in self.near(e['area_slow']['radius'], now, target.mover.pos(now) if target else None):
                n.effect.add('slow', stop, e['area_slow']['ratio'], item, now)
        if 'chain_damage' in e:                   # Tempest Voltage Link: the target and the next nearest, increasing with each jump
            z, hit, cur, dmg = e['chain_damage'], [], target, float(e['chain_damage']['first'])
            while cur and len(hit) < z['target']:
                hit.append(cur.id)
                cur.effect.add('frozen', 1.0, 1.0, item, now)
                w.hit_npc(cur.id, int(dmg), 1)
                dmg *= 1 + z.get('increase', 0)
                cx, cy = cur.mover.pos(now)
                rest = [(math.hypot(n.mover.pos(now)[0] - cx, n.mover.pos(now)[1] - cy), n) for n in w.npcs.values()
                        if n.alive and n.id not in hit]
                rest = [r for r in rest if r[0] <= z['range']]
                cur = min(rest, key=lambda r: r[0])[1] if rest else None
            charge(p, 'chain', len(hit) - 1)    # Volt Discharge: each jump is one charge
        if 'triangle_blast' in e:                  # Zephyr Triple Barrage: three explosions in a triangle behind the target, overlapping areas add up
            u, (hx, hy), (tx, ty) = e['triangle_blast'], w.hero_pos(now), target.mover.pos(now)
            d = math.hypot(tx - hx, ty - hy) or 1.0
            ux, uy, gap = (tx - hx) / d, (ty - hy) / d, u['distance']
            for cx, cy in ((tx + ux * gap, ty + uy * gap), (tx + 2 * ux * gap - uy * gap, ty + 2 * uy * gap + ux * gap),
                           (tx + 2 * ux * gap + uy * gap, ty + 2 * uy * gap - ux * gap)):
                for n in self.near(u['radius'], now, (cx, cy)):
                    w.hit_npc(n.id, int(u['damage']), 1)
        if 'rocket_cooldown_ms' in e and w.rocket_ready > now:
            w.rocket_ready = now                  # Rapid Fire: rocket ready at once
            msgs.append(('MenuItemCooldownGroupTimerCommand', dict(timerState=mod('TimerStateModule', timerStateValue=READY),
                                                                   cooldownType=mod('CooldownTypeModule', typeValue=4), maxTime=0, time=0)))
        if 'mods' in e:
            msgs += self.stats()
        self.ending[item] = now + (stop if stop > 0 else VISUAL_HOLD)
        self.refresh(now)
        self.send(msgs)
        p.ach('ability', type=a.get('achievement'))
        w.log('   ability: %s (%s s, cooldown %d s)%s' % (a['name'], ('%.1f' % stop) if stop else 'instant', cd,
                                                          ' -> %s' % target.d['name'] if target else ''))
        return True

    # ------------------------------------------------------------ duration
    def finish(self, item, now):
        """Effect ended: the visual is removed, your own shield decreases (Diminisher Weaken Shields) or the target's shield returns (Shield Disarray),
        the charged hit (Charge Shot), the cooldown starts."""
        p, w = self.p, self.w
        self.ending.pop(item, None)
        s = state(p).get(item, {})
        e = effect_def(p, item)
        msgs = []
        if 'phase_out' in e and not (w.hero_dead or w.jumping):     # Phase Out: the fading ship appears in a random direction (instant MoveCommand)
            (x, y), a = w.hero_pos(now), random.uniform(0, 2 * math.pi)
            x, y = int(min(max(0, x + e['phase_out'] * math.cos(a)), w.map_w)), int(min(max(0, y + e['phase_out'] * math.sin(a)), w.map_h))
            w.hero = type(w.hero)(x, y)
            msgs.append(('MoveCommand', dict(userId=w.hid, x=x, y=y, timeToTarget=0)))
        msgs += self.visual_off(item, s.get('target'))
        if item in self.charging:
            self.discharge(item, now)
        back = s.pop('shut_off', 0)
        if back and s.get('target') in w.npcs and w.npcs[s['target']].alive:
            n = w.npcs[s['target']]
            n.shield = min(max(n.d.get('shield', 0), n.shield), n.shield + back)
            if w.target == n.id:
                msgs.append(w.selection(n))
        if 'shield_loss' in e and not w.hero_dead:      # Weaken Shields: when the effect ends 30% of YOUR OWN shield goes
            g = p.d['ship']
            p.set_hull(shield=g.get('shield', 0) * (1 - e['shield_loss']))
            msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)}))
        n = w.npcs.get(s.get('target'))
        if n:
            n.effect.remove(source=item)            # effects on the target (weakened shield, poison, marker) are removed early
        if duration(p, item) > 0:                 # instant abilities (Solace) have no end line
            msgs += [timer_msg(p, item, now)] + line(item, stop=True)
        if 'mods' in e:
            msgs += self.stats()
        self.waiting.add(item)
        self.refresh(now)
        self.send(msgs)

    def discharge(self, item, now):
        """Charge Shot: the charged damage to the target (in Plus split among those around the target)."""
        tid, start = self.charging.pop(item)
        d, n = effect_def(self.p, item)['reload'], self.w.npcs.get(tid)
        dmg = min(d['maximum'], d['per_second'] * (now - start))
        if not n or not n.alive or dmg <= 0:
            return
        hit = [n] + ([m for m in self.near(d['split_radius'], now, n.mover.pos(now)) if m is not n] if d.get('split_radius') else [])
        for m in hit:
            self.w.hit_npc(m.id, int(dmg / len(hit)), 1)
        self.w.log('   Charge Shot: %d damage, %d targets' % (dmg, len(hit)))

    def end_now(self, item, now):
        with self.p.lock:
            s = state(self.p).get(item, {})
            if now < s.get('end_time', 0):
                left = s['end_time'] - now
                s['end_time'] = now
                s['ready'] = s.get('ready', now) - left
        self.finish(item, now)

    def reveal(self):
        """Attack, collecting a box, jumping: cloaking ends."""
        now = time.time()
        for i in active_items(self.p, now):
            if effect_def(self.p, i).get('cloak'):
                self.end_now(i, now)
                self.w.log('   cloaking ended')

    def on_death(self):
        now = time.time()
        self.charging.clear()                      # the charged hit does not go off on death
        for i in list(self.ending):
            self.end_now(i, now)
        with self.p.lock:
            for i in ship_items(self.p):
                if effect_def(self.p, i).get('cargo'):
                    state(self.p).setdefault(i, {})['cargo'] = 0      # charges reset on death (wiki)
        for i in ship_items(self.p):
            s = state(self.p).get(i, {})
            if s.get('on'):
                with self.p.lock:
                    s['on'] = False
                self.refresh(now)
                self.send(self.visual_off(i, None) + [timer_msg(self.p, i, now)] + line(i, stop=True))

    def tick(self, now):
        p, w = self.p, self.w
        if now >= self.next_heal:                 # Aegis repairs: an equal share per second
            self.next_heal = now + 1.0
            g = p.d['ship']
            for i in active_items(p, now):
                e = effect_def(p, i)
                stop = max(duration(p, i), 1)
                if 'area_damage' in e and 'per_second' in e['area_damage'] and not w.hero_dead:     # Solaris, Paladin Ripper
                    a = e['area_damage']
                    dmg = a['per_second'] + (w.laser_damage(None)[0] * a['laser_share'] if a.get('laser_share') else 0)
                    for n in self.near(a['radius'], now):
                        w.hit_npc(n.id, int(dmg), 1)
                    for o in self.foes(now, None, a['radius']):     # forum 160373: Ripper/Incinerate on players too
                        import player_combat as OS
                        OS._hit(w, o, now, int(dmg))
                if 'hp_repair' in e and not w.hero_dead:
                    hp0 = g.get('hitPoints', 0)
                    p.set_hull(hp=hp0 + e['hp_repair'] * factor(p, i, 'effect') / stop)
                    self.send([w.hp_msg()] + w.heal_msgs(hp0))
                    self.heal_mates(i, 'hp_repair', stop, now)
                if 'shield_melt' in e and not w.hero_dead:     # Scramble, Supercharge Plus: 10% of the maximum shield per second
                    sh = max(0, g.get('shield', 0) - g.get('shieldMax', 0) * e['shield_melt'])
                    p.set_hull(shield=sh)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
                    if sh <= 0 and e.get('close_at_zero'):
                        self.end_now(i, now)               # Scramble: closes if the shield runs out
                if 'reload' in e and i in self.charging:     # Charge Shot: hits when the target leaves range or when charged
                    tid, start = self.charging[i]
                    n = w.npcs.get(tid)
                    hx, hy = w.hero_pos(now)
                    full = e['reload']['per_second'] * (now - start) >= e['reload']['maximum']
                    if full or not n or not n.alive or math.hypot(*(c - h for c, h in zip(n.mover.pos(now), (hx, hy)))) > self.range:
                        self.end_now(i, now)
                if 'shield_repair' in e and not w.hero_dead:
                    sh0 = g.get('shield', 0)
                    p.set_hull(shield=sh0 + e['shield_repair'] * factor(p, i, 'effect') / stop)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})]
                              + w.heal_msgs(sh0=sh0))
                    self.heal_mates(i, 'shield_repair', stop, now)
        for i, b in list(self.beams.items()):          # Hecate: 8,050 + 6,000 x elapsed s per second (forum 143093)
            h = HECATE_BEAM[i]
            if now - b['start'] > h['duration_sec'] or w.hero_dead:
                del self.beams[i]
                continue
            if now - b['last'] < 1:
                continue
            b['last'] = now
            dmg = int(h['first'] + h['increase'] * int(now - b['start']))
            n = w.npcs.get(b['target'])
            if n and n.alive and n.tip in h['npc']:
                w.hit_npc(n.id, dmg, 1)
                n.effect.add('slow', 1.5, h['slow'], i, now)
            o = w.player(b['target'])
            if o:
                import player_combat as OS
                OS._hit(w, o, now, dmg)
                o.hero_effects.add('slow', 1.5, h['slow'], i, now)
        for i, t in list(self.ending.items()):
            if now >= t:
                self.finish(i, now)
        for i, t in list(self.flash.items()):
            if now >= t:
                del self.flash[i]
                self.send(self.visual_off(i, None))
        for i in list(self.waiting):
            if now >= state(p).get(i, {}).get('ready', 0):
                self.waiting.discard(i)
                if i in ship_items(p):
                    self.send([timer_msg(p, i, now)])
