"""PvP hunt: looking for the players of the enemy company (4-X, other companies' maps). manager.pvp_tick resolves the encounters; a bot on a hunt
counts as the attacker. Anger (just killed) and grudge (the one who killed it is in memory) draw the hunt: revenge."""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S


def find_target(y, name):
    """The person under a hunt order: from the bots or real players (name case-insensitive) -> (name, company, map or None
    (offline), clan, is human) or None."""
    a = str(name or '').strip().lower()
    if not a:
        return None
    x = y.name_index.get(a)
    if x is not None:
        return x.name, x.firma, (x.game_map if x.online else None), x.k.get('clan'), False
    import community as TP
    import clan as KL
    k = TP.find(name=a)
    if k is None:
        return None
    kl = KL.clan_of(k.profile)
    return (k.name, int(k.profile.d['pilot'].get('factionId') or 0),
            int(k.profile.d['position'].get('mapId', 0)) or None if k.session is not None else None, kl['id'] if kl else None, True)


def order_grudge(bot, name, now):
    """A hunt given by clan order (clan_orders) or the clan focus: this person is treated like a grudge (added to ship.pvp_target's grudge term)."""
    a = bot.k.get('hunt_order')
    name = str(name).lower()
    if a and now < a['end_time'] and a['name'] == name:
        return 1.0
    f = bot.k.get('clan_focus')
    if f and now < f['end_time']:
        import clan as KL
        c = KL.CLANS.get(f['clan'])
        if c is not None and name in c['members']:
            return 0.8
    return 0.0


def order_target(bot, y, now):
    """The online target of an ongoing hunt order (or clan focus) -> (name, map) or None."""
    a = bot.k.get('hunt_order')
    if a and now < a['end_time']:
        t = find_target(y, a['name'])
        if t is not None and t[2] and t[1] != bot.firma and K.route(bot.game_map, t[2], bot.firma, bot.level):
            return t[0], t[2]
    f = bot.k.get('clan_focus')
    if f and now < f['end_time']:
        import clan as KL
        c = KL.CLANS.get(f['clan'])
        for u in (c or {}).get('members', ()):
            t = find_target(y, u)
            if t is not None and t[2] and t[1] != bot.firma and K.route(bot.game_map, t[2], bot.firma, bot.level):
                return t[0], t[2]
    return None


@target
class PvpHunt(Goal):
    name = 'pvp'
    permission = 'pvp'
    min_sec = 240

    def eligible(self, bot, b):
        from .. import admin_warnings as AW
        from .. import weapons as WP
        return bot.level >= (b.setting('pvp_level', 6) or 1) and bot.value()['power'] >= 8 and not AW.active(bot, 'pvp', b.now)             and WP.has_laser(bot)                         # a player without ammo is not hunted

    def points(self, bot, b):
        o = bot.traits
        p = 0.1 + 0.55 * o['aggression'] * o['rekabet'] + (0.35 if bot.archetype == 'hunter' else 0)
        p += 0.45 * bot.mood['anger'] * o['aggression']
        p *= 0.6 + 0.6 * bot.mood['confidence']
        if b.y is not None and bot.memory.grudges() and b.y.online_name(bot.memory.grudges()):
            p += 0.25 * o['aggression']
        if b.y is not None and b.y.prime(b.now):
            p *= float(b.setting('prime_pvp', 2.0) or 1.0)           # evening rush hour: PvP picks up
        return p

    def start(self, bot, b):
        y = b.y
        target_map = None
        grudge = y.online_name(bot.memory.grudges()) if y is not None else None
        order = order_target(bot, y, b.now) if y is not None else None
        if order is not None:
            target_map = order[1]                           # clan order: goes to find the named person (or a member of the focus clan)
            bot.plan['hunt'] = order[0]
            grudge = order
        elif grudge is not None and K.route(bot.game_map, grudge.game_map, bot.firma, bot.level):
            target_map = grudge.game_map                        # revenge: goes to find the one who killed it
            bot.plan['hunt'] = grudge.name
        elif y is not None:
            # a map where the enemies are, that is reachable and has no overly strong enemy
            power = bot.value()['power']
            candidates = []
            for m, enemy in y.enemy_population(bot).items():
                if not enemy or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
                    continue
                threat = max(d.value()['power'] for d in enemy) / max(1.0, power)
                candidates.append((len(enemy) - 2.5 * max(0.0, threat - 1.0 - bot.o('risk')), m))
            if candidates:
                target_map = max(candidates)[1]
        if (y is not None and grudge is None and y.prime(b.now) and b.setting('big_battle', True) and bot.r.random() < 0.75
                and K.can_enter(y.front(b.now), bot.firma, bot.level) and K.route(bot.game_map, y.front(b.now), bot.firma, bot.level)):
            target_map = y.front(b.now)                    # big war: companies gather at the rush hour's front
            call = y.__dict__.setdefault('front_call', {})
            key = (bot.firma, int(b.now // 3600))
            if key not in call and bot.o('talkativeness') + bot.o('aggression') > 1.0:
                call[key] = bot.name
                import map_links as H
                from .. import speech as SPC
                y.speak(bot, 'company', SPC.template(bot, 'battle_call', map=H.name(target_map)), now=b.now + bot.r.uniform(3, 20))
        if target_map is None:
            target_map = next((m for m in (13 + bot.firma - 1, 16, 29) if K.can_enter(m, bot.firma, bot.level)), bot.game_map)
        bot.plan['map'] = int(target_map)
        S.go(bot, target_map, y, b.now)

    def concrete(self, bot, g, w, now):
        """Hunt on the map (clan order or revenge): if the hunted is on this map the bot flies toward it even without seeing it, and when in sight ship.pvp_target
        attacks (order_grudge and grudge put it first); if it moved to another map it follows (live 2026-11-01: the bot reached the hunted one's map
        and kept killing aliens there). While fighting, en route and with no hunted target, the ship's usual behavior."""
        from .. import ship as BG
        y = BG.MGR.ACTIVE
        order = order_target(bot, y, now) if y is not None else None
        if order is not None:
            bot.plan['hunt'] = order[0]                      # an ongoing order comes first (for an order given while already in PvP, start does not run again)
        name = str(bot.plan.get('hunt') or '').lower()
        if not name or g.target is not None or bot.en_route or any(now - t < 6 for t in g.attacker.values()):
            return False
        uid = next((m.id for m in w.npcs.values() if m.alive and m.bot is not None and m.bot.name.lower() == name), None)
        if uid is None:
            uid = next((o.hid for o in ([w] + list(w.shared.members if w.shared is not None else [])) if o.running and not o.hero_dead
                        and str(o.p.d['pilot'].get('userName', '')).lower() == name), None)
        if uid is None:
            t = find_target(y, name) if y is not None else None
            if (t is not None and t[2] and t[2] != bot.game_map and now >= bot.__dict__.get('_hunt_trail', 0)
                    and K.route(bot.game_map, t[2], bot.firma, bot.level)):
                bot._hunt_trail = now + 30
                bot.plan['map'] = int(t[2])
                S.go(bot, t[2], y, now)                  # the hunted moved to another map: follow
                return True
            return False
        t = BG.pvp_target(w, g, now)
        if t is not None:
            g.target = t                                   # in sight: attacks (the fight is in ship)
            return False
        pos = BG._position(w, uid, now)
        if pos is None:
            return False
        BG._go_to(w, g, pos[0], pos[1], now, threshold=300)
        return True

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        if K.map_npcs(bot.game_map) and bot.r.random() < 0.5:
            S.farm(bot, dt * 0.5, y)        # while waiting it also kills aliens (half efficiency)
