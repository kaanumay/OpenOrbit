"""Auto Mode: the panel's live map (status 'radar', written once a second). Everything the map draws, in short lists so the status file stays
small: the hero (position, velocity, the point it flies to), the aliens (flags: aggressive, attacking the hero, attackable, hunted, priority,
left alone), other pilots (player bots and the players of a shared map, friend or foe), boxes, ore, portals, the station, safe zones, quest
givers and obstacles. Velocities are units per second: the panel moves the marks between two status files.

Read only (under the world lock, like every act/ method)."""
import map_layout as ML
import map_links as H

NPC_AGGRESSIVE, NPC_ENGAGED, NPC_OK, NPC_HUNTED, NPC_PRIORITY, NPC_IGNORED = 1, 2, 4, 8, 16, 32


def _vel(mover, now, x, y):
    """Units per second toward where the mover will be in a second (0 when it stands)."""
    nx, ny = mover.pos(now + 1.0)
    return round(nx - x), round(ny - y)


class Radar:
    def radar(self, now, cfg):
        w = self.w
        hx, hy = w.hero_pos(now)
        hvx, hvy = _vel(w.hero, now, hx, hy)
        g = w.p.d['ship']
        dest = [int(w.hero.x1), int(w.hero.y1)] if w.hero.t1 > now else None
        ammo = self.laser_ammo()
        ignore = cfg.get('ignore') or ()
        types, npcs = {}, []
        for n in list(w.npcs.values()):
            if not self.visible_alien(n):
                continue
            x, y = n.mover.pos(now)
            vx, vy = _vel(n.mover, now, x, y)
            if n.tip not in types:
                model = str(n.d.get('model') or n.tip)
                types[n.tip] = dict(name=n.d.get('name', n.tip), icon='npc_%s_icon' % model if model.isdigit() else None,
                                    aggressive=bool(w.aggressive(n)))
            passive = getattr(n, 'passive', False)
            f = ((NPC_AGGRESSIVE if w.aggressive(n) and not passive else 0) | (NPC_ENGAGED if n.engaged and not passive else 0)
                 | (NPC_OK if self.attackable(n, now, ammo) else 0)
                 | (NPC_HUNTED if not cfg['aliens'] or n.tip in cfg['aliens'] or w.gate else 0)
                 | (NPC_PRIORITY if n.tip in (cfg.get('priority') or ()) else 0) | (NPC_IGNORED if n.id in ignore else 0))
            hp_max = max(1, n.d.get('hp', 1))
            npcs.append([n.id, n.tip, int(x), int(y), vx, vy, max(0, min(100, round(100 * n.hp / hp_max))), f])
        ships = self.radar_ships(now)
        boxes = []
        for b in w.boxes.values():
            if not w.own(b) or b.get('keyed'):
                continue
            tip = b.get('tip')
            kind = 'event' if b.get('event') else 'bonus' if tip == 'BONUS_BOX' else 'cargo' if tip in self.cargo_box_types() else 'other'
            boxes.append([int(b['x']), int(b['y']), kind])
        ores = [[int(o['x']), int(o['y']), o['tip']] for o in w.ores.values()]
        portals = []
        for gt in w.gates:
            if gt.get('hidden'):
                continue
            kind = 'exit' if gt.get('exit') else 'gate' if gt.get('gate') or gt.get('event_gate') else 'map'
            target = gt.get('target')
            portals.append([int(gt['x']), int(gt['y']), H.name(target) if target else '', target, kind, gt.get('gateId')])
        s = w.station
        station = [int(s['posX']), int(s['posY']), int(s.get('peaceRadius', 0)), int(s.get('type') or 0)] if s else None
        safe = []
        hs = w.home_station()
        if hs:
            safe.append([int(hs['posX']), int(hs['posY']), int(hs['peaceRadius'])])
        r = ML.gate_peace_radius(w.map_id, H.GATE_PEACE_RADIUS)
        safe += [[int(gt['x']), int(gt['y']), int(r)] for gt in w.peace_gates()]
        safe += [[int(a) for a in z] for z in ML.safe_zones(w.map_id)]
        return dict(
            map=int(w.map_id), name=H.name(w.map_id), w=int(w.map_w), h=int(w.map_h), t=now,
            hero=dict(x=int(hx), y=int(hy), vx=hvx, vy=hvy, dest=dest, ship=g.get('typeId', ''), company=self.company(),
                      hp=g.get('hitPoints', 0), hp_max=g.get('hitMax', 0), sh=g.get('shield', 0), sh_max=g.get('shieldMax', 0),
                      cargo=self.p.cargo_free(), cargo_max=g.get('cargoSpaceMax', 0), range=int(w.laser_range()),
                      peace=bool(w.in_peace(hx, hy))),
            types=types, npcs=npcs, ships=ships, boxes=boxes, ores=ores, portals=portals, station=station, safe=safe,
            givers=[[int(x), int(y)] for _, x, y in w.givers], walls=[[int(a) for a in r_] for r_ in ML.walls(w.map_id)])

    def radar_ships(self, now):
        """Other pilots: [id, name, x, y, vx, vy, company, ship, hostile (could attack the hero), attacking (fires at the hero)]."""
        w = self.w
        out = []
        sh = getattr(w, 'shared', None)
        if sh is not None:
            for o in list(sh.members):
                if o is w or not o.running or o.hero_dead or o.jumping or getattr(o, 'reload_pending', False) or o.hidden(now):
                    continue
                x, y = o.hero_pos(now)
                vx, vy = _vel(o.hero, now, x, y)
                pl = o.p.d['pilot']
                out.append([o.hid, pl.get('userName', ''), int(x), int(y), vx, vy, int(pl.get('factionId') or 0),
                            o.p.d['ship'].get('typeId', ''), self.player_hostile(o), bool(o.attacking and o.target == w.hid)])
        for n in list(w.npcs.values()):
            b = n.bot
            if b is None or not n.alive or getattr(n, 'hidden', False):
                continue
            x, y = n.mover.pos(now)
            vx, vy = _vel(n.mover, now, x, y)
            out.append([n.id, getattr(b, 'name', ''), int(x), int(y), vx, vy, int(getattr(b, 'company', 0) or 0), str(getattr(n, 'model', '') or ''),
                        self.bot_hostile(n), getattr(n, 'target', None) == w.hid and bool(getattr(n, 'fire', False))])
        return out
