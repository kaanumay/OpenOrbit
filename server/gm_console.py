"""GM console (roadmap Ö2): the client's hidden admin window (UIAdminTools, window 82) connects to the server.

In the client (Ghidra: UnitFactory.InitMyUnit, GmComponentSystem, GmComponentSystemAwake, ClientDebugHelper):
  - The window opens only when Hero.Admin; Admin = ShipInitializationCommand.dailyRank == 6000. To open: Ctrl, then Shift, then Z.
    When admin the client also shortens the exit countdown and writes quest ids as "#id:" in the quest list.
  - On first open CCInitRequest -> CCInitCommand {commands: [CCommandModule {name, args: [CCAttributeModule {name, subAttributes,
    range (CCListRangeModule {valueList}), ...}]}]}: the client takes into its dropdown lists only the value lists of the "box" (args 'spawn' > 'boxType' list)
    and "quest" (args 'accept' list) commands.
  - Commands are CCommandRequest {name, attributes: [CCRequestAttributeModule {name, value (CCIntValueModule / CCStringValueModule /
    CCItemValueModule / CCBooleanValueModule / CCQuestValueModule), subAttributes}]}:
      jump      map {x, y}                   teleport to the map
      kill      range N | viewport | target | unselected | almost | me     kill aliens (with their rewards), set HP to 1, oneself
      quest     accept|finish|fail|cancel <id>, finishAll
      book      item {amount, level, overheatPetGear} | package {amount}     give an item or package
      spawn     npcType {amount}             spawn an alien (the client's game.xml npcId: spawn_type)
      box       spawn {boxType, amount}      drop a box; collect {boxType, amount}: collect the nearest boxes
      god       toggle invulnerability
      cooldown  resetAll                     reset ability and item cooldowns
      pet       petLevel/lv                  P.E.T. level
      galaxyGates bookGGReward <name> | setup <name> {lifes, wave, lastWave}
      addEternalBlacklightPoints <n>         points to the EBL run
      battleStation                          Clan Battle Station (Ö5)
    There is no response command (the protocol has no CCommand... response): the result is written to the screen.
  - The console's Ship Check, Switch Ship, Effects (playing effects and VisualModifiers), Show Assets pages have no server side.
When the panel's "GM console" setting (gm_console, developer) is on, dailyRank 6000 is sent (the rank icon may appear blank) and the commands work.
"""
import json, math, os, random, time

import settings as SET
from legacy_protocol import legacy

REQUESTS = ('CCInitRequest', 'CCommandRequest')
ADMIN_RANK = 6000
GM_NPC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'gm_npc.json'), encoding='utf8'))['npc']
DERIVED = ('gg_', 'event_', 'pm_', 'apo_', 'experiment_')      # gate, event, mode copies: the original type first for the same npc_id
STAND_IN = '79'                                          # values of an NPC that has no counterpart on the server (Kristallon)


def enabled(profile=None):
    """On a friend server only the server's own player (off for a guest even if the server's setting is on)."""
    return bool(SET.get('gm_console')) and getattr(profile, 'guest', None) is None


def mod(_cls, **f):
    f['_'] = _cls                 # 'name' is the modules' own field
    return f


def values(attrs):
    """CCRequestAttributeModule list -> [(name, value, sub-items)] (value by the value module's type int / str / bool / lootId)."""
    out = []
    for a in attrs or []:
        v = a.get('value') or {}
        val = next((v[k] for k in ('value', 'lootId', 'cdCom') if k in v), None)
        out.append((a.get('name') or '', val, values(a.get('subAttributes'))))
    return out


def flat(attrs):
    """All items in a single dictionary: name -> value (first seen)."""
    d = {}
    for name, val, sub in values(attrs):
        d.setdefault(name, val)
        for k, v in flat_items(sub):
            d.setdefault(k, v)
    return d


def flat_items(rows):
    for name, val, sub in rows:
        yield name, val
        yield from flat_items(sub)


def num(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def world_types():
    import world
    return world.CFG['types']


def _plain(s):
    return ''.join(c for c in str(s or '').lower() if c.isalnum())


def spawn_type(want):
    """The spawn page's npcId -> (type, model, name). The client sends the npcId in game.xml (data/gm_npc.json); since the type keys
    (Battleray '115') collide with other NPCs' ids, npc_id first (player report 2026-10-30: Emperor Kristallon
    115 -> Battleray, Ufo 25 -> Boss Saimon). For one with no id on the server: the ship type if it is a type key, the name if it equals a type's,
    otherwise the fallback type's values with the client's model and name (model, name filled in)."""
    T = world_types()
    same = [k for k, v in T.items() if str(v.get('npc_id')) == want and not k.startswith(('eg_', 'kp_'))]
    if same:
        return min(same, key=lambda k: (not k.isdigit(), k.startswith(DERIVED))), None, None
    kind, name = GM_NPC.get(want) or (None, None)
    if not name:
        return (want, None, None) if want in T else (None, None, None)
    alike = next((k for k, v in T.items() if _plain(v.get('name')) == _plain(name) and not k.startswith(('eg_', 'kp_'))), None)
    if alike:
        return alike, None, None
    name = name if name.startswith(('-=', '..', '(', '\\', '<')) else '-=[ %s ]=-' % name
    if kind in T:                            # another-named design of the same model (Boss Kucurbium: UberLordakium's model)
        return kind, None, name
    return STAND_IN, kind, name


class Console:
    """The session's GM console (game.Session binds: s)."""

    def __init__(self, session, log=print):
        self.s, self.log = session, log

    @property
    def w(self):
        return self.s.world

    def say(self, text):
        from galaxy_gates import screen
        self.log('   GM: %s' % text)
        return [screen('GM: ' + text)]

    def handle(self, name, f):
        if not enabled(self.s.profile):
            self.log('   GM console off (panel: Developer > GM console): %s' % name)
            return []
        if name == 'CCInitRequest':
            return [self.init_cmd()]
        cmd = (f.get('name') or '').strip()
        fn = getattr(self, 'cmd_' + cmd, None)
        if not fn:
            return self.say('bilinmeyen komut %s' % cmd)
        try:
            return fn(values(f.get('attributes')), flat(f.get('attributes')))
        except Exception as e:                      # the console must not crash the game
            import traceback
            self.log(traceback.format_exc())
            return self.say('%s hatası: %s' % (cmd, e))

    # ------------------------------------------------------------ opening lists
    def init_cmd(self):
        import world
        import loot as LOOT
        import quest as QU
        boxes = ['BONUS_BOX'] + sorted(LOOT.BOXES) + sorted({k for k in world.CFG.get('box_kinds', [])})
        box_list = mod('CCListRangeModule', valueList=[mod('CCStringValueModule', name=b, value=b) for b in dict.fromkeys(boxes)])
        quest_list = mod('CCListRangeModule', valueList=[mod('CCQuestValueModule', name='%d %s' % (q, d['name']), value=q)
                                                         for q, d in sorted(QU.QUESTS.items())])
        attr = lambda name, rng=None, sub=(): mod('CCAttributeModule', name=name, subAttributes=list(sub), singleAttributeSelection=True,
                                                   range=rng or mod('CCAbstractRangeModule'), toolTip='')
        box = mod('CCommandModule', name='box', toolTip='', singleAttributeSelection=True,
                  args=[attr(a, sub=[attr('boxType', box_list), attr('amount', mod('CCNumericRangeModule', min=1, max=100))])
                        for a in ('spawn', 'collect')])
        quest = mod('CCommandModule', name='quest', toolTip='', singleAttributeSelection=True,
                    args=[attr('accept', quest_list), attr('finish', quest_list), attr('fail', quest_list), attr('finishAll')])
        return 'CCInitCommand', {'commands': [box, quest]}

    # ------------------------------------------------------------ komutlar
    def cmd_jump(self, rows, d):
        import map_links as H
        dest = num(d.get('map'))
        if dest not in H.NAMES and not H.client_map_name(dest):
            return self.say('harita %s yok' % d.get('map'))
        x, y = num(d.get('x')), num(d.get('y'))
        if not x and not y:
            pos = None
        else:
            w, h = H.map_size(dest)
            pos = (max(0, min(w, x)), max(0, min(h, y)))
        self.log('   GM: teleport %s %s' % (dest, pos))
        self.s.change_map(dest, None, pos=pos)
        return []

    def cmd_kill(self, rows, d):
        """The console's kill page (the client sends "option[,value]"): range N (aliens in range), viewport (those on screen), target
        (selected), unselected (those on screen other than the selected), almost (the selected or those on screen: HP 1, shield 0), me (the player's ship)."""
        w = self.w
        if not w:
            return []
        name, val = (rows[0][0].lower(), rows[0][1]) if rows else ('range', 1000)
        now = time.time()
        with w.lock:
            alive = [n for n in list(w.npcs.values()) if n.alive]
            seen = [n for n in alive if n.id in w.visible]
            if name == 'me':
                if w.hero_dead:
                    return self.say('gemi zaten yok edilmiş')
                msgs = []
                w.p.set_hull(hp=0, shield=0)
                w.hero_death(msgs)
                return msgs + self.say('gemin yok edildi')
            if name == 'target':
                near = [n for n in alive if n.id == w.target]
            elif name == 'unselected':
                near = [n for n in seen if n.id != w.target]
            elif name == 'viewport':
                near = seen
            elif name == 'almost':
                near = [n for n in alive if n.id == w.target] or seen
                msgs = []
                for n in near:
                    n.hp, n.shield = 1, 0
                    if n.id == w.target:
                        msgs.append(w.selection(n))
                return msgs + self.say('%d uzaylının canı 1' % len(near))
            else:
                rng = num(val, 1000)
                hx, hy = w.hero_pos(now)
                near = [n for n in alive if math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= rng]
            msgs = []
            for n in near:
                msgs += w.kill(n)
        return msgs + self.say('%d uzaylı öldürüldü (%s)' % (len(near), name if name != 'range' else 'menzil %s' % val))

    def cmd_quest(self, rows, d):
        import quest as QU
        quests = self.s.quest
        msgs = []
        for name, val, sub in rows:
            name = name.lower()                     # the client's page: Accept, Finish, FinishAll, Fail
            if name == 'finishall':
                done = [int(q) for q in list(quests.st['active'])]
                for q in done:
                    msgs += quests.complete(q)
                return msgs + self.say('%d görev bitirildi' % len(done))
            q = num(val)
            if q not in QU.QUESTS:
                return self.say('görev yok: %s' % val)
            if name == 'accept':
                return quests.accept(q) + self.say('görev alındı: %d' % q)
            if name == 'finish':
                if str(q) not in quests.st['active']:
                    msgs += quests.accept(q)
                return msgs + quests.complete(q) + self.say('görev bitti: %d' % q)
            if name == 'fail':
                return quests.fail(q, 'GM') + self.say('görev başarısız: %d' % q)
            if name == 'cancel':
                return quests.cancel(q) + self.say('görev iptal: %d' % q)
        return self.say('görev komutu anlaşılmadı')

    def cmd_book(self, rows, d):
        m = self.s.shop
        if d.get('package'):
            loot, n = d['package'], max(1, num(d.get('amount'), 1))
            grants = m.contents(loot, n) or []
            msgs = []
            for g, k in grants:
                msgs += m.reward(g, k)
            return msgs + m.money_msgs() + self.say('paket %s x%d (%d eşya)' % (loot, n, len(grants)))
        loot, n = d.get('item'), max(1, num(d.get('amount'), 1))
        if not loot:
            return self.say('eşya yok')
        msgs = m.reward(loot, n)
        lv = num(d.get('level'))
        if lv > 1:
            self.log('   GM: level %d requested (upgrade in Assembly\'s)' % lv)
        return msgs + m.money_msgs() + self.say('%s x%d' % (loot, n))

    def cmd_spawn(self, rows, d):
        w = self.w
        if not w:
            return []
        want = str(d.get('npcType') or '')
        tip, model, name = spawn_type(want)
        if not tip:
            return self.say('uzaylı türü yok: %s' % want)
        n = max(1, min(50, num(d.get('amount'), 1)))
        prep = (lambda x: setattr(x, 'd', dict(x.d, name=name))) if name else None
        now = time.time()
        with w.lock:
            hx, hy = w.hero_pos(now)
            for k in range(n):
                a = 2 * math.pi * k / n
                w.spawn_npc_at(tip, hx + math.cos(a) * 600, hy + math.sin(a) * 600, model=model, prep=prep)
        return self.say('%s x%d' % (name or world_types()[tip]['name'], n))

    def cmd_box(self, rows, d):
        import world
        w = self.w
        if not w:
            return []
        kind, n = d.get('boxType') or 'BONUS_BOX', max(1, min(50, num(d.get('amount'), 1)))
        now = time.time()
        if any(name == 'collect' for name, _, _ in rows):
            # Collect button (client GmComponentSystem.SendCollectBox: 'collect' {boxType, amount}): collects the nearest boxes
            # (player report 2026-10-30: it dropped boxes like Spawn)
            with w.lock:
                hx, hy = w.hero_pos(now)
                near = sorted((math.hypot(b['x'] - hx, b['y'] - hy), h) for h, b in w.boxes.items() if b['tip'] == kind and w.own(b))
                got = sum(1 for _, h in near[:n] if w.take_box(h) is not False)
            return self.say('%s toplandı: %d' % (kind, got))
        with w.lock:
            hx, hy = w.hero_pos(now)
            for k in range(n):
                x, y = hx + random.randint(-400, 400), hy + random.randint(-400, 400)
                content = random.choice(world.CFG['bonus_boxes']) if kind == 'BONUS_BOX' else None
                w.drop_box(kind, x, y, content, None)
        return self.say('%s x%d' % (kind, n))

    def cmd_god(self, rows, d):
        w = self.w
        if not w:
            return []
        w.invulnerable = not w._invulnerable
        return self.say('dokunulmazlık %s' % ('açık' if w._invulnerable else 'kapalı'))

    def cmd_cooldown(self, rows, d):
        import ship_ability as SA
        import combat_items as CIT
        p, now = self.s.shop.p, time.time()
        with p.lock:
            p.d[CIT.TIMERS] = {}
            for st in SA.state(p).values():
                if isinstance(st, dict):
                    st['ready'] = 0
                    st['end_time'] = min(st.get('end_time', 0), now)
            p.dirty = True
        msgs = p.menu_changes()
        if self.w:
            self.w.rocket_ready = 0.0
            self.w.ammo_ready = {}
            msgs += [SA.timer_msg(p, i, now) for i in SA.ship_items(p)]
        return msgs + self.say('bekleme süreleri sıfırlandı')

    def cmd_pet(self, rows, d):
        import pet as PETM
        pet = self.s.pet
        if not pet.owned:
            return self.say('P.E.T. yok')
        lv = max(0, min(len(PETM.PET['levels']) - 1, num(d.get('lv') or d.get('petLevel'))))
        with pet.p.lock:
            pet.d['level'] = lv
            pet.d['ep'] = PETM.PET['levels'][lv]['ep']
            pet.p.dirty = True
        pet.p.ach('pet_level', value=lv)
        return [('PetLevelUpdateCommand', dict(petLevel=lv, petExperiencePointsUntilNextLevel=pet.next_xp(), designId=pet.ship_type(),
                                               expansionStage=1)),
                ('PetExperiencePointsUpdateCommand', dict(currentExperiencePoints=pet.d['ep'], maxExperiencePoints=pet.next_xp()))] + \
            self.say('P.E.T. seviyesi %d' % lv)

    def cmd_galaxyGates(self, rows, d):
        import galaxy_gates as GALAXY
        k = self.s.gates
        for name, val, sub in rows:
            if name == 'bookGGReward':
                key = str(val or '').strip().lower()
                if key not in GALAXY.GATES:
                    return self.say('kapı yok: %s' % val)
                w = self.w
                msgs, info = k.finish(key, w.reward_msgs if w else None)
                return msgs + self.say('%s ödülü verildi' % GALAXY.GATES[key]['name'])
            if name in ('setup', 'galaxyGates'):
                parts = [x.strip() for x in str(val or '').split(',')]
                key = parts[0].lower() if parts and parts[0] else ''
                if key not in GALAXY.GATES:
                    return self.say('kapı yok: %s' % (parts[0] if parts else ''))
                flat = dict((n, v) for n, v in flat_items(sub))
                g = GALAXY.GATES[key]
                lifes = num(flat.get('lifes') or (parts[1] if len(parts) > 1 else 0)) or g['hp']
                wave = num(flat.get('wave') or (parts[2] if len(parts) > 2 else 0))
                last = str(flat.get('lastWave') or (parts[3] if len(parts) > 3 else '')).lower() in ('true', '1')
                with k.p.lock:
                    G = k.gate(key)
                    G.update(ready=True, hp=lifes, lives_bought=0, parts=list(range(1, g['part'] + 1)),
                             wave=len(g['waves']) - 1 if last else max(0, min(len(g['waves']) - 1, wave - 1 if wave else 0)))
                    k.p.dirty = True
                return self.say('%s kuruldu: %d can, dalga %d (X-1 portalı)' % (g['name'], lifes, G['wave'] + 1))
        return self.say('kapı komutu anlaşılmadı')

    def cmd_addEternalBlacklightPoints(self, rows, d):
        n = next((num(v) for k, v in d.items() if num(v)), 0)
        ebl = self.s.pve.ebl if self.s.pve else None
        if not ebl or not getattr(ebl, 'run', None):
            return self.say('EBL koşusu yok')
        with ebl.p.lock:
            ebl.run['points'] = ebl.run.get('points', 0) + n
            ebl.p.dirty = True
        return self.say('EBL puanı +%d (%d)' % (n, ebl.run['points']))

    def cmd_battleStation(self, rows, d):
        cbs = getattr(self.s, 'cbs', None)
        if cbs and hasattr(cbs, 'gm'):
            return cbs.gm(rows, d)
        return self.say('Clan Battle Station sunucuda henüz yok')
