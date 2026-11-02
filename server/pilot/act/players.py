"""Auto Mode: other pilots on the hero's map that could attack it: players on a shared map (friend server, shared_maps.py) and the player
bots (server/bot, World.npcs entries with n.bot). Read only: nothing is sent (player_combat.attack_error has a side effect, the friendly
fire warning, so the same rules are read here without it)."""
import clan as KL
import bot.ship as BG


class Players:
    def hostiles(self, now):
        """-> [{id, name, x, y, attacking (firing at the hero), kind}]."""
        w = self.w
        out = []
        sh = getattr(w, 'shared', None)
        if sh is not None:
            for o in list(sh.members):
                if o is w or not o.running or o.hero_dead or o.jumping or getattr(o, 'reload_pending', False) or o.hidden(now):
                    continue
                if not self.player_hostile(o):
                    continue
                x, y = o.hero_pos(now)
                out.append(dict(id=o.hid, name=o.p.d['pilot'].get('userName', ''), x=x, y=y, kind='player',
                                attacking=bool(o.attacking and o.target == w.hid)))
        for n in list(w.npcs.values()):
            b = n.bot
            if b is None or not n.alive or getattr(n, 'hidden', False) or not self.bot_hostile(n):
                continue
            x, y = n.mover.pos(now)
            out.append(dict(id=n.id, name=getattr(b, 'name', ''), x=x, y=y, kind='bot',
                            attacking=getattr(n, 'target', None) == w.hid and bool(getattr(n, 'fire', False))))
        return out

    def player_hostile(self, o):
        """Could player o attack the hero (player_combat.attack_error's rules, without the peace zones of the moment)."""
        w = self.w
        if w.is_group_member(o.hid) or o.is_group_member(w.hid):
            return False
        a, b = w.p.d['pilot'], o.p.d['pilot']
        clan = int(a.get('clanId') or 0)
        if clan and clan == int(b.get('clanId') or 0):
            return False
        rel = (KL.relation(w.p, o.p), KL.relation(o.p, w.p))
        if any(r in (1, 2) for r in rel):
            return False
        return int(a.get('factionId') or 0) != int(b.get('factionId') or 0) or 3 in rel

    def bot_hostile(self, n):
        """Could the player bot attack the hero (the same rules as player_hostile): not one of its clan, nor an ally / non-aggression
        pact; another company or a clan at war; or it fires at the ship."""
        if getattr(n, 'target', None) == self.w.hid and getattr(n, 'fire', False):
            return True
        clan = int(self.p.d['pilot'].get('clanId') or 0)
        if clan and clan == int(n.bot.k.get('clan') or 0):
            return False
        rel = BG.relation(self.w, n.bot)
        if rel in (1, 2):
            return False
        return int(self.p.d['pilot'].get('factionId') or 1) != getattr(n.bot, 'company', None) or rel == 3
