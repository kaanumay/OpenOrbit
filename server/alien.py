"""Alien abilities (roadmap Stage 4): defined in data/alien_abilities.json with the client's npcId, applied together to the same alien on the map and in the
Galaxy Gate. world.py calls: on a hit (on_hit), every step (tick), on the alien's laser shot
(laser_factor, after_shot, extra_target), on death (on_kill).

Abilities (the data fields are in alien_abilities.json's description):
  summoning, regeneration, spawn on death, invulnerability while their summons live   hooks in world.py (Stage 1); here the enraged call
  repair and rage while their summons live (Battleray)  two or more attackers (player + P.E.T.) within the last sure_sn
  summon at an HP threshold (Invoke XVI: 8 Impulse II)  once
  cloak breaking (Mindfire Behemoth)                  a nearby cloaked player becomes visible
  slowing shot (Barb, Stinger, Saboteur, Behemoth)    a laser that hits: speed cap (sphere, 120) or slowing by a ratio
  multiple targets (Behemoth)                          at critical HP it also fires at the P.E.T.
  rocket (StreuneR) and rocket launcher (Annihilator)  a rocket at the player with a separate cooldown
  singularity (The Stinger, Reflector Mimesis)         damage per second, total limited, within range (no vortex on the Reflector)
  explosion on contact (Kamikaze Mimesis)              fires no laser; explodes when close (bomb damage), leaves without a reward
  vanishing (Emperor Lordakium)                        teleports far away after a certain amount of damage, two fakes appear (explode when hit);
                                                       refills HP and shield while hidden
  kamikaze at an HP threshold (Barracuda)              glows red when HP drops, waits in place, then approaches and explodes
  reversed controls (Boss StreuneR, Boss Saimon)       when the shield runs out / HP drops, the player's movement is reversed for a while
  summons disperse on death (Cubikon)                  the Protegits wander without chasing anyone, then vanish
  sticky bomb (Emperor Kristallon)                     delayed big damage at intervals (single player: divided by the group size)
  speed skill and capsules (Emperor Sibelon)           speeds up as the shield runs out; capsules appear on the map, if the Emperor collects them
                                                       it grows stronger (HP, shield, damage), if a player passes near, the capsule vanishes
  healing (Streuner Specialist, Aider, Medic Mimesis)  repairs the hulls of aliens of the class nearby at intervals (not itself)
  following (Aider Streuner)                           wanders around the Recruit Streuner (guard layout: world.think)
  periodic summoning (Rocketeer, Strokelight Barrage)  summons at intervals while fighting even if not hit (while at most that many live)
  mine dropping (Agatus, Strokelight Barrage)         when HP falls below the threshold, drops an ACM-1 mine at intervals (combat_items.alien_mine)
  death ray (Gygerim Overlord)                        big damage at intervals while the player is far away (from outside the map)
  player's speed (Seeker Rocket, Hooligan)             speed is matched to the player's (+extra; for the Hooligan only at critical HP)
  reversed shot (Streuner Turret)                      a laser that hits reverses the player's controls for a while
  EMP pulse (Obscured Mimesis, Hitac Underboss, Spookfish)  the player's target is reset, cloaking ends, the minimap is jammed
  low HP (low_hp; stray map aliens)                 below 20% it flees to the edge point opposite the player (fires if
                                                       in range), stops there and regenerates, does not retaliate when hit (fandom Low health, Parking)
"""
import json, math, os, random, time

import settings as SET
import map_links as H
import map_layout as ML
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
Y = json.load(open(os.path.join(HERE, 'data', 'alien_abilities.json'), encoding='utf8'))
ABILITIES = {int(k): v for k, v in Y['skills'].items()}
LOW = Y['low_hp']               # fleeing and parking at low HP (fandom Low health, Parking)
CAPSULES = Y['capsule_types']
BUFF_CAPSULE = 45                  # AssetTypeModule.AssetType (client): BUFF_CAPSULE
RING_RADIUS = 300                  # the ring around the Emperor when a capsule is collected (unit; adaptation, to be tuned live)
EMP_NOISE_SEC = 5                   # minimap jamming from the Behemoth's cloak-breaking EMP (seconds; adaptation)
SINGULARITY_TARGET = 21            # VisualModifierCommand.VisualModifier (client): the golden vortex on the singularity's target
MIRRORED_CONTROLS = 27             # VisualModifier: the client reverses the player's movement (reversed controls)
RED_GLOW = 30                      # VisualModifier: red glow (the Barracuda's kamikaze wait)
CAPSULE_BASE = 152000000           # capsule entity ids


def mod(name, **f):
    f['_'] = name
    return f


def of(d):
    """An NPC type's abilities: the npcId's abilities + the type's own "davranis" (the latter takes priority; None turns that ability off: the Kappa
    Annihilator's launcher); note fields ('_') are dropped."""
    out = {k: v for k, v in ABILITIES.get(d.get('npc_id'), {}).items() if not k.startswith('_')}
    out.update(d.get('behavior') or {})
    return {k: v for k, v in out.items() if v is not None}


def asset_create(aid, kind, x, y, name='', design=0):
    """An entity (capsule) on the map: the AssetCreateCommand format in the save (2-1 station turrets)."""
    return ('AssetCreateCommand', dict(designId=design, clanId=0, showBubble=True, userName=name, assetId=aid, expansionStage=0,
                                       modifier=[], type=mod('AssetTypeModule', typeValue=kind), detectedByWarnRadar=True,
                                       invisible=False, posY=int(y), clanRelation=mod('ClanRelationModule', type=0), clanTag='',
                                       factionId=0, posX=int(x), visibleOnWarnRadar=False))


def asset_remove(aid, kind):
    return ('AssetRemoveCommand', {'assetType': mod('AssetTypeModule', typeValue=kind), 'uid': aid})


class Abilities:
    """A world's alien abilities (world.World.alien)."""

    def __init__(self, world):
        import world as world_module                # world imports this module; the values are taken when the world is built
        self.w = world
        self.S, self.CFG, self.Mover, self.ITEMS = world_module.COMBAT, world_module.CFG, world_module.Mover, world_module.ITEMS
        self.capsules = {}          # capsule id -> {x, y, type, owner}
        self.next_capsule = CAPSULE_BASE
        self.hero_dots = []         # singularities on the player: {npc, end_time, remaining, damage_per_sec, next}
        self.mirror_end = 0.0       # end of the reversed controls (overlapping reversed shots extend the time, the visual does not close early)
        self.mirror_gen = 0         # the sequence number of the last reversed shot to extend the time: only its timer closes the visual

    # ------------------------------------------------------------ helpers
    def dist(self, n, now):
        hx, hy = self.w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        return math.hypot(nx - hx, ny - hy)

    def hero_open(self, now, n=None):
        """NPC abilities share laser retaliation rules, with portal/spawn/cloak protection."""
        w = self.w
        if w.hero_dead or w.jumping or now < w.invuln_until:
            return False
        if (w.abilities.cloaked(now) or w.items.cloaked()) and not (n is not None and n.engaged):      # an attacking alien ignores cloaking
            return False
        return not w.in_peace(*w.hero_pos(now)) or bool(n is not None and w.npc_retaliating(n, now))

    def adopt(self, parent, child):
        """What the alien spawned/summoned: does not respawn; counts as the wave's alien at the gate (the wave does not end until it dies)."""
        child.summoned, child.gate = True, parent.gate
        k = self.w.gate
        if k and parent.id in k.npcs:
            k.npcs.add(child.id)

    def attacked(self, n, attacker, now):
        n.attackers[attacker or self.w.hid] = now

    def summoner_bot(self, n):
        """The bot ship that last hit the alien (if the player is not fighting it): its summons attack it (world.npc_summon vuran)."""
        uid = n.ab.get('summoner')
        t = self.w.npcs.get(uid) if uid is not None else None
        return t if t is not None and t.alive and t.bot is not None and not n.engaged else None

    def trigger_attack(self, c, bot, now):
        """A summoned helper attacks at once: the bot if a bot had it summoned, otherwise the player."""
        if bot is not None:
            c.engaged, c.bot_target = False, bot.id
        else:
            c.engaged = True
        c.next_think = now

    def enraged(self, n, now):
        """Rage (Battleray): at least "saldiran" different attackers within the last sure_sn (player and P.E.T. count separately)."""
        o = n.behavior.get('anger')
        if not o:
            return False
        return sum(1 for t in n.attackers.values() if now - t <= o.get('duration_sec', 10)) >= o.get('attacker', 2)

    def extra_summons(self, n, now):
        """What is added to the summon limit while enraged."""
        return n.behavior['anger'].get('extra_summon', 0) if self.enraged(n, now) else 0

    # ------------------------------------------------------------ hit
    def on_hit(self, n, dmg, attacker, now, to_player=True):
        """The alien was hit (after the damage was applied): attacker, summon at an HP threshold, vanishing. to_player: whether effects aimed at the
        player (reversed controls, EMP) are applied (if a bot hit it, only when the player is nearby: bot/ship.hit_npc)."""
        self.attacked(n, attacker, now)
        n.ab.pop('hidden', None)                                  # Emperor Lordakium is found: the refill stops
        for i, c in enumerate(n.behavior.get('summon_at_hp_threshold', [])):
            key = 'esik_%d' % i
            if key not in n.ab and 0 < n.hp <= n.d['hp'] * c['ratio']:
                n.ab[key] = now
                self.summon(n, c['type'], c['count'], now)
        t = n.behavior.get('reverse_controls') if to_player else None
        if t and 'reverse' not in n.ab and n.hp > 0 and (n.shield <= n.d['shield'] * t['shield_ratio'] if 'shield_ratio' in t
                                                      else n.hp <= n.d['hp'] * t['hp_ratio']):
            n.ab['reverse'] = now                                   # once
            self.reverse_controls(n, t['sec'])
        if 'emp_on_shield_down' in n.behavior and to_player:      # Obscured Mimesis: an EMP pulse every time the shield runs out
            if n.shield > 0:
                n.ab.pop('emp_shield', None)
            elif 'emp_shield' not in n.ab and n.hp > 0:
                n.ab['emp_shield'] = now
                self.emp(n, now)
        c = n.behavior.get('critical_emp') if to_player else None
        if c and 'emp_critical' not in n.ab and 0 < n.hp <= n.d['hp'] * c['hp_ratio']:
            n.ab['emp_critical'] = now                             # Spookfish: EMP at critical HP (once)
            self.emp(n, now)
        k = n.behavior.get('disappear')
        if k and dmg > 0 and n.alive and n.hp > 0:
            # only the hull's loss (darkorbitwiki: "after losing ~1.280.000 HP"); shield damage used to count too, a boss with a 6.8 M shield
            # vanished at almost full HP (player report 2026-10-30). HP refilled while hidden does not count
            prev = n.ab.get('last_hp', n.d['hp'])
            n.ab['last_hp'] = n.hp
            n.ab['loss'] = n.ab.get('loss', 0) + max(0, prev - n.hp)
            if n.ab['loss'] >= k['damage']:
                n.ab['loss'] = 0
                self.vanish(n, k, now)

    def visual(self, uid, modifier, on):
        return ('VisualModifierCommand', dict(userId=uid, modifier=modifier, attribute=0, additionalAttribute='', count=0,
                                              activated=on))

    def reverse_controls(self, n, sec):
        """Reversed controls (Boss StreuneR, Boss Saimon, Streuner Turret): the player's movement is reversed for sec seconds (the client reverses it:
        MIRRORED_CONTROLS). If already reversed, the time is extended; the visual closes at the last end."""
        w, now = self.w, time.time()
        if now >= self.mirror_end:
            w.send([self.visual(w.hid, MIRRORED_CONTROLS, True)])
        if now + sec > self.mirror_end:                              # the shot that extends the time: older closing timers become ineffective
            self.mirror_end = now + sec
            self.mirror_gen += 1
            generation = self.mirror_gen

            def off():
                if generation == self.mirror_gen:
                    self.mirror_end = 0.0
                    w.send([self.visual(w.hid, MIRRORED_CONTROLS, False)])
            w.later(sec, off)
        w.log('   %s reversed the controls (%d s)' % (n.d['name'], sec))

    def summon(self, n, kind, count, now):
        w = self.w
        x, y = n.mover.pos(now)
        for i in range(count):
            a = 2 * math.pi * i / max(1, count)
            c = w.spawn_npc_at(kind, x + math.cos(a) * 300, y + math.sin(a) * 300)
            self.adopt(n, c)
            self.trigger_attack(c, self.summoner_bot(n), now)
            n.children.add(c.id)
        w.log('   %s summoned %d %s (HP %%%d)' % (n.d['name'], count, self.CFG['types'][kind]['name'], 100 * n.hp // max(1, n.d['hp'])))

    def far_spot(self, near, far):
        """A point at least "far" from the player (otherwise the farthest attempt); near: searches around (x, y) (None: anywhere on the map)."""
        w = self.w
        hx, hy = w.hero_pos()
        best, bid = None, -1
        for _ in range(40):
            if near:
                a, r = random.uniform(0, 2 * math.pi), random.uniform(far * 0.3, far)
                x, y = near[0] + math.cos(a) * r, near[1] + math.sin(a) * r
            else:
                x, y = random.uniform(600, w.map_w - 600), random.uniform(600, w.map_h - 600)
            x, y = min(max(x, 500), w.map_w - 500), min(max(y, 500), w.map_h - 500)
            d = math.hypot(x - hx, y - hy)
            if d >= far:
                return int(x), int(y)
            if d > bid:
                best, bid = (int(x), int(y)), d
        return best

    def vanish(self, n, k, now):
        """Emperor Lordakium: teleports far away, its two fakes appear in other places; the player's choice is left."""
        w = self.w
        # the real one and the fakes within the player's view, in different directions (wiki: "reappears together with two fake Lordakiums"; they used to go
        # out of view, 2,500 units away, not visible on the map, could not be found: player report 2026-10-30)
        hx, hy = w.hero_pos(now)
        spots = self.ring_spots(hx, hy, k.get('distance', 1500), k.get('fake', 2) + 1)
        x, y = spots.pop(0)
        n.mover = self.Mover(x, y)
        n.engaged = False
        n.next_think = now + 2
        n.ab['hidden'] = now
        msgs = []
        if w.target == n.id:
            w.target, w.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if n.id in w.visible:
            w.visible.discard(n.id)
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        w.send(msgs)
        fake = self.fake_type(n, k)
        for fx, fy in spots:
            f = w.spawn_npc_at(fake, fx, fy)
            f.summoned, f.gate = True, n.gate
            f.ab['lifetime'] = now + k.get('fake_lifetime_sec', 90)
        w.log('   %s vanished: (%d,%d), %d fakes' % (n.d['name'], x, y, k.get('fake', 2)))

    def ring_spots(self, hx, hy, r, count):
        """count points around the player at distance r, at equal angles (in random order); within the map."""
        w, a0 = self.w, random.uniform(0, 2 * math.pi)
        out = [(int(min(max(hx + math.cos(a0 + 2 * math.pi * i / count) * r, 500), w.map_w - 500)),
                int(min(max(hy + math.sin(a0 + 2 * math.pi * i / count) * r, 500), w.map_h - 500))) for i in range(count)]
        random.shuffle(out)
        return out

    def fake_type(self, n, k):
        """The fake Emperor type (looks the same as the real one; 1 HP, does not fire, no reward, explodes when hit)."""
        key = 'sahte_' + n.tip
        if key not in self.CFG['types']:
            self.CFG['types'][key] = dict(name=n.d['name'], model=n.model, hp=1, shield=0, damage=0, speed=n.d['speed'], aggressive=False,
                                      reward=dict(ep=0, honor=0, credits=0, uridium=0), cargo={}, uncounted=True,
                                      behavior={'explode_on_death': {'damage': k.get('explosion', 60000),
                                                                 'radius': k.get('explosion_radius', 500)}})
        return key

    # ------------------------------------------------------------ the alien's shot
    def laser_factor(self, n, now):
        """The alien's laser damage multiplier: rage (Battleray: RSB-75), Emperor Sibelon's damage capsules."""
        f = 1 + n.ab.get('damage_bonus', 0)
        if self.enraged(n, now):
            f *= n.behavior['anger'].get('damage_multiplier', 1)
        return f

    def laser_color(self, n, now):
        """The alien's laser visual (AttackLaserRunCommand.laserColor): the enraged Battleray fires RSB-75 (wiki: "uses RSB-75 instead of
        UCB-100"; ofke.lazer_renk, RSB-75 = 6 for instance). Without the visual the rage stayed only in the damage and went unnoticed in game (report
        2026-10-28)"""
        if self.enraged(n, now):
            return n.behavior['anger'].get('laser_color', 0)
        return 0

    def after_shot(self, n, now, hit):
        """The alien's laser hit the player: reversed shot (Streuner Turret), slowing shot."""
        t = n.behavior.get('reverse_shot')
        if t and hit and not self.w.hero_dead and now >= n.ab.get('reverse_next', 0):
            n.ab['reverse_next'] = now + t['cooldown_sec']
            self.reverse_controls(n, t['sec'])
        s = n.behavior.get('slowing_shots')
        if not s or not hit or self.w.hero_dead or not SET.get('slowing_shots'):          # panel: can be turned off
            return
        if s.get('range') and self.dist(n, now) > s['range']:
            return
        w = self.w
        src = 'slow_%s' % n.tip
        if s.get('visual'):                       # Saboteur: the slowing orb chases the ship (MapEventsAssemblyHelper.AssembleSabShot)
            w.send([legacy('0|n|%s|%d|%d' % (s['visual'], n.id, w.hid))])
        if 'speed' in s:
            w.hero_effects.remove('speed_limit', source=src)          # renews, does not stack
            w.hero_effect('speed_limit', s['sec'], s['speed'], source=src)
        else:
            w.hero_effects.remove('slow', source=src)
            w.hero_effect('slow', s['sec'], s['ratio'], source=src)

    def extra_target(self, n, now):
        """Multiple targets (Mindfire Behemoth): at critical HP it also fires at the P.E.T."""
        c = n.behavior.get('multi_target')
        return bool(c) and n.hp <= n.d['hp'] * c.get('hp_ratio', 0.25)

    # ------------------------------------------------------------ every step
    def tick(self, now):
        w = self.w
        for n in list(w.npcs.values()):
            if not n.alive or not n.behavior and not n.ab or not w.owner(n, now):     # on a shared map the alien's owner processes it
                continue
            if 'lifetime' in n.ab and now >= n.ab['lifetime']:
                self.expire(n)
                continue
            d = n.behavior
            if 'repair_while_summons_alive' in d:
                self.summon_repair(n, now)
            if 'cloak_breaker' in d:
                self.uncloak(n, now)
            if 'rocket' in d:
                self.rocket(n, now)
            if 'singularity' in d:
                self.singularity(n, now)
            if 'sticky_bomb' in d:
                self.bomb(n, now)
            if 'explode_on_contact' in d:
                self.kamikaze(n, now)
            if 'kamikaze_threshold' in d:
                self.threshold_kamikaze(n, now)
            if 'speed_skill' in d:
                self.speed_skill(n, now)
            if 'disappear' in d and n.ab.get('hidden'):
                self.hidden_regen(n, now)
            if 'improvement' in d:
                self.heal(n, now)
            if 'follow' in d:
                self.follow(n, now)
            if 'periodic_summon' in d:
                self.periodic_summon(n, now)
            if 'drop_mine' in d:
                self.drop_mines(n, now)
            if 'death_beam' in d:
                self.death_ray(n, now)
            if 'periodic_emp' in d:
                self.periodic_emp(n, now)
            if 'player_speed' in d:
                self.match_speed(n, now)
            if n.bot_target is not None and not n.engaged:
                self.bot_abilities(n, now)
        self.dot_tick(now)          # once per tick (when it stayed at the end of bota_yetenekler the Singularity damage and capsules were never processed)
        self.capsule_tick(now)

    # ------------------------------------------------------------ against a bot (while the alien fights a bot)
    def bot_abilities(self, n, now):
        """While the alien fights a bot ship, the attack abilities against the bot: rocket, sticky bomb, explosion on contact, kamikaze, singularity,
        death ray, periodic summoning (helpers to the bot). Player-specific effects (EMP, cloak breaking, slowing, mines around the player,
        speed matching) are not applied to the bot. Previously the abilities worked only while fighting the player (user report 2026-10-30)."""
        from bot import ship as BG
        w, d = self.w, n.behavior
        t = w.npcs.get(n.bot_target)
        if t is None or not t.alive or t.bot is None or n.effect.frozen(now):
            return
        nx, ny = n.mover.pos(now)
        tx, ty = t.mover.pos(now)
        aliens = math.hypot(tx - nx, ty - ny)

        def hit(dmg, delay=0.0):
            uid, hid = n.id, t.id

            def at():
                h = w.npcs.get(hid)
                if h is not None and h.alive and h.bot is not None:
                    BG.bot_damage(w, h, int(dmg), uid, time.time(), npc=w.npcs.get(uid) or n)
            w.later(delay, at) if delay else at()
        r = d.get('rocket')
        if r and r.get('damage') and now >= n.ab.get('rocket', 0) and aliens <= w.npc_range(n):     # effect-only rockets: player only
            n.ab['rocket'] = now + r.get('cooldown_sec', 8)
            if random.random() < self.S['rocket_hit_chance']:
                from legacy_protocol import legacy
                BG._broadcast(w, [legacy('0|v|%d|%d|H|%d|0|0' % (n.id, t.id, r.get('type', 1)))], n.id, t.id)
                hit(r['damage'] * random.uniform(0.85, 1.0), self.S['rocket_flight_sec'])
        b = d.get('sticky_bomb')
        if b and aliens <= w.npc_range(n) * 2:
            if 'bomb' not in n.ab:
                n.ab['bomb'] = now + b['interval_sec']
            elif now >= n.ab['bomb']:
                n.ab['bomb'] = now + b['interval_sec']
                dmg = random.randint(*b['damage']) if isinstance(b['damage'], list) else b['damage']
                hit(dmg / max(1, b.get('group', 1)), b.get('delay_sec', 2))
        k = d.get('explode_on_contact')
        if k and aliens <= k['radius']:
            dmg = k['damage'] * ((1 - (1 - k['at_edge']) * min(1.0, aliens / k['radius'])) if 'at_edge' in k else 1)
            hit(dmg)
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(boom + w.remove_npc(n))
            return
        k = d.get('kamikaze_threshold')
        if k and n.hp <= n.d['hp'] * k['ratio'] and n.hp > 0 and aliens <= k['radius']:
            hit(n.hp * k['damage_hp_ratio'])
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(boom + w.remove_npc(n))
            if not n.gate and not n.summoned:
                w.schedule(random.uniform(*w.respawn_range(n)), 'npc', n.tip)
            return
        s = d.get('singularity')
        if s and now >= n.ab.get('singularity', 0) and aliens <= s['range'] * SET.multiplier('npc_range'):
            n.ab['singularity'] = now + s['cooldown_sec']
            for i in range(int(min(s['duration_sec'], s['maximum'] / max(1, s['damage_per_sec'])))):
                hit(s['damage_per_sec'], i + 1.0)
        o = d.get('death_beam')
        if o and now >= n.ab.get('beam', 0) and aliens > o['distance']:
            n.ab['beam'] = now + o['interval_sec']
            hit(o['damage'] * random.uniform(0.8, 1.2))
        p = d.get('periodic_summon')
        if p and now >= n.ab.get('periodic', 0):
            n.ab['periodic'] = now + p['cooldown_sec']
            n.ab['summoner'] = t.id
            n.children = {c for c in n.children if c in w.npcs and w.npcs[c].alive}
            for e in p['summons']:
                room = e['max_count'] - sum(1 for c in n.children if w.npcs[c].tip == e['type'])
                if room > 0:
                    self.summon(n, e['type'], min(e['count'], room), now)

    def expire(self, n):
        """One whose life ran out (fake Emperor): leaves silently."""
        w = self.w
        n.alive = False
        w.npcs.pop(n.id, None)
        msgs = []
        if w.target == n.id:
            w.target, w.attacking = None, False
            msgs.append(('ShipDeselectionCommand', {}))
        if n.id in w.visible:
            w.visible.discard(n.id)
            msgs.append(('ShipRemoveCommand', {'userId': n.id}))
        w.send(msgs)

    def summon_repair(self, n, now):
        """Repair per second while their summons live (Battleray: 600, 30,000 when enraged)."""
        if now < n.ab.get('repair', 0):
            return
        n.ab['repair'] = now + 1.0
        n.children = {c for c in n.children if c in self.w.npcs and self.w.npcs[c].alive}
        if not n.children or n.hp >= n.d['hp']:
            return
        r = n.behavior['repair_while_summons_alive']
        amount = n.behavior['anger'].get('repair_hp_per_sec', r['hp_sec']) if self.enraged(n, now) else r['hp_sec']
        n.hp = min(n.d['hp'], n.hp + amount)
        if self.w.target == n.id:
            self.w.send([self.w.selection(n)])

    def uncloak(self, n, now):
        w = self.w
        if not (w.abilities.cloaked(now) or w.items.cloaked()) or w.hero_dead:
            return
        if self.dist(n, now) <= n.behavior['cloak_breaker'].get('range', 1500):
            w.abilities.reveal()
            w.items.reveal()
            # EMP pulse (Ö1): the client's "EMP Malus Bolt" jams the minimap (MapEventsAssemblyHelper.AssembleEmpMalusBolt,
            # 0|n|EMAL|<seconds>; the duration is an adaptation)
            from legacy_protocol import legacy
            w.send([legacy('0|n|EMAL|%d' % EMP_NOISE_SEC)])
            w.log('   %s gizlenmeyi bozdu' % n.d['name'])

    def rocket(self, n, now):
        """The alien's rocket or rocket launcher salvo: with its own cooldown, within firing range."""
        w, r = self.w, n.behavior['rocket']
        if (not n.engaged or now < n.ab.get('rocket', 0) or n.effect.frozen(now) or not self.hero_open(now, n)
                or self.dist(n, now) > w.npc_range(n)):
            return
        n.ab['rocket'] = now + r.get('cooldown_sec', 8)
        m = w.p.mods()
        hit = random.random() < self.S['rocket_hit_chance'] * (1 - m.get('evasion', 0)) * (1 - n.effect.accuracy_loss(now))
        flight = self.S['rocket_flight_sec']
        special = self.ITEMS['rockets'][random.choice(r['rockets'])] if r.get('rockets') else None    # Hexor: DCR-250 / R-IC3
        if special:
            r = dict(r, type=special['uid'], damage=special.get('damage', 0))
        if r.get('launcher'):
            import combat_items as CIT
            kind = CIT.LAUNCHER_AMMO.get('ammunition_rocketlauncher_eco-10', {}).get('type', 1)
            cnt = r.get('count', 5)
            flight = CIT.salvo_time(self.dist(n, now), cnt)        # local curve salvo: the damage when the last rocket arrives
            w.send([CIT.salvo(n.id, w.hid, hit, cnt, kind)])
        else:
            from legacy_protocol import legacy
            w.send([legacy('0|v|%d|%d|%s|%d|0|0' % (n.id, w.hid, 'H' if hit else 'M', r.get('type', 1)))])
        dmg = int(r['damage'] * random.uniform(0.85, 1.0))
        uid = n.id

        def land():
            if w.hero_dead or w.jumping:
                return
            if not hit:
                w.send([('AttackMissedCommand', dict(attackType=mod('AttackTypeModule', attackTypeValue=0), targetUserId=w.hid,
                                                     skillColorId=0))])
                return
            if dmg > 0:
                w.send(w.hurt_hero(dmg, w.npcs.get(uid) or n, atype=0))
            if special:                                   # the special rocket's effect on the player (slow 30% 5 s / frozen 2 s)
                for kind, (val, sec) in special.get('effect', {}).items():
                    w.hero_effect(kind, sec, val, source='rocket_%s' % n.tip)
        w.later(flight, land)

    def singularity(self, n, now):
        """The Stinger's singularity starts: damage per second on the player (dot_tick)."""
        t = n.behavior['singularity']
        rng = t['range'] * SET.multiplier('npc_range')       # panel: alien firing range
        if not n.engaged or now < n.ab.get('singularity', 0) or not self.hero_open(now, n) or self.dist(n, now) > rng:
            return
        n.ab['singularity'] = now + t['cooldown_sec']
        visual = t.get('visual', True)                     # the Reflector Mimesis's radiation: no vortex
        if visual and not any(d_.get('visual') for d_ in self.hero_dots):
            self.w.send([self.singularity_visual(True)])    # live test H30: there was damage, no visual
        self.hero_dots.append(dict(npc=n.id, end_time=now + t['duration_sec'], remaining=t['maximum'], damage_per_sec=t['damage_per_sec'], next=now + 1.0,
                                   range=rng, visual=visual, emp=bool(t.get('emp_clears'))))
        self.w.log('   %s singularity started' % n.d['name'])

    def kamikaze(self, n, now):
        """Kamikaze Mimesis: explodes when it gets within yaricap of the player (bomb damage) and leaves without a reward."""
        t, w = n.behavior['explode_on_contact'], self.w
        if t.get('cloak_breaks_lock') and n.engaged and (w.abilities.cloaked(now) or w.items.cloaked()):
            n.engaged = False                                # forum 127094: cloaking (like EMP) breaks the Kamikaze's lock
            return
        if not n.engaged or not self.hero_open(now, n) or self.dist(n, now) > t['radius']:
            return
        dmg = t['damage']
        if 'at_edge' in t:         # Seeker Rocket: damage by the distance at the moment of explosion (full on contact, "kenarda" of it at the edge of yaricap)
            dmg = int(dmg * (1 - (1 - t['at_edge']) * min(1.0, self.dist(n, now) / t['radius'])))
        boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
        w.send(w.hurt_hero(dmg, n, atype=0, inverse_absorb=bool(t.get('inverse_absorb'))) + boom + w.remove_npc(n))
        w.log('   %s exploded: %d damage' % (n.d['name'], dmg))

    def threshold_kamikaze(self, n, now):
        """Barracuda: when HP drops to ratio it glows red and stays in place for wait_sec (frozen: does not fire), then approaches the player;
        if within radius it explodes with area damage by its remaining HP (no reward; respawns if on the map), if it cannot
        reach within approach_sec it glows again (fandom: Barracuda, Kamikaze)."""
        t, w = n.behavior['kamikaze_threshold'], self.w
        until = n.ab.get('kamikaze')
        if until is None:
            if n.hp <= 0 or n.hp > n.d['hp'] * t['ratio']:
                return
            self.glow(n, t, now)
            return
        if now < until:
            if now >= n.ab.get('glint', 0):          # the glow is momentary (client ShipGlowEffect3D): while waiting it blinks once a second
                n.ab['glint'] = now + 1.0
                w.send([self.visual(n.id, RED_GLOW, True)])
            return
        if 'approach' not in n.ab:
            n.ab['approach'] = now + t['approach_sec']
            n.engaged, n.next_think = True, now
            w.send([self.visual(n.id, RED_GLOW, False)])
        if self.hero_open(now, n) and self.dist(n, now) <= t['radius']:
            dmg = int(n.hp * t['damage_hp_ratio'])
            boom = [('ShipDestroyedCommand', dict(destroyedUserId=n.id, explosionTypeId=0))] if n.id in w.visible else []
            w.send(w.hurt_hero(dmg, n, atype=0) + boom + w.remove_npc(n))
            if not n.gate and not n.summoned:
                w.schedule(random.uniform(*w.respawn_range(n)), 'npc', n.tip)
            w.log('   %s blew itself up: %d damage' % (n.d['name'], dmg))
        elif now >= n.ab['approach']:
            self.glow(n, t, now)                            # could not reach: glows again and waits

    def glow(self, n, t, now):
        n.ab['kamikaze'], n.ab['glint'] = now + t['wait_sec'], now + 1.0
        n.ab.pop('approach', None)
        self.w.npc_effect(n, 'frozen', t['wait_sec'], source='kamikaze')
        self.w.send([self.visual(n.id, RED_GLOW, True)])
        self.w.log('   %s preparing to kamikaze (HP %%%d)' % (n.d['name'], 100 * n.hp // max(1, n.d['hp'])))

    def singularity_visual(self, on):
        return self.visual(self.w.hid, SINGULARITY_TARGET, on)

    def dot_tick(self, now):
        w = self.w
        keep = []
        for dot in self.hero_dots:
            n = w.npcs.get(dot['npc'])
            if not n or not n.alive or now >= dot['end_time'] or dot['remaining'] <= 0 or w.hero_dead:
                continue
            keep.append(dot)
            if now < dot['next']:
                continue
            dot['next'] += 1.0
            if self.dist(n, now) > dot['range'] or not self.hero_open(now, n):
                continue
            dmg = min(dot['damage_per_sec'], dot['remaining'])
            dot['remaining'] -= dmg
            w.send(w.hurt_hero(dmg, n))
        if any(d_.get('visual') for d_ in self.hero_dots) and not any(d_.get('visual') for d_ in keep):
            w.send([self.singularity_visual(False)])
        self.hero_dots = keep

    def bomb(self, n, now):
        """Emperor Kristallon's sticky bomb: at intervals, delayed; single player: the damage is divided by the group size."""
        b, w = n.behavior['sticky_bomb'], self.w
        if not n.engaged or not self.hero_open(now, n) or self.dist(n, now) > w.npc_range(n) * 2:
            return
        if 'bomb' not in n.ab:
            n.ab['bomb'] = now + b['interval_sec']           # the first bomb aralik_sn after the battle starts
            return
        if now < n.ab['bomb']:
            return
        n.ab['bomb'] = now + b['interval_sec']
        dmg = random.randint(*b['damage']) if isinstance(b['damage'], list) else b['damage']      # Marker Mimesis: 100-300 bin
        dmg = int(dmg / max(1, b.get('group', 1)))
        from legacy_protocol import legacy
        w.send([legacy('0|v|%d|%d|H|1|0|0' % (n.id, w.hid))])
        uid = n.id

        def boom():
            if not w.hero_dead and not w.jumping:
                w.send(w.hurt_hero(dmg, w.npcs.get(uid) or n, atype=0))
        w.later(b.get('delay_sec', 2), boom)
        w.log('   %s sticky bomb (%d damage)' % (n.d['name'], dmg))

    def hidden_regen(self, n, now):
        """A hidden Emperor Lordakium refills HP and shield per second."""
        if now < n.ab.get('reload', 0):
            return
        n.ab['reload'] = now + 1.0
        k = n.behavior['disappear']
        n.hp = min(n.d['hp'], n.hp + k.get('hp_sec', 0))
        n.shield = min(n.d['shield'], n.shield + k.get('shield_per_sec', 0))

    # ------------------------------------------------------------ healing, following, periodic summoning, EMP, the player's speed
    def heal(self, n, now):
        """Healing {hp_sec | hp_ratio, cooldown_sec, range, target [name parts; otherwise every alien]}: every cooldown_sec it repairs the hulls of
        aliens named in target within range; it does not repair itself (Streuner Specialist: 6,000 per 3 s; the other Specialist repairs it)."""
        h = n.behavior['improvement']
        if now < n.ab.get('improvement', 0):
            return
        n.ab['improvement'] = now + h['cooldown_sec']
        w = self.w
        nx, ny = n.mover.pos(now)
        for m in list(w.npcs.values()):
            if m is n or not m.alive or m.hp <= 0 or m.hp >= m.d['hp'] or (h.get('target')
                                                                           and not any(s in m.d['name'].lower() for s in h['target'])):
                continue
            mx, my = m.mover.pos(now)
            if math.hypot(mx - nx, my - ny) > h['range']:
                continue
            amount = int(min(m.d['hp'] - m.hp, h['hp_sec'] if 'hp_sec' in h else m.d['hp'] * h['hp_ratio']))
            m.hp += amount
            msgs = [legacy('0|A|HL|%d|%d|HPT|%d|%d' % (n.id, m.id, int(m.hp), amount))] if m.id in w.visible else []
            if w.target == m.id:
                msgs.append(w.selection(m))
            w.send(msgs)

    def follow(self, n, now):
        """Following {target (name part), radius}: if it has no guard, wanders around the nearest alien named target (Aider Streuner
        follows the Recruit Streuner); the wandering is world.think's guard layout (NPC.guard)."""
        if now < n.ab.get('follow', 0) or self.w.ward_of(n):
            return
        n.ab['follow'] = now + 5.0
        f, nx, ny = n.behavior['follow'], *n.mover.pos(now)
        near = [(math.hypot(m.mover.pos(now)[0] - nx, m.mover.pos(now)[1] - ny), m.id) for m in self.w.npcs.values()
                if m is not n and m.alive and f['target'] in m.d['name'].lower()]
        if near:
            n.guard = (min(near)[1], {'radius': f['radius']})

    def periodic_summon(self, n, now):
        """Periodic summoning {cooldown_sec, summons [{type, count, max_count}]}: while fighting, even if not hit, it summons every cooldown_sec; each type
        is not summoned again while max_count of it live (Rocketeer -> Seeker Rocket; Strokelight Barrage -> Abide I and Steadfast III)."""
        p, w = n.behavior['periodic_summon'], self.w
        if not n.engaged or n.effect.frozen(now) or now < n.ab.get('periodic', 0) or not self.hero_open(now, n):
            return
        n.ab['periodic'] = now + p['cooldown_sec']
        n.children = {c for c in n.children if c in w.npcs and w.npcs[c].alive}
        for e in p['summons']:
            room = e['max_count'] - sum(1 for c in n.children if w.npcs[c].tip == e['type'])
            if room > 0:
                self.summon(n, e['type'], min(e['count'], room), now)

    def drop_mines(self, n, now):
        """Mine dropping {mine, hp_ratio, cooldown_sec, max_count, target, radius}: while fighting with HP below hp_ratio it drops a
        mine every cooldown_sec (at the alien's position; target: around the player, at distance radius [min, max]); it does not drop a new one while
        the same alien's max_count mines live. The mine is combat_items.alien_mine's alien mine (when placed it explodes if the player is nearby)."""
        m, w = n.behavior['drop_mine'], self.w
        if (w.items is None or not n.engaged or n.effect.frozen(now) or n.hp > n.d['hp'] * m['hp_ratio']
                or now < n.ab.get('mine', 0) or not self.hero_open(now, n)):
            return
        n.ab['mine'] = now + m['cooldown_sec']
        if sum(1 for k in w.items.mines.values() if k['owner'] == n.id) >= m['max_count']:
            return
        x, y = w.hero_pos(now) if m.get('target') else n.mover.pos(now)
        if m.get('target'):
            a, r = random.uniform(0, 2 * math.pi), random.uniform(*m['radius'])
            x, y = x + math.cos(a) * r, y + math.sin(a) * r
        w.items.alien_mine(m['mine'], min(max(0, x), w.map_w), min(max(0, y), w.map_h), n.id, now)
        w.log('   %s dropped a mine (%s)' % (n.d['name'], m['mine']))

    def death_ray(self, n, now):
        """Death ray {damage, interval_sec, distance} (Gygerim Overlord): while fighting with the player farther than distance (the rays come from outside the map),
        every interval_sec an average damage (80-120%); not tied to range, no ray falls on a nearby player."""
        r, w = n.behavior['death_beam'], self.w
        if (not n.engaged or n.effect.frozen(now) or now < n.ab.get('beam', 0) or self.dist(n, now) <= r['distance']
                or not self.hero_open(now, n)):
            return
        n.ab['beam'] = now + r['interval_sec']
        dmg = int(r['damage'] * random.uniform(0.8, 1.2))
        w.send(w.hurt_hero(dmg, n, atype=0))
        w.log('   %s death ray (%d damage)' % (n.d['name'], dmg))

    def periodic_emp(self, n, now):
        """Periodic EMP {cooldown_sec, range}: while fighting, if in range, every cooldown_sec (the Hitac Underboss's EMP Impulse)."""
        e = n.behavior['periodic_emp']
        if not n.engaged or n.effect.frozen(now) or now < n.ab.get('emp_next', 0) or self.dist(n, now) > e['range'] \
                or not self.hero_open(now, n):
            return
        n.ab['emp_next'] = now + e['cooldown_sec']
        self.emp(n, now)

    def emp(self, n, now):
        """The alien's EMP pulse (Obscured Mimesis, Hitac Underboss, Spookfish): the player's target is reset, cloaking ends (like EMP-01's effect on the
        player: targeting devices turn off, cloaking is broken) and the minimap is jammed."""
        w = self.w
        if w.hero_dead or w.jumping:
            return
        if w.attacking:
            w.laser_stop()
        w.abilities.reveal()
        w.items.reveal()
        msgs = [legacy('0|n|EMP|%d' % w.hid), legacy('0|n|EMAL|%d' % EMP_NOISE_SEC)]
        if w.target is not None:
            w.target = None
            msgs.append(('ShipDeselectionCommand', {}))
        w.send(msgs)
        w.log('   %s EMP darbesi savurdu' % n.d['name'])

    def match_speed(self, n, now):
        """The player's speed {ek, can_orani}: speed is matched to the player's (+ek). With can_orani, only when HP drops to that ratio (Hooligan:
        critical HP); Seeker Rocket always (player + 20)."""
        h = n.behavior['player_speed']
        if 'hp_ratio' in h and n.hp > n.d['hp'] * h['hp_ratio']:
            n.ab.pop('speed', None)
        else:
            n.ab['speed'] = max(1, int(self.w.p.d['ship'].get('speed', 300)) + h.get('extra', 0))

    # ------------------------------------------------------------ low HP: fleeing and parking (fandom Low health, Parking)
    def flees(self, n):
        """Whether this alien flees at low HP: strays in the map's own population and Galaxy Gate wave aliens (to a corner). Other gate, mode, event and summoned ones, immobile ones,
        the mothership and special bosses (yeniden_dogma_ozel), pirate maps (5-X), walled maps, the Barracuda (kamikaze) and the Hooligan whose speed is
        matched to the player's do not flee (fandom: mothership and pirates do not flee)."""
        w = self.w
        if n.gate and getattr(w.gate, 'corners', None):      # Galaxy Gate wave alien: to a corner (galaxy_gates.Run.corners)
            return (n.id not in w.gate.keep and not n.summoned and not getattr(n, 'passive', False) and n.d['speed'] > 0
                    and 'kamikaze_threshold' not in n.behavior and 'player_speed' not in n.behavior)
        if (n.gate or n.summoned or n.hunt or getattr(n, 'passive', False) or n.d['speed'] <= 0 or w.gate or w.low or w.labyrinth
                or n.tip in self.S.get('respawn_special', {}) or 'kamikaze_threshold' in n.behavior or 'player_speed' in n.behavior
                or H.map_class(w.map_id).startswith('5-') or ML.navigates(w.map_id)):
            return False
        return any(e['tip'] == n.tip for e in w.rules.get('npc', []))

    def flee_range(self, n):
        """Firing range while fleeing: for some aliens (Kristallon, Kristallin) it increases at low HP (fandom Low health)."""
        m, r = LOW['range_boost'], self.w.npc_range(n)
        return r * m['multiplier'] if any(s in n.d['name'].lower() for s in m['name']) else r

    def flee_spot(self, n, now):
        """Map alien: the edge point farthest from the player (without entering the safe zone and its path); otherwise where it is.
        Galaxy Gate: of the two corners the one nearest the alien, so it runs on away from the pilot it circles instead of across the map past them
        (user reports 2026-11-07 with a minimap shot: alien and pilot at the top right, it went to the far top-left corner instead of the
        bottom-right one; fandom Parking: "travels in the opposite direction from you until it reaches the corner")."""
        w, m = self.w, LOW['edge_margin']
        hx, hy = w.hero_pos(now)
        nx, ny = n.mover.pos(now)
        corners = getattr(w.gate, 'corners', None) if n.gate else None
        if corners:
            spots = [(m + (w.map_w - 2 * m) * cx, m + (w.map_h - 2 * m) * cy) for cx, cy in corners]
            return min(spots, key=lambda s: math.hypot(s[0] - nx, s[1] - ny))
        spots = [(x, y) for x in (m, w.map_w // 2, w.map_w - m) for y in (m, w.map_h // 2, w.map_h - m) if (x, y) != (w.map_w // 2, w.map_h // 2)]
        spots = [s for s in spots if not w.near_zone(s[0], s[1], 600) and not w.path_near_zone(nx, ny, s[0], s[1])]
        return max(spots, key=lambda s: math.hypot(s[0] - hx, s[1] - hy)) if spots else (int(nx), int(ny))

    def flee_move(self, n, st, now):
        tx, ty = st['target']
        ms = n.mover.go(tx, ty, n.speed() * n.effect.speed_factor(now), now)
        self.w.send([('MoveCommand', dict(userId=n.id, x=int(tx), y=int(ty), timeToTarget=ms))])

    def low_health(self, n, now):
        """Low HP (a map alien whose HP fell below low_hp.ratio): flees to the edge point opposite the player ('kac'; still fires if in range),
        stops on arrival and regenerates shield/HP ('park'; does not fire, does not retaliate when hit, regenerates while not hit);
        normal AI once regenerated to return_ratio. -> 'kac' | 'park' | None (world.think)."""
        st = n.ab.get('flee')
        if n.effect.frozen(now):
            return st['state'] if st else None
        if st is None:
            fr = n.behavior.get('flee_repair')
            if fr:                         # Terror Mimesis (forum 127094): flees to repair once below each HP threshold
                crossed = [r for r in fr['ratios'] if 0 < n.hp <= n.d['hp'] * r and 'flee_%s' % r not in n.ab]
                if not crossed or n.summoned or n.d['speed'] <= 0:
                    return None
                for r in crossed:
                    n.ab['flee_%s' % r] = now
            elif not (0 < n.hp < n.d['hp'] * LOW['ratio']) or not self.flees(n):
                return None
            st = n.ab['flee'] = dict(state='flee', target=self.flee_spot(n, now), reload=0.0)
            self.flee_move(n, st, now)
            self.w.log('   %s fleeing at low HP (HP %%%d)' % (n.d['name'], 100 * n.hp // max(1, n.d['hp'])))
        if n.hp >= n.d['hp'] * LOW['return_ratio'] and n.shield >= n.d['shield'] * LOW['return_ratio']:
            del n.ab['flee']                                       # tamamen yenilendi: normal yapay zekâ
            n.next_think = now
            return None
        if st['state'] == 'flee':
            if n.mover.t1 > now:
                return 'flee'
            x, y = n.mover.pos(now)
            if math.hypot(x - st['target'][0], y - st['target'][1]) > 150:
                self.flee_move(n, st, now)                         # its path was cut (slowing, freezing): again
                return 'flee'
            st['state'] = 'park'
            self.w.log('   %s parked in the corner: (%d,%d)' % (n.d['name'], x, y))
        n.engaged = False                                          # park: does not retaliate
        if now >= st['reload']:
            st['reload'] = now + 1.0
            r = LOW['regeneration']
            if now - n.last_hit >= r['cooldown_sec']:
                n.hp = min(n.d['hp'], n.hp + int(n.d['hp'] * r['hp_ratio_per_sec']))
                n.shield = min(n.d['shield'], n.shield + int(n.d['shield'] * r['shield_ratio_per_sec']))
                if self.w.target == n.id:
                    self.w.send([self.w.selection(n)])
        return 'park'

    # ------------------------------------------------------------ Emperor Sibelon: speed and capsules
    def speed_skill(self, n, now):
        h = n.behavior['speed_skill']
        if 'speed' not in n.ab and n.shield <= n.d['shield'] * h.get('shield_ratio', 0.1):
            n.ab['speed'] = h['speed']
            n.ab['capsule_at'] = now
            self.w.log('   %s sped up (%d)' % (n.d['name'], h['speed']))
        k = n.behavior.get('capsules')
        if 'speed' not in n.ab or not k:
            return
        mine = [a for a, c in self.capsules.items() if c['owner'] == n.id]
        if len(mine) < k['count'] and now >= n.ab['capsule_at']:
            n.ab['capsule_at'] = now + k['interval_sec']
            self.spawn_capsule(n)
            mine = [a for a, c in self.capsules.items() if c['owner'] == n.id]
        if not mine or n.effect.frozen(now):
            return
        nx, ny = n.mover.pos(now)
        aid = min(mine, key=lambda a: math.hypot(self.capsules[a]['x'] - nx, self.capsules[a]['y'] - ny))
        c = self.capsules[aid]
        d = math.hypot(c['x'] - nx, c['y'] - ny)
        if d <= k.get('harvest_distance', 150):
            if 'collecting' not in c:
                c['collecting'] = now + k['collect_ms'] / 1000.0
                self.w.send([('StartCapsuleCollectCommand', {'collectorId': n.id, 'assetId': aid, 'timer': k['collect_ms']})])
            elif now >= c['collecting']:
                self.collect_capsule(n, aid, k)
            return
        if n.ab.get('capsule') != aid or n.mover.t1 <= now:
            n.ab['capsule'] = aid
            ms = n.mover.go(c['x'], c['y'], n.ab['speed'] * n.effect.speed_factor(now), now)
            n.next_think = now + ms / 1000.0 + 0.5          # stops chasing and goes to the capsule
            self.w.send([('MoveCommand', dict(userId=n.id, x=int(c['x']), y=int(c['y']), timeToTarget=ms))])

    def spawn_capsule(self, n):
        w = self.w
        self.next_capsule += 1
        aid = self.next_capsule
        x, y = self.far_spot(n.mover.pos(time.time()), 2500)
        kind = random.choice(CAPSULES)
        self.capsules[aid] = dict(x=x, y=y, type=kind, owner=n.id)
        w.send([asset_create(aid, BUFF_CAPSULE, x, y, name='%s-Buff' % {'hp': 'HP', 'shield': 'SHD', 'damage': 'DMG'}[kind],
                             design=CAPSULES.index(kind))])
        w.log('   capsule appeared: %s (%d,%d)' % (kind, x, y))

    def drop_capsule(self, aid, why):
        c = self.capsules.pop(aid, None)
        if not c:
            return
        msgs = [asset_remove(aid, BUFF_CAPSULE)]
        if 'collecting' in c:
            msgs.insert(0, ('StopCapsuleCollectCommand', {'collectorId': c['owner']}))
        self.w.send(msgs)
        self.w.log('   capsule %s: %s' % (why, c['type']))

    def collect_capsule(self, n, aid, k):
        """The Emperor collected the capsule: HP/shield refills 10% or the damage increases and the player's drops (lifted when the Emperor dies)."""
        w = self.w
        kind = self.capsules[aid]['type']
        if kind == 'hp':
            n.hp = min(n.d['hp'], n.hp + n.d['hp'] * k['hp'])
        elif kind == 'shield':
            n.shield = min(n.d['shield'], n.shield + n.d['shield'] * k['shield'])
        else:
            n.ab['damage_bonus'] = n.ab.get('damage_bonus', 0) + k['damage']
            w.hero_effect('weakness', 3600, k['damage'], source='kapsul_%d' % n.id)
        self.drop_capsule(aid, 'collected')
        # collection visual (Ö1): a glowing ring around the Emperor for 4 s; type 0 damage (red), 1 shield, 2 HP (client:
        # EmperorSibelonBuffRingCommandHandler, diameter radius x 2; the radius is an adaptation)
        x, y = n.mover.pos(time.time())
        w.send([('EmperorSibelonBuffRingCommand', dict(avatarId=n.id, type={'damage': 0, 'shield': 1, 'hp': 2}[kind], radius=RING_RADIUS,
                                                       x=int(x), y=int(y)))])
        if w.target == n.id:
            w.send([w.selection(n)])

    def capsule_tick(self, now):
        """If a player passes near the capsule it vanishes; capsules whose owner died are lifted."""
        if not self.capsules:
            return
        w = self.w
        hx, hy = w.hero_pos(now)
        for aid, c in list(self.capsules.items()):
            owner = w.npcs.get(c['owner'])
            if not owner or not owner.alive:
                self.drop_capsule(aid, 'left without owner')
            elif not w.hero_dead and math.hypot(c['x'] - hx, c['y'] - hy) <= owner.behavior['capsules'].get('harvest_distance', 150):
                self.drop_capsule(aid, 'destroyed by a player')

    def capsule_msgs(self):
        """When the map reloads the capsules are announced again."""
        return [asset_create(aid, BUFF_CAPSULE, c['x'], c['y'], design=CAPSULES.index(c['type'])) for aid, c in self.capsules.items()]

    # ------------------------------------------------------------ death
    def on_kill(self, n, x, y):
        """The alien died: one that explodes (fake Emperor) hits a nearby player; its summons disperse (Cubikon); the DMG capsule's effect on the player
        is lifted."""
        w = self.w
        p = n.behavior.get('explode_on_death')
        msgs = []
        if p and not w.hero_dead:
            hx, hy = w.hero_pos()
            if math.hypot(x - hx, y - hy) <= p['radius']:
                msgs += w.hurt_hero(p['damage'], n, atype=0)
                w.log('   %s exploded: %d damage' % (n.d['name'], p['damage']))
        g = n.behavior.get('summons_scatter_on_death')
        if g:
            end = time.time()
            for cid in n.children:
                c = w.npcs.get(cid)
                if c and c.alive:
                    c.passive, c.engaged = True, False                    # wanders without chasing anyone (world.think)
                    c.ab['lifetime'] = end + random.uniform(*g['lifetime_sec'])
        if w.hero_effects.get('weakness'):
            w.hero_effects.remove('weakness', source='kapsul_%d' % n.id)
        left = [d for d in self.hero_dots if d['npc'] != n.id]
        if any(d.get('visual') for d in self.hero_dots) and not any(d.get('visual') for d in left):
            msgs.append(self.singularity_visual(False))                 # the singularity's owner died: the vortex is lifted
        self.hero_dots = left
        return msgs
