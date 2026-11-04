"""Sharing maps on the friend server (multiplayer.py; the panel's "Play with your friends" page).

In single player every session has its own world (world.World). On the friend server the worlds of players on the same normal map
share a Map: the aliens, boxes, ores, pending spawns, the alien id counter, the calendar's map event and the world
lock are common (the worlds' loop steps run in turn). Each world drives its own hero: position, target, fire, effects, P.E.T.,
portals, rewards (whoever kills the alien gets the reward; in a group it is shared with the members on the same map: world.World.tag_sharers, group.py).
  - An alien's AI (world.think), abilities (alien.py), poison and repair are run by the world that "owns" it: the player it
    fights (the player who hits becomes the owner), or if it is not fighting, the nearest reachable player (owners).
  - The map's jobs (respawns, boxes whose time is up, timed aliens, the calendar's map event) run in the leader's loop:
    the first to enter the map, and when it leaves the next one.
  - Messages everyone must see (alien movement, lasers and hits, explosions, visual effects) are mirrored from the sending world to the other
    members (mirror); each recipient gets only those of the ships it knows (World.knows).
  - Players see each other within view distance, group members everywhere on the map (visibility): ShipCreateCommand, title, drones
    and modules (messages of another player in the save; game.Session.appearance), the hero's movement as MoveCommand (movement). A dead,
    jumping or hidden player is invisible.
Gate, mode and event maps (those that are the session's own run) are not shared: each player has their own copy (game.Session.start_world).
When the last player leaves, the map state is kept as in single player (world.WORLD_CACHE) and the shared state is released.
"""
import math, threading

UID_BASE = 150300000          # start of the alien ids (same as world.World's)
FLASHLIGHT = 62               # flashlight (world.FLASHLIGHT): an effect on the player's own screen, not mirrored
OWNER_SEC = 0.1                # interval at which owners are recomputed (loop step)
# mirrored messages -> the fields of the ship ids in them (it goes if the recipient knows them all; 0: environment, e.g. radiation)
REFLECTED = {'MoveCommand': ('userId',), 'AttackLaserRunCommand': ('attackerId', 'targetId'),
            'AttackHitCommand': ('attackerId', 'victimId'), 'AttackMissedCommand': ('targetUserId',),
            'ShipDestroyedCommand': ('destroyedUserId',), 'VisualModifierCommand': ('userId',),
            # end of the laser: in AttackLaserRunCommand the client sets the attacker's target (ShipInfo.Target) and turns the ship toward it;
            # if this does not arrive, the other player's ship stays facing the target, its nose does not turn and no engine effect appeared (AttackAbortLaser.Run)
            'AttackAbortLaserCommand': ('uid',),
            # emote, level-up, ship abilities, particle cannon, Hellstorm (list fields: every id in it)
            'EmoteActivationCommand': ('userId',), 'LevelUpCommand': ('uid',),
            'AbilityEffectActivationCommand': ('activatorId', 'targetIds'), 'AbilityEffectDeActivationCommand': ('activatorId', 'targetIds'),
            'AbilityStartCommand': ('activatorId',), 'AbilityStopCommand': ('activatorId', 'targetIds'),
            'PlayVisualEffectCommand': ('activatorId', 'targetIds'), 'CannonAttackCommand': ('attackerId', 'attackedId'),
            'HellstormAttackCommand': ('attackerId', 'targetId')}
# the player's mines and fireworks (combat_items.py; their tags M<id>_<seq>, F<id>_<seq>) and the spray are visible to everyone;
# an alien's mine (U...) only hits the hero of the world that laid it, not mirrored
PLAYER_HASH = ('M', 'F')
SPRAY = 69                    # AssetCreateCommand type (combat_items.SPRAY_ASSET)
# visuals sent with legacy text (legacy_protocol.py) -> the part order of the ship ids in them (the first number list: all the remaining parts
# are ids): rocket 0|v|attacker|target|..., Smart Bomb / Insta-Shield / EMP 0|n|SMB|uid, ship ability 0|n|SD|A|effect|permanent|
# activator[|target], technology 0|n|A|S|code|uid, Chain Impulse 0|n|ECI|1|attacker|target..., freeze/slow 0|n|fx|start|type|uid,
# Battle Repair Bot/NPC Nuke shock wave 0|n|BT|uid, 0|n|NNK|uid, collecting beam 0|A|SLA|mode|unit, heal count 0|A|HL|healer|
# target|... and invisibility 0|n|INV|uid|open
LEGACY = {('0', 'v'): (2, 3), ('0', 'n', 'SMB'): (3,), ('0', 'n', 'ISH'): (3,), ('0', 'n', 'EMP'): (3,),
        ('0', 'n', 'SD'): (6, [7]), ('0', 'n', 'A', 'S'): (5,), ('0', 'n', 'ECI'): (4, [5]), ('0', 'n', 'fx'): (5,),
        ('0', 'n', 'BT'): (3,), ('0', 'n', 'NNK'): (3,), ('0', 'A', 'SLA'): (4,), ('0', 'A', 'HL'): (3, 4), ('0', 'n', 'INV'): (3,)}

REG = threading.Lock()
MAPS = {}                # map id -> Map (while a world uses it)


def take(map_id):
    """The map's shared state (created if missing). Once when a world is set up (World.__init__); release() when the world stops."""
    with REG:
        h = MAPS.get(str(map_id))
        if h is None:
            h = MAPS[str(map_id)] = Map(str(map_id))
        h.ref += 1
        return h


class Map:
    def __init__(self, map_id):
        self.map_id = map_id
        self.lock = threading.RLock()
        self.npcs, self.boxes, self.ores = {}, {}, {}
        self.pending, self.ore_fields = [], []
        self.next_uid = UID_BASE
        self.members = []              # worlds whose loop is running, by entry order (the first is the leader)
        self.starting = set()          # worlds in World.start (not yet members): a second one joins their population
        self.event = None          # the calendar's map event (event_maps.MapEvents; the leader drives it)
        self.ref = 0                  # worlds holding this map (including those set up but not yet entered)
        self._owner, self._owner_at = {}, 0.0

    @property
    def leader(self):
        return self.members[0] if self.members else None

    def killer(self, w):
        """The world's loop started (under the world lock)."""
        if w not in self.members:
            self.members.append(w)
        if self.event is not None:
            self.event.w = self.leader
        self._owner_at = 0.0

    def detach(self, w):
        """The world stopped (map change, connection dropped) -> True if no member remains. The aliens fighting it are re-owned."""
        with self.lock:
            if w in self.members:
                self.members.remove(w)
            for n in self.npcs.values():
                if getattr(n, 'foe', None) is w:
                    n.foe = None
            if self.event is not None and self.leader is not None:
                self.event.w = self.leader
            self._owner_at = 0.0
            return not self.members

    def release(self):
        """The world let go of this map (once): if nobody holds it, it is removed from the registry."""
        with REG:
            self.ref -= 1
            if self.ref <= 0 and MAPS.get(self.map_id) is self:
                del MAPS[self.map_id]

    # ------------------------------------------------------------ owners of the aliens
    def owners(self, now):
        """alien id -> the world that runs its AI. A fighting alien goes to the player it fights (if on the map); other aliens go
        to the nearest reachable player (not dead, not jumping, not in a safe zone, not hidden; if there is none, the nearest)."""
        if now - self._owner_at < OWNER_SEC:
            return self._owner
        members = [w for w in self.members if w.running]
        pos = {w: w.hero_pos(now) for w in members}
        is_open = {w: w.reachable(now) for w in members}
        out = {}
        for n in self.npcs.values():
            f = getattr(n, 'foe', None)
            if not (n.engaged and f in pos):
                nx, ny = n.mover.pos(now)
                f = min(members, key=lambda w: (not is_open[w], (pos[w][0] - nx) ** 2 + (pos[w][1] - ny) ** 2), default=None)
                n.foe = f
            out[n.id] = f
        self._owner, self._owner_at = out, now
        return out

    def is_owner(self, w, n, now):
        """Whether this world runs the alien's AI (a newly spawned, not yet computed alien: the leader)."""
        o = self.owners(now).get(n.id)
        return (o if o is not None else self.leader) is w

    # ------------------------------------------------------------ mesajlar
    def mirror(self, source, msgs):
        """The source world's messages visible to everyone, to the other members (those of the ships they know)."""
        out = [(m, uid_list(m)) for m in msgs if not (m[0] == 'VisualModifierCommand' and m[1].get('modifier') == FLASHLIGHT)]
        out = [(m, ids) for m, ids in out if ids is not None]
        if not out:
            return
        for w in self.members:
            if w is source or not w.running:
                continue
            mine = [m for m, ids in out if all(w.knows(x) for x in ids)]
            if mine:
                w.deliver(mine)

    def movement(self, source, x, y, ms):
        """The hero moved: MoveCommand to the players who see it (not to the player themselves; the client drives that itself)."""
        m = ('MoveCommand', dict(userId=source.hid, x=int(x), y=int(y), timeToTarget=int(ms)))
        for w in self.members:
            if w is not source and w.running and source.hid in w.players:
                w.deliver([m])

    def visibility(self, w, now, hx, hy, vision, release):
        """The other players' ships in w's client: show the one that comes into view, remove the one that leaves (died, jumped, hid, left, appearance
        changed) -> messages. A group member is visible wherever on the map (group.py)."""
        cur = {}
        for m in self.members:
            if m is w or not m.running or m.hero_dead or m.jumping or m.reload_pending or (m.hidden(now) and w.target != m.hid):
                continue                   # a hidden one stays on the one who selected it (can be hit: player_combat.attack_error)
            mx, my = m.hero_pos(now)
            lim = release if m.hid in w.players else vision
            if math.hypot(mx - hx, my - hy) <= lim or w.is_group_member(m.hid):
                cur[m.hid] = m
        msgs = []
        for uid in list(w.players):
            m = cur.get(uid)
            if m is None or w.players[uid] != signature(w, m):
                del w.players[uid]
                msgs.append(('ShipRemoveCommand', {'userId': uid}))
        for uid in list(w.pets):         # visible with the P.E.T.'s owner; removed when the owner goes or the P.E.T. changes (stopped, new design)
            if uid not in w.players or w.pets[uid] != pet_signature(w, cur[uid]):
                msgs.append(('ShipRemoveCommand', {'userId': w.pets.pop(uid)[0]}))
        for uid, m in cur.items():
            if uid not in w.players:
                w.players[uid] = sig = signature(w, m)
                msgs += [(n, dict(f, clanDiplomacy=dict(f['clanDiplomacy'], type=sig[1]))) if n == 'ShipCreateCommand' and f.get('userId') == m.hid
                         else (n, f) for n, f in m.gorunum_msgs(now)]
        for uid, m in cur.items():
            sig = pet_signature(w, m)
            if sig and uid not in w.pets:
                w.pets[uid] = sig
                msgs += [(n, dict(f, clanRelationship=dict(f['clanRelationship'], type=sig[-1]))) if n == 'PetActivationCommand' else (n, f)
                         for n, f in m.pet.view_msgs(now)]
        return msgs


def signature(w, m):
    """m's ship in w's client: its appearance and clan relation (relative to the viewer; the ship is rebuilt when diplomacy changes)."""
    import clan as KL
    return m.signature(), KL.shown_relation(w.p, m.p)


def pet_signature(w, m):
    """m's P.E.T. in space, in w's client: id, appearance, name, level and clan relation; None if the P.E.T. is not in space."""
    pet = m.pet
    if not (pet and pet.active and pet.w is m):
        return None
    import clan as KL
    return pet.pid, pet.look, pet.d['name'], pet.d['level'], KL.shown_relation(w.p, m.p)


def uid_list(m):
    """The ship ids of the mirrored message (the recipient must know them all) or None (not mirrored)."""
    if m[0] in REFLECTED:
        ids = []
        for k in REFLECTED[m[0]]:
            v = m[1].get(k)
            ids += v if isinstance(v, list) else [v]
        return ids
    if m[0] in ('AddMineCommand', 'RemoveMineCommand', 'AddFireworkBoxCommand'):
        return [] if str(m[1].get('hash', '')).startswith(PLAYER_HASH) else None
    if m[0] in ('AssetCreateCommand', 'AssetRemoveCommand'):
        kind = m[1].get('type') or m[1].get('assetType') or {}
        return [] if kind.get('typeValue') == SPRAY else None
    if m[0] != 'LegacyModule':
        return None
    parts = str(m[1].get('message', '')).split('|')
    if parts[:3] in (['0', 'n', 'MIN'], ['0', 'n', 'FWG']):          # a mine's explosion, the firing of fireworks (with their tags)
        return [] if len(parts) > 3 and all(h.startswith(PLAYER_HASH) for h in parts[3:]) else None
    for key, pos in LEGACY.items():
        if tuple(parts[:len(key)]) != key:
            continue
        fixed = [i for i in pos if not isinstance(i, list)]
        rest = [j for i in pos if isinstance(i, list) for j in range(i[0], len(parts))]
        try:
            return [int(parts[i]) for i in fixed + rest]
        except (ValueError, IndexError):
            return None
    return None


def is_shared(w):
    """Whether the world is on a shared map and whether there is another player there (mirroring is skipped if unnecessary)."""
    return w.shared is not None and len(w.shared.members) > 1
