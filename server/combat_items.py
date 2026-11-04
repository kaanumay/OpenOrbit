"""Combat items and active CPUs: mines, Smart Bomb, Insta-Shield, EMP-01, jump/cloak/aim CPUs, automatic rocket and
launcher CPUs, the rocket launcher, special rockets. Data items.json "combat_items", "rockets" and "extras" (research:
the client's code, belgeler/wiki/rockets.md, belgeler/wiki/extras_cpu_tech.md). One Items per world (world.items); the shortcut bar comes from
world.menu_action, the rocket from AttackRocketRequest.

The client (1.1.114) does not handle the binary MapEvent* and JumpCPU* commands; the effects are shown with the old text protocol:
  AddMineCommand / RemoveMineCommand        placing a mine / silent removal (when its lifetime ends)
  0|n|MIN|hash                              the mine explodes and is removed from the map
  0|n|SMB|uid  0|n|ISH|uid  0|n|EMP|uid     Smart Bomb, Insta-Shield, EMP visuals
  0|n|INV|uid|1 or 0                        cloaking
  0|A|JCPU|S|sec|map                        countdown of a CPU jump (-1|0 cancel); then the map change as in a portal jump
  0|A|JCPU|I|…  0|A|JCPU|C|…  0|A|JV|n      advanced jump (AJP-01): map list, choice reply, coupon count
  0|RL|S|type|rocket|loaded                 as the launcher fills (sound); HellstormAttackCommand: launcher shot
  0|v|attacker|target|H|rocket|trail|homing rocket (rocket = visual id; trail and homing world.rocket_look)
  0|n|fx|start or end|ICY_CUBE|uid          freezing, SABOTEUR_DEBUFF slowdown visual
Cooldowns use MenuItemCooldownGroupTimerCommand (group: the client's CooldownType); ends are in the profile (they continue across map changes too).
"""
import itertools, json, math, os, random, time
import game_data as DATA

import extras as EX
import map_links as H
import map_layout as ML
import settings as SET
import event_calendar as CAL
import skill_tree as SKL
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_E = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf8'))
_N = DATA.load('npc.json')
S = _E['combat_items']
O6 = json.load(open(os.path.join(HERE, 'data', 'items_o6.json'), encoding='utf8'))       # Ö6: expressions (tools/items_o6.py)
EMOTE_PREFIX = 'ammunition_specialammo_emote_'
ROCKETS = _E['rockets']
MINES = S['mines']
# Curcubitor's Trick mine is born when the event alien dies; the player neither buys nor places it: it stays in MINES for damage and visuals,
# removed from inventory and menu operations
EVENT_MINES = frozenset({'curcubitor_mayini'})
PLAYER_MINES = frozenset(MINES) - EVENT_MINES
LAUNCHERS = S['launcher']['kinds']
LAUNCHER_AMMO = S['launcher_ammo']
# Dot color of the launcher item (the client's CounterStyle: 0 DEFAULT, 1 RED, 2 GREEN, 3 YELLOW, 4 BLUE, 5 CYAN, 6 ORANGE). Real
# recording (20261027_235305): ECO-10 4, HSTRM-01 3, UBR-100 1, BDR1212 5, SAR-02 5. Those not in the recording use the client's icon color
# (atlas_assets_all): SAR-01 and PIR-100 cyan, CBR blue-gray, OBR-100 purple-white (no purple in the enum: DEFAULT)
LAUNCHER_COLOR = {'ammunition_rocketlauncher_eco-10': 4, 'ammunition_rocketlauncher_hstrm-01': 3,
                  'ammunition_rocketlauncher_ubr-100': 1, 'ammunition_rocketlauncher_bdr1212': 5,
                  'ammunition_rocketlauncher_sar-01': 5, 'ammunition_rocketlauncher_sar-02': 5,
                  'ammunition_rocketlauncher_pir-100': 5, 'ammunition_rocketlauncher_cbr': 4,
                  'ammunition_rocketlauncher_obr-100': 0}
TOGGLES = S['on_off']                      # menu item -> extra's property (nisan, oto_roket, oto_fircatici)
ALIEN_CPUS = S['alien_cpu']                  # Chaos Alien CPUs, Cubi Portal -> map classes, spawned types
ALIEN_CPUS.update(json.load(open(os.path.join(HERE, 'data', 'event_gates.json'), encoding='utf8')).get('cpu', {}))   # Bountiful (Gauntlet of Plutus; tools/event_gates.py)
FORMATIONS = _E['formations']               # drone formation menu items: one shared wait between two changes (S['formation'])
TOGGLE_DEFAULT = {'aim': False}             # spends Xenomit: does not turn on by itself; the others are on when fitted
XENOMIT = 3
REPBOT_MENU = 'equipment_extra_repbot_rep'
HM7 = 'equipment_extra_hmd-07'                # trade drone: the shortcut bar icon opens the trade window (world.menu_action)
TIMERS = 'cooldown_groups'                   # in the profile: {group: [end, max ms]}
# fireworks (K6): the client's fireworkDescriptor ids 31-35 (read live from the client's dictionary; any other gives a NullReference in FireWorkInfo.Init),
# order like the client's Ammunition (FIREWORK_1-3, COM, RZ); the firing item has no counter
FIREWORKS = {'ammunition_firework_fwx-s': 31, 'ammunition_firework_fwx-m': 32, 'ammunition_firework_fwx-l': 33,
             'ammunition_firework_fwx-com': 34, 'ammunition_firework_fwx-rz': 35}
IGNITE = 'ammunition_firework_ignite'
# spray (K6): in the client the AssetCreateCommand type is SPRAY (69), designId is lib_assets.xml's spray_<n> pattern (order as there). Cooldown
# group from the client's menu (57); the official Mimesis Mutiny FAQ (2020): "last for 30 seconds and have a 45 second cooldown which
# applies to all sprays". The client adds (+200, +130)
# to the position and puts the image 330 units deep: when the ship's position was sent the image stayed below the screen (live K6), SPRAY_KAYMA
# brings it under the ship
SPRAY_OFFSET = (-200, -400)
SPRAY_PREFIX = 'ammunition_specialammo_spray_'
SPRAYS = ['cross', 'hearts', 'ko', 'like', 'skull', 'eggle', 'space-bunny', 'eggtopia', 'easter-eggs', 'shoot', 'heartbreak',
          'watchingyou', 'strong', 'biohazard', 'healing', 'wash-hands', 'celebrate', 'peace', 'question', 'crown', 'fist-bump',
          'hand-shake', 'batman', 'hand', 'turkeydinner', 'frozen-hand', 'snowflake', 'yeti']
SPRAY_ASSET, SPRAY_GROUP, SPRAY_CD, SPRAY_SEC = 69, 57, 45, 30
SPRAY_SEQ = itertools.count(1)        # spray ids are unique on the server (on a shared map other players' sprays are visible too)
FIREWORK_LIMIT = 5                            # boxes set up at the same time (fandom Fireworks: "You can only put down 5 fireworks"); no
                                              # cooldown (cooldown group 0 in the client's menu)
ROCKET_FLIGHT = _N['combat']['rocket_flight_sec']
ATTACK_MINE = 2                               # the client's AttackType: MINE


def mod(name, **f):
    f['_'] = name
    return f


def attack_type(v):
    return mod('AttackTypeModule', attackTypeValue=v)


def stm(key):
    return legacy('0|A|STM|%s' % key)


# ------------------------------------------------------------ item classes
def ammo_kind(loot):
    """The type of the selected ammo: laser, rocket (special rockets included), fircatici or None (single-use items)."""
    if loot.startswith('ammunition_laser_'):
        return 'laser'
    if loot.startswith('ammunition_rocketlauncher_'):
        return 'launcher'
    if loot.startswith('ammunition_rocket_') or loot in ROCKETS:
        return 'rocket'
    if loot.startswith('ammunition_slug_'):
        return 'slug'                                   # particle cannon (particle.py)
    if loot.startswith('ammunition_spool_'):
        return 'gsp'                                    # Singularity Drive (particle.py)
    return None


def special(rocket):
    return bool(ROCKETS.get(rocket, {}).get('special'))


def item_cooldown(loot):
    """The shortcut item's cooldown group and duration (sec, before multipliers) or None."""
    if loot.startswith(EMOTE_PREFIX):
        return O6['phrases']['cooldown_group'], O6['phrases']['cooldown_sec']
    if loot.startswith(SPRAY_PREFIX):
        return SPRAY_GROUP, SPRAY_CD
    if loot in MINES:
        m = MINES[loot]
        return m.get('cooldown_group', S['mine']['cooldown_group']), m.get('cooldown_sec', S['mine']['cooldown_sec'])
    if loot in ALIEN_CPUS:
        return ALIEN_CPUS[loot]['cooldown_group'], ALIEN_CPUS[loot]['cooldown_sec']
    if loot in FORMATIONS:
        return S['formation']['cooldown_group'], S['formation']['cooldown_sec']
    for key in ('smart_bomb', 'insta_shield', 'emp', 'ghost'):
        if loot == S[key]['menu']:
            return S[key]['cooldown_group'], S[key]['cooldown_sec']
    r = ROCKETS.get(loot, {})
    if r.get('special'):
        return r['cooldown_group'], r['cooldown_sec']
    return None


def mine_based(loot):
    """Mines and things made from mines: the Turbo Mine CPU (MIN-T01/02) shortens the cooldown."""
    return loot in MINES or loot in (S['smart_bomb']['menu'], S['insta_shield']['menu'])


LAUNCHER_COOLDOWN = 3.0           # rocket launcher shot cooldown (sec)
LAUNCHER_FIRST_DELAY = (0.75, 1.9)       # from the salvo to the first rocket's damage (sec)
LAUNCHER_INTERVAL = 2.2            # between the damage of consecutive rockets (sec)


def timer_msg(group, ms, cooling=True):
    return ('MenuItemCooldownGroupTimerCommand', dict(timerState=mod('TimerStateModule', timerStateValue=2 if cooling else 0),
                                                      cooldownType=mod('CooldownTypeModule', typeValue=group), maxTime=ms,
                                                      time=ms if cooling else 0))


def ready_at(p, group):
    return (p.d.get(TIMERS, {}).get(str(group)) or [0, 0])[0]


def timer_fields(p, loot, now=None):
    """The shortcut item's ongoing cooldown at login and on map change (player_profile.patch_template) or None."""
    c = item_cooldown(loot)
    if not c:
        return None
    now = now or time.time()
    until, mx = p.d.get(TIMERS, {}).get(str(c[0])) or [0, 0]
    if until <= now:
        return None
    return dict(activatable=False, timerState=2, maxTime=mx, time=int((until - now) * 1000))


# ------------------------------------------------------------ fitted CPUs
def _first(p, key):
    return next((l for l, v in EX.props(p, key)), None)


def jump_loot(p):
    """The fitted jump CPU: the first with uses left (else the first, for the "no uses" message)."""
    cpus = [l for l, v in EX.props(p, 'jump') if 'right' in EX.X[l]]
    return next((l for l in cpus if EX.uses(p, l) > 0), cpus[0] if cpus else None)


def has_ajp(p):
    return EX.has(p, 'advanced_jump')


def cloak_loot(p):
    """The fitted cloak CPU: the first with uses left (an empty XL no longer blocks a fitted M), else the first."""
    cpus = [l for l, v in EX.props(p, 'cloak')]
    return next((l for l in cpus if EX.uses(p, l) > 0), cpus[0] if cpus else None)


def toggled(p, item):
    key = TOGGLES.get(item)
    if not key or not EX.has(p, key):
        return False
    return p.d.get('cpu_on', {}).get(item, TOGGLE_DEFAULT.get(key, True))


def home_map(p):
    return S['jump_cpu']['main_map'].get(str(p.d['pilot'].get('factionId')), 1)


def jump_allowed(loot, map_id):
    """Whether the CPU works from this map: JP-01 only X-1..X-4; JP-02 and AJP-01 except 5-X, BL and gate maps.
    Every jump CPU works from the Cubikon Graveyard (wiki: the only exit is a jump CPU or death); not from LoW."""
    if int(map_id) == 42:
        return True
    if int(map_id) not in H.NAMES or int(map_id) in H.SPECIAL:
        return False                                  # Galaxy Gate maps, LoW
    cfg = EX.X.get(loot, {}).get('jump', {})
    if 'maps' in cfg:
        return H.map_class(map_id) in cfg['maps']
    return not any(H.name(map_id).startswith(s) for s in cfg.get('ban', []))


def gate_map(map_id):
    """Galaxy Gate map (the gates in the generator): the Smart Bomb cannot be dropped (client ttip_inactive_smb_galaxy_gate "You can't drop
    Smartbombs in a Galaxy Gate!"). The mine's gate rule is contradictory (N.O.V.A. Explosive Firepower A/B/G strengthens the mine)."""
    import galaxy_gates
    return int(map_id) in galaxy_gates.BY_MAP


def launchers(p):
    return [l for l in p.d.get('equipment', {}).get('rocket', []) if l in LAUNCHERS]


def launcher_upgrade(p):
    """The launcher's rocket damage multiplier: upgrade (upgrades.py; the client's ratio). The Plus launcher's roket_bonus is information: the level-20
    total is 1 + level x ratio (official forum 161353: Neptune 28.5%, Triskelion 47.5%); with several launchers the highest."""
    import upgrades as UPG
    eq, lv = p.d.get('equipment', {}).get('rocket', []), p.d.get('equipment_level', {}).get('rocket', [])
    return max([UPG.factor(l, lv[i] if i < len(lv) else 0, UPG.ROCKET) for i, l in enumerate(eq) if l in LAUNCHERS] or [1.0])


def capacity(p):
    return sum(LAUNCHERS[l]['capacity'] for l in launchers(p))


def salvo(attacker, target, hit, cnt, kind):
    """A single HellstormAttackCommand carries the whole salvo. When currentLoad > 1 the client flies
    the rockets on a curved trajectory with its own interval (1.1.115 AttackRocketRun.Run).
    Sending each rocket as currentLoad=1 flattens the Hellstorm trajectory."""
    return ('HellstormAttackCommand', dict(attackerId=attacker, targetId=target, hit=hit, currentLoad=cnt,
                                          rocketType=mod('AmmunitionTypeModule', typeValue=kind)))


def salvo_time(dist, cnt):
    """The last rocket's arrival on the client (sec): AttackRocketRun.Run starts the rocket i*0.5/count later;
    InitRocketCurve makes the flight max(1, distance/500) + (0.3 if curved) sec."""
    return max(1.0, dist / 500.0) + (0.3 + (cnt - 1) * 0.5 / cnt if cnt > 1 else 0.0)


def launcher_type(p):
    return max((LAUNCHERS[l]['type'] for l in launchers(p)), default=0)


def loaded(p):
    """The rockets in the launcher: [ammo, count]."""
    return p.d.get('launcher_loaded') or [None, 0]


def mine_uses(p, cfg):
    """Smart Bomb / Insta-Shield: how many times with the mines and Xenomit at hand."""
    return min(p.ammo(cfg['mine']) // cfg['mine_count'], p.ore_count(XENOMIT) // cfg['xenomit'])


# ------------------------------------------------------------ shortcut bar state (player_profile.menu_status)
def _line(key, reps=(), ktype=5):
    return {'_': 'MessageKeyListWildcardModule', 'baseKey': key, 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': ktype},
            'textStyle': 0, 'wildCardReplacements': [
                {'_': 'MessageWildcardReplacementModule', 'wildcard': w, 'replacement': str(r),
                 'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': t}} for w, r, t in reps]}


def _tips(st, lines):
    for k in ('toolTipSlotBar', 'toolTipItemBar'):
        st[k] = {'_': 'MessageKeyListWildcardCommand', 'commandList': json.loads(json.dumps(lines))}


def _explosive(st, loot, n):
    _tips(st, [_line('ttip_explosive', [('%TYPE%', loot, 1)]), _line('ttip_count', [('%COUNT%', n, 0)]), _line(loot, ktype=7)])


def menu_status(p, menu_id, st):
    """The state of this module's items (st: a copy of the template in the save) or None (another item)."""
    start_map = H.map_class(p.d['position'].get('mapId', 0)) == 'X-1'
    if menu_id in PLAYER_MINES:
        n = p.ammo(menu_id)
        st.update(counterValue=n, counterStyle=4 if n > 0 else 1, visible=st.get('visible') or n > 0, available=n > 0 and not start_map,
                  activatable=n > 0 and not start_map)
        if not start_map:                      # save (start map): ttip_inactive_mine_start_map
            _explosive(st, menu_id, n)
        return st
    if menu_id in (S['smart_bomb']['menu'], S['insta_shield']['menu']):
        smb = menu_id == S['smart_bomb']['menu']
        cfg = S['smart_bomb' if smb else 'insta_shield']
        owned = EX.has(p, 'smart_bomb' if smb else 'insta_shield')
        n = mine_uses(p, cfg) if owned else 0
        in_gate = smb and gate_map(p.d['position'].get('mapId', 0))
        blocked = smb and (start_map or in_gate)   # save: ttip_inactive_smb_start_map
        st.update(visible=owned, counterValue=n, available=owned and n > 0 and not blocked, activatable=owned and n > 0 and not blocked)
        if owned and not blocked:
            _explosive(st, menu_id, n)
        elif owned and in_gate:
            _tips(st, [_line('ttip_inactive_smb_galaxy_gate')])
        return st
    if menu_id == S['jump_cpu']['menu']:
        loot = jump_loot(p)
        if not loot:
            st.update(visible=False, available=False, activatable=False, counterValue=0)
            return st
        n = EX.uses(p, loot)
        here = p.d['position'].get('mapId', 0)
        if here == home_map(p):
            lines, ok = [_line('ttip_inactive_jump_already_on_map')], False       # save
        elif not jump_allowed(loot, here):
            lines, ok = [_line('ttip_inactive_jump_map_range_exceeded')], False
        else:
            lines = [_line('ttip_jump_cpu', [('%TYPE%', loot, 1)]), _line('ttip_cpu_jump_count', [('%COUNT%', n, 0)]),
                     _line('ttip_cpu_jump_desc')]
            ok = n > 0
        _tips(st, lines)
        st.update(visible=True, available=True, activatable=ok, counterValue=n, iconLootId=loot)
        return st
    if menu_id == S['advanced_jump']['menu']:
        owned = has_ajp(p)
        st.update(visible=owned, available=owned, activatable=owned)
        if owned:
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == S['cloak_cpu']['menu']:
        loot = cloak_loot(p)
        if not loot:
            st.update(visible=False, available=False, activatable=False, selected=False, counterValue=0)
            return st
        n = EX.uses(p, loot)
        on = bool(p.d.get('cpu_hidden'))
        _tips(st, [_line('ttip_cloak_cpu', [('%TYPE%', loot, 1)]), _line('ttip_cpu_cloak_count', [('%COUNT%', n, 0)])])
        st.update(visible=True, available=True, activatable=n > 0 and not on, selected=on, counterValue=n, iconLootId=loot)
        return st
    if menu_id == HM7:                             # usable if in the inventory/fitted and it has uses (official game: on the bar once bought, no need to fit)
        owned = EX.owned(p, HM7)
        ok = owned and EX.uses(p, HM7) > 0
        st.update(visible=owned, available=ok, activatable=ok)
        if owned and not EX.unlimited(p, HM7):         # remaining sale uses: at the icon's bottom left (official game)
            n = EX.uses(p, HM7)
            st.update(counterValue=n, counterStyle=4 if n > 0 else 1)
        if owned:
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == REPBOT_MENU:                     # repair robot: the template is always REP-2; by the fitted robot, disabled if none is fitted
        loot = next((e for e in EX.equipped(p) if e in _E['repair_robots']), None)
        if loot:
            _tips(st, [_line('ttip_robot_cpu', [('%TYPE%', loot, 1)])])
            st.update(visible=True, available=True, activatable=True, iconLootId=loot)
        else:
            _tips(st, [_line('ttip_cpu_not_equipped')])
            st.update(visible=True, available=False, activatable=False, selected=False)
        return st
    if menu_id in TOGGLES:
        key = TOGGLES[menu_id]
        loot = _first(p, key)
        st.update(visible=bool(loot), available=bool(loot), activatable=bool(loot), selected=toggled(p, menu_id))
        if loot:
            if menu_id == S['aim_cpu']['menu']:
                _tips(st, [_line('ttip_aim_cpu_category'), _line(loot, ktype=7)])
                n = p.ore_count(XENOMIT) // S['aim_cpu']['xenomit']      # remaining salvo (player report 2026-10-27: it showed 0)
                st.update(iconLootId=loot, counterValue=n, counterStyle=4 if n > 0 else 1)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == S['launcher']['menu']:
        lns = launchers(p)
        if not lns:
            return st                           # the "no launcher" state in the save
        ammo, n = loaded(p)
        cap = capacity(p)
        sel = p.d.get('selected', {}).get('launcher')
        # the number of loaded rockets in an empty launcher too (0): the text of the no-launcher calculation ttip_rocketlauncher_unloaded "Attention: No launcher installed"
        # (save); it also went out with a fitted but empty launcher (user report 2026-10-25: "Hellstorm takılı ama
        # kurulmamış diyor")
        lines = [_line('ttip_rocketlauncher', [('%TYPE%', menu_id, 5)])]          # save: the item's name (type 5), not the launcher's
        rocket = ammo if n else sel
        if rocket:
            lines.append(_line('ttip_rocketlauncher_loadcount', [('%COUNT%', n, 0), ('%TYPE%', rocket, 1)]))
        _tips(st, lines)
        # save: icon and dot color of the loaded (otherwise selected) ammo; the launcher's name and default style showed every rocket as red
        st.update(visible=True, available=n > 0, activatable=n > 0, counterValue=n, maxCounterValue=cap,
                  iconLootId=rocket or lns[0], counterStyle=LAUNCHER_COLOR.get(rocket, 1), selected=False)
        if sel is None:
            st['available'] = st['activatable'] = False
        return st
    return None


# ------------------------------------------------------------ advanced jump (AJP-01) list
def ajp_price(p, dest, here=None):
    """The cost of an AJP-01 jump without a coupon: by source and target map (forum 127075 table, same as the real save); 0 with a coupon."""
    c = S['advanced_jump']
    if p.resource(c['voucher']):
        return 0
    src = H.name(here if here is not None else p.d['position'].get('mapId', 0))
    return c.get('price_table', {}).get(src, {}).get(H.name(dest), c['price'])


def ajp_locked(p, m):
    """The target's level is not enough or it is an enemy company's X-1 (forum 127075: locked regardless of level)."""
    fac = p.d['pilot'].get('factionId')
    homes = S['jump_cpu']['main_map']
    return (m in homes.values() and m != homes.get(str(fac))) or p.d['pilot'].get('level', 1) < H.level_required(m, fac)


def random_maps(p, here):
    """Random jump targets (the wormhole of 4-5): the selectable maps of the AJP-01 list, excluding the level and enemy X-1 locks."""
    return [m for m in sorted(H.NAMES) if m != here and m not in H.SPECIAL and not ajp_locked(p, m)
            and not any(H.name(m).startswith(s) for s in ('5-', 'BL-'))]


def jcpu_list(p):
    """0|A|JCPU|I|key|map;…;|… : -1 locked (level or enemy X-1), -2 not enough uridium, price: selectable."""
    here = p.d['position'].get('mapId', 0)
    groups = {-1: [], -2: []}
    for m in sorted(H.NAMES):
        if m == here or m in H.SPECIAL or any(H.name(m).startswith(s) for s in ('5-', 'BL-')):
            continue
        price = ajp_price(p, m, here)
        if ajp_locked(p, m):
            groups[-1].append(m)
        elif price and p.d['pilot'].get('uridium', 0) < price:
            groups[-2].append(m)
        else:
            groups.setdefault(price, []).append(m)
    parts = ['0', 'A', 'JCPU', 'I']
    for k, maps in groups.items():
        if maps:
            parts += [str(k), ''.join('%d;' % m for m in maps)]
    return legacy('|'.join(parts))


def vouchers_msg(p):
    return legacy('0|A|JV|%d' % p.resource(S['advanced_jump']['voucher']))


# ------------------------------------------------------------ items in the world
class Items:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.mine_visuals = {}     # type -> the last end sent to the client; profile reads may drop effects early
        self.mines = {}            # hash -> {loot, x, y, owner, armed_at, end_time}
        self.fireworks = []        # hashes of the set-up firework boxes (the client removes them when fired)
        self.seq = 0
        self.jump = None           # CPU jump: {target, time, cpu, start}
        self.ajp_target = None     # the map chosen in the advanced jump
        self.next_load = 0.0       # the launcher's next load
        self.launcher_cd = 0.0     # the launcher's fire cooldown (official recording: 3 s after every shot, MenuItemTimerCommand)
        self.next_lure = 0.0
        self.waiting = {}          # group -> end: a READY notice when it ends
        self.ghost_end = 0.0       # end of the Ghostifier look
        self.serum_next = 0.0      # the Serum CPU is ready for the next cure
        self.next_dep = 0.0        # check of the Smart Bomb / Insta-Shield counter (dependent_tick)
        self.aim_warned = False    # the aim CPU's Xenomit warning went away (again when Xenomit arrives)
        self.born = time.time()    # this map load (login, jump, portal): the jump CPU after 10 s (jump_cpu_failed_time)
        now = time.time()
        for g, (until, mx) in self.p.d.get(TIMERS, {}).items():
            if until > now:
                self.waiting[int(g)] = until

    # ------------------------------------------------------------ helpers
    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def log(self, s):
        self.w.log(s)

    def status(self, *loots):
        out = [st for st in (self.p.menu_status(l) for l in loots) if st]
        for st in out:
            self.p.menu_mark(st)
        return [('MenuItemStatusCommand', st) for st in out]

    def dependent_tick(self, now):
        """The Smart Bomb and Insta-Shield counter depends on ACM-01 and Xenomit: these can change from anywhere (shop, collecting,
        selling, fitting/removing). When the state changes the client is notified (live test H20: after buying a mine the counter stayed at 0)."""
        if now < self.next_dep:
            return
        self.next_dep = now + 1.0
        self.send(self.p.menu_changes([S['smart_bomb']['menu'], S['insta_shield']['menu'], S['aim_cpu']['menu']]))

    def start_map(self):
        return H.map_class(self.w.map_id) == 'X-1'

    def ready(self, group, now):
        return now >= ready_at(self.p, group)

    def cooldown(self, loot, now):
        """Start the item's cooldown group -> timer message. The Turbo Mine CPU and the formation/design multipliers are here."""
        group, sec = item_cooldown(loot)
        if mine_based(loot):
            sec *= EX.mine_factor(self.p) * max(0.0, 1 + self.p.mods().get('mine_cooldown', 0))
        sec *= SET.multiplier('skill_cooldown', 'item')                    # panel: ability and item cooldowns
        ms = int(sec * 1000)
        with self.p.lock:
            self.p.d.setdefault(TIMERS, {})[str(group)] = [now + sec, ms]
            self.p.dirty = True
        self.waiting[group] = now + sec
        return timer_msg(group, ms)

    def ore_msgs(self):
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.d['ores']})]
        if self.w.ore_pack:
            msgs.append(self.w.ore_pack([XENOMIT]))
        return msgs

    def pay_mines(self, cfg):
        """Cost of Smart Bomb / Insta-Shield: 10 ACM-01 + 100 Xenomit -> messages, or None (not enough)."""
        p = self.p
        if mine_uses(p, cfg) < 1:
            return None
        p.use_ammo(cfg['mine'], cfg['mine_count'])
        p.remove_ores({XENOMIT: cfg['xenomit']})
        return self.w.ammo_msgs(cfg['mine']) + self.ore_msgs()

    def tick(self, now):
        for g, until in list(self.waiting.items()):
            if now >= until:
                del self.waiting[g]
                mx = (self.p.d.get(TIMERS, {}).get(str(g)) or [0, 0])[1]
                self.send([timer_msg(g, mx, cooling=False)])
        self.mine_tick(now)
        self.dependent_tick(now)
        self.lure_tick(now)
        self.jump_tick(now)
        self.launcher_tick(now)
        if self.ghost_end and now >= self.ghost_end:
            self.ghost_end = 0.0
            self.send([self.ghost_msg(False)])

    # ------------------------------------------------------------ shortcut bar (world.menu_action)
    def menu(self, item, now=None):
        """Single-use and toggle items -> True: this module's item (for toggle items the client sends actionType 0)."""
        now = now or time.time()
        if item in PLAYER_MINES:
            self.place_mine(item, now)
        elif item in FIREWORKS:
            self.place_firework(item, now)
        elif item == IGNITE:
            self.ignite()
        elif item.startswith(SPRAY_PREFIX):
            self.spray(item, now)
        elif item == S['smart_bomb']['menu']:
            self.smart_bomb(now)
        elif item == S['insta_shield']['menu']:
            self.insta_shield(now)
        elif item == S['emp']['menu']:
            self.emp(now)
        elif item == S['jump_cpu']['menu']:
            self.jump_cpu(now)
        elif item == S['advanced_jump']['menu']:
            it = self.p.window_item('spacemap')       # the target space map is chosen from the jump panel: the click opens the map
            if it:
                self.send([('WindowItemCommand', dict(it, maximized=True))])
        elif item == S['cloak_cpu']['menu']:
            self.cloak(now)
        elif item in TOGGLES:
            self.toggle(item)
        elif item == S['launcher']['menu']:
            self.launcher_fire(now)
        elif item in ALIEN_CPUS:
            self.alien_cpu(item, now)
        elif item == S['ghost']['menu']:
            self.ghostify(now)
        else:
            return False
        return True

    def toggle(self, item):
        if not EX.has(self.p, TOGGLES[item]):
            return
        on = not toggled(self.p, item)
        with self.p.lock:
            self.p.d.setdefault('cpu_on', {})[item] = on
            self.p.dirty = True
        self.send(self.status(item))
        self.log('   %s %s' % (item, 'on' if on else 'off'))

    # ------------------------------------------------------------ mines
    def mine_worlds(self):
        """Players on the same map; visibility/cloaking does not change mine triggering."""
        w = self.w
        return [w] + [other for other in (w.shared.members if w.shared else [])
                      if other is not w and other.running]

    def mine_snapshot(self, now=None):
        """The existing mines for a loading client; shared player mines and only its own alien mines."""
        now = time.time() if now is None else now
        out, seen = [], set()
        for other in self.mine_worlds():
            if str(other.map_id) != str(self.w.map_id):
                continue
            for h, mine in other.items.mines.items():
                player = mine['owner'] == other.hid
                if h in seen or mine['end_time'] <= now or (other is not self.w and not player):
                    continue
                seen.add(h)
                out.append(('AddMineCommand', dict(hash=h, x=int(mine['x']), y=int(mine['y']),
                                                   typeId=MINES[mine['loot']]['tip'],
                                                   maxSkill1=mine.get('maxSkill1', player and SKL.maxed(other.p, '1')),
                                                   maxSkill5b=mine.get('maxSkill5b', player and SKL.maxed(other.p, '5b')))))
        return out

    def place_mine(self, loot, now):
        w, p, M = self.w, self.p, S['mine']
        cfg = MINES[loot]
        group = item_cooldown(loot)[0]
        if w.hero_dead or w.jumping or self.start_map() or p.ammo(loot) <= 0 or not self.ready(group, now):
            self.log('   mine not placed: %s' % loot)
            return
        x, y = w.hero_pos(now)
        if w.in_pvp_peace(x, y):
            self.log('   mine not placed: safe zone')
            return
        mines = [m for other in self.mine_worlds() for m in other.items.mines.values() if m['end_time'] > now]
        if any(m['loot'] == loot and math.hypot(m['x'] - x, m['y'] - y) < M['stack_distance'] for m in mines):
            self.send([stm('msg_no_mine_stacking')])
            return
        if sum(1 for m in mines if not m.get('area')) >= M['map_limit']:      # 5-1/5-3 minefield mines do not count
            self.send([stm('msg_map_too_many_mine')])
            return
        p.use_ammo(loot, 1)
        self.seq += 1
        h = 'M%d_%d' % (w.hid, self.seq)
        self.mines[h] = dict(loot=loot, x=x, y=y, owner=w.hid, armed_at=now + cfg.get('arm_sec', M['arm_sec']),   # SLM-01 1 sn
                             end_time=now + cfg.get('lifetime_sec', M['lifetime_sec']),
                             damage=max(0.0, 1 + p.mods().get('mine', 0) + p.mods().get('mine_lance', 0)),     # Lance only to mines
                             radius=M['explosion'] * max(0.0, 1 + p.mods().get('mine_radius', 0)),
                             maxSkill1=SKL.maxed(p, '1'), maxSkill5b=SKL.maxed(p, '5b'))
        p.ach('shot', weapon='MINE')
        # the mine's visual: at the last level of Explosives (1) and Detonation II (5b) (official FAQ: "mine visuals")
        self.send(w.ammo_msgs(loot) + [('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=cfg['tip'],
                                                               maxSkill1=self.mines[h]['maxSkill1'], maxSkill5b=self.mines[h]['maxSkill5b'])),
                                       self.cooldown(loot, now)])
        self.log('   mine: %s (%d, %d)' % (loot, x, y))

    def place_firework(self, loot, now):
        """A firework box in the ship's place (AddFireworkBoxCommand: typeId is the fireworkDescriptor id; each digit of colourCode is
        the color 1-3 of a stage; eventModifier empty -> the client's 'standard' class). The firing item fires them all at once."""
        w, p = self.w, self.p
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or len(self.fireworks) >= FIREWORK_LIMIT:
            self.log('   firework not placed: %s' % loot)
            return
        x, y = w.hero_pos(now)
        p.use_ammo(loot, 1)
        self.seq += 1
        h = 'F%d_%d' % (w.hid, self.seq)
        self.fireworks.append(h)
        colour = int(''.join(random.choice('123') for _ in range(3)))
        self.send(w.ammo_msgs(loot) + [('AddFireworkBoxCommand', dict(hash=h, x=int(x), y=int(y), colourCode=colour,
                                                                       typeId=FIREWORKS[loot], eventModifier=''))])
        self.log('   firework: %s (%d, %d)' % (loot, x, y))

    def ignite(self):
        """All the set-up boxes (0|n|FWG|hash|…: from the 3rd part on the client fires and removes each box)."""
        if not self.fireworks:
            return
        dmg, self.fireworks = self.fireworks, []
        self.send([legacy('0|n|FWG|%s' % '|'.join(dmg))])
        self.log('   fireworks fired: %d' % len(dmg))

    def spray(self, loot, now):
        """A spray in the ship's place (the client draws the pattern's image on the ground), removed after SPRAY_SN."""
        w, p = self.w, self.p
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(SPRAY_GROUP, now):
            return
        p.use_ammo(loot, 1)
        x, y = w.hero_pos(now)
        uid, kind = 970000 + next(SPRAY_SEQ), {'_': 'AssetTypeModule', 'typeValue': SPRAY_ASSET}
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now), (
            'AssetCreateCommand', dict(designId=SPRAYS.index(loot[len(SPRAY_PREFIX):]), clanId=0, showBubble=False, userName='',
                                       assetId=uid, expansionStage=0, modifier=[], type=kind, detectedByWarnRadar=False,
                                       invisible=False, posX=int(x) + SPRAY_OFFSET[0], posY=int(y) + SPRAY_OFFSET[1],
                                       clanRelation={'_': 'ClanRelationModule', 'type': 0},
                                       clanTag='', factionId=0, visibleOnWarnRadar=False))])
        w.later(SPRAY_SEC, lambda: self.send([('AssetRemoveCommand', {'assetType': kind, 'uid': uid})]))
        self.log('   sprey: %s (%d, %d)' % (loot, x, y))

    def alien_mine(self, loot, x, y, owner, now):
        """An alien's mine (Curcubitor's Trick, Agatus): if a player is nearby it explodes when set up (mine_tick)."""
        M = S['mine']
        self.seq += 1
        h = 'U%d_%d' % (owner, self.seq)
        self.mines[h] = dict(loot=loot, x=x, y=y, owner=owner, armed_at=now + MINES[loot].get('arm_sec', M['arm_sec']),
                             end_time=now + MINES[loot].get('lifetime_sec', M['lifetime_sec']))
        self.send([('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=MINES[loot]['tip'], maxSkill1=False, maxSkill5b=False))])

    def field_mine(self, x, y, now):
        """A mine in the map's minefield (5-1, 5-3; map_layout.json): set up, endless, ownerless (explodes with the player like an alien mine;
        mine_tick). When it explodes a new one in its field (explode). -> AddMineCommand"""
        loot = ML.MINE['type']
        self.seq += 1
        h = 'A%d' % self.seq
        self.mines[h] = dict(loot=loot, x=x, y=y, owner=0, armed_at=now, end_time=float('inf'), area=True)
        return ('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=MINES[loot]['tip'], maxSkill1=False, maxSkill5b=False))

    def mine_msgs(self):
        """When the map reloads (respawn) the standing mines again."""
        return [('AddMineCommand', dict(hash=h, x=int(m['x']), y=int(m['y']), typeId=MINES[m['loot']]['tip'], maxSkill1=False,
                                        maxSkill5b=False)) for h, m in self.mines.items()]

    def serum_cure(self):
        """Serum CPU (ANTI-Z1 1 dose, XL 10 doses; client: "automatically cure you of any infections"): if fitted and it has doses, it cures a spreading
        infection by itself, one dose is spent; the next cure after 60 s (wiki cooldown). -> True if cured"""
        now = time.time()
        loot = next((l for l, _ in EX.props(self.p, 'serum') if EX.uses(self.p, l) > 0), None)
        if not loot or now < self.serum_next:
            return False
        self.serum_next = now + EX.X[loot]['cooldown_sec']
        self.log('   Serum CPU cured the infection (%s, %d left)' % (loot, EX.use(self.p, loot)))
        return True

    def mine_effect_msgs(self, now=None, replay=False, remember=True):
        """The mine's lasting visual on the ship: PLAGUE (57), SL-M01's slow-effect (also in aliens' slowing shot: Saboteur, Uber
        Protegit …); an explosion does not start these by itself."""
        now = time.time() if now is None else now
        w, msgs = self.w, []
        for kind in ('infection', 'slow'):
            effects = [] if w.hero_dead else w.hero_effects.get(kind, now)
            effects = [e for e in effects if kind == 'infection' or e.get('source') in MINES]
            if kind == 'slow' and not w.hero_dead:
                effects += [e for e in w.hero_effects.get('slow', now) + w.hero_effects.get('speed_limit', now)
                            if str(e.get('source')).startswith('slow_')]
            until = max((e['end_time'] for e in effects), default=0)
            previous = self.mine_visuals.get(kind, 0)
            def message(on):
                if kind == 'infection':
                    return ('VisualModifierCommand', dict(userId=w.hid, modifier=57, attribute=0,
                                                           additionalAttribute=str(max(0, math.ceil(until - now))) if on else '',
                                                           count=0, activated=on))
                return legacy('0|n|fx|%s|SABOTEUR_DEBUFF|%d' % ('start' if on else 'end', w.hid))
            if previous and not replay and previous != until:
                msgs.append(message(False))     # remove the old particle/timer of the renewed infection
            if until and (replay or previous != until):
                msgs.append(message(True))
            if remember:                       # another client's new ship look does not change the local end tracking
                if until:
                    self.mine_visuals[kind] = until
                else:
                    self.mine_visuals.pop(kind, None)
        return msgs

    def mine_tick(self, now):
        if not self.mines:
            return
        w, M = self.w, S['mine']
        hx, hy = w.hero_pos(now)
        for h, m in list(self.mines.items()):
            if h not in self.mines:
                continue
            if now >= m['end_time']:
                del self.mines[h]
                self.send([('RemoveMineCommand', {'hash': h})])
                continue
            if now < m['armed_at'] or 'bait' in MINES[m['loot']]:
                continue
            players = self.mine_worlds() if m['owner'] == w.hid else [w]
            hit = any(not other.hero_dead and not other.jumping
                      and (other.hid != m['owner'] or (M.get('self_damage') and SET.get('own_mine')))
                      and math.hypot(*(a - b for a, b in zip(other.hero_pos(now), (m['x'], m['y'])))) <= M['trigger']
                      and not (other.in_pvp_peace(*other.hero_pos(now)) and not other.hero_fighting(now))     # a fighting pilot has no DMZ
                      and not other.tech.mine_protected(now) for other in players)
            if not hit and m['owner'] == w.hid and M.get('npc_adaptation', False):
                hit = any(n.alive and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (m['x'], m['y'])))) <= M['trigger']
                          for n in w.npcs.values())       # local PvE adaptation; in the official game it does not trigger NPCs
            if hit:
                self.explode(h, now)

    def explode(self, h, now):
        m = self.mines.pop(h, None)
        if m is None:
            return
        self.send([legacy('0|n|MIN|%s' % h)])
        self.log('   mine exploded: %s' % m['loot'])
        self.blast(m['x'], m['y'], m.get('radius', S['mine']['explosion']), MINES[m['loot']], m['owner'], now, m['loot'],
                   factor=m.get('damage'), self_hit=S['mine'].get('self_damage', False) and SET.get('own_mine'))       # panel: your own mine
        if m.get('area'):                     # minefield: a new one in the same field a little later
            rect = ML.mine_field_of(self.w.map_id, m['x'], m['y'])

            def again():
                p = rect and ML.free_spot(self.w.map_id, rect, pad=100)
                if p:
                    self.send([self.field_mine(p[0], p[1], time.time())])
            self.w.later(random.uniform(*ML.MINE['renew_sec']), again)

    def blast(self, x, y, radius, cfg, owner, now, source, self_hit=False, factor=None):
        """Explosion: the mine effect on aliens in the radius (if the owner is the player) and on the player (if it is the alien's mine or self_hit)."""
        w = self.w
        m = self.p.mods()
        f = factor if factor is not None else max(0.0, 1 + m.get('mine', 0) + m.get('mine_lance', 0)) if owner == w.hid else 1.0
        if source in MINES:                   # official FAQ: mines affect ships; not aliens
            if 'bait' in cfg:
                return
            if owner == w.hid and S['mine'].get('npc_adaptation', False):
                for n in list(w.npcs.values()):
                    if n.alive and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (x, y)))) <= radius:
                        self.mine_npc(n, cfg, f, now, source)
            for other in self.mine_worlds() if owner == w.hid else [w]:
                if other.hero_dead or other.jumping or (other.hid == owner and not self_hit):
                    continue
                hx, hy = other.hero_pos(now)
                if not (other.in_pvp_peace(hx, hy) and not other.hero_fighting(now)) and math.hypot(hx - x, hy - y) <= radius:
                    other.items.mine_hero(cfg, f, owner, now, source)
            return
        f = max(0.0, 1 + m.get('mine', 0)) if owner == w.hid else 1.0      # Turtle -7.5%, Detonation I/II; not Lance (forum 127433)
        if owner == w.hid:
            radius *= 1 + m.get('mine_radius', 0)                         # Explosives
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - x, ny - y) <= radius:
                    self.mine_npc(n, cfg, f, now, source)
        if owner != w.hid or self_hit:
            hx, hy = w.hero_pos(now)
            if math.hypot(hx - x, hy - y) <= radius:
                self.mine_hero(cfg, f, owner, now, source)

    def mine_npc(self, n, cfg, f, now, source):
        w = self.w
        sh = min(n.shield, n.d['shield'] * cfg.get('shield', 0) * f)       # SAB-M01 50% x (Lance + Detonation) at most 100% (wiki)
        hp = n.d['hp'] * cfg.get('hp', 0) * f
        if cfg.get('damage_type') == 'standard':
            sh = min(n.shield, int(hp * n.d.get('shield_absorb', _N['combat']['npc_shield_absorb'])))
            hp = min(max(0, n.hp - 1), hp - sh)
        if sh or hp:
            w.hit_npc(n.id, 0, ATTACK_MINE, split=(int(sh), int(hp)), reactive=True)       # laid earlier: not an attack (world.attacked)
        if not n.alive:
            return
        if 'slow' in cfg:
            w.npc_effect(n, 'slow', cfg['slow'][1], cfg['slow'][0], source=source)
        inf = cfg.get('infection')
        if inf:
            w.npc_effect(n, 'slow', inf['sec'], inf['slow'], source=source)
            w.npc_effect(n, 'damage_bonus', inf['sec'], inf['damage_bonus'], source=source)
        if not sh and not hp and not n.engaged and ('slow' in cfg or inf):
            n.engaged = True                   # the slowed alien turns on the attacker

    def mine_hero(self, cfg, f, owner, now, source):
        w, p = self.w, self.p
        g = p.d['ship']
        if w.hero_dead:
            return
        npc_owner = w.npcs.get(owner)
        place = 'wave' if getattr(npc_owner, 'hunt', False) else 'map'
        k = SET.multiplier('npc_damage', place) if npc_owner else 1.0
        shield, hull = g.get('shield', 0), g.get('hitPoints', 0)
        sh = min(shield, int(g.get('shieldMax', 0) * cfg.get('shield', 0) * f * k))
        hp = int(g.get('hitMax', 0) * cfg.get('hp', 0) * f * k)
        if cfg.get('damage_type') == 'standard':
            sh = min(shield, int(hp * p.d.get('shield_absorb', 0.8)))
            hp = min(max(0, hull - 1), hp - sh)          # ACM/IM alone does not destroy a ship
        elif cfg.get('damage_type') == 'direct':
            base = p.ship_row().get('hp', g.get('hitMax', 0)) + SKL.mods(p).get('hp_flat', 0)
            hp = int(base * cfg.get('hp', 0) * f * k)   # DD-M01: base hull + Pilot Bio
        if w.hero_effects.invulnerable(now) or w.invulnerable:
            sh = hp = 0
        if cfg.get('emp'):
            w.abilities.reveal()
            self.reveal('msg_uncloaked')
        if 'slow' in cfg:
            w.hero_effect('slow', cfg['slow'][1], cfg['slow'][0], source=source)
        infection = cfg.get('infection')
        if not sh and not hp:
            if infection:
                w.hero_effect('infection', infection['sec'], source=source)
            return
        w.last_combat = w.last_hurt = now
        w.stop_repair()
        new = hull - hp
        if npc_owner:
            new = max(new, w.tech.hp_floor(now))
        hp = hull - max(0, new)
        p.set_hull(hp=max(0, new), shield=shield - sh)
        msgs = [('AttackHitCommand', dict(attackType=attack_type(ATTACK_MINE), attackerId=owner, victimId=w.hid,
                                          victimHitpoints=int(g['hitPoints']), victimShield=int(g.get('shield', 0)),
                                          victimNanoHull=int(g.get('nanoHull', 0)), damage=int(sh + hp), skilled=False, strike=False,
                                          cannonType=0))]
        self.log('   mine hit the player: %d' % (sh + hp))
        if g['hitPoints'] <= 0:
            w.hero_death(msgs, npc_owner, note='killed_by_mine')
        self.send(msgs)
        if infection and not w.hero_dead:
            w.hero_effect('infection', infection['sec'], source=source)  # first the ACM damage, then the hull capacity change

    def lure_tick(self, now):
        """AGL-M01: Agatus and Spinels come to the bait (when not attacking)."""
        if now < self.next_lure:
            return
        self.next_lure = now + 2.0
        baits = [m for other in self.mine_worlds() for m in other.items.mines.values()
                 if 'bait' in MINES[m['loot']] and m['armed_at'] <= now < m['end_time']]
        if not baits:
            return
        w = self.w
        for n in w.npcs.values():
            if not n.alive or n.engaged or n.d['speed'] <= 0:
                continue
            nx, ny = n.mover.pos(now)
            names = [b for b in baits if any(k in n.d['name'] for k in MINES[b['loot']]['bait'])
                     and math.hypot(b['x'] - nx, b['y'] - ny) <= MINES[b['loot']]['radius']]
            if not names:
                continue
            nx, ny = n.mover.pos(now)
            b = min(names, key=lambda b: math.hypot(b['x'] - nx, b['y'] - ny))
            if math.hypot(b['x'] - nx, b['y'] - ny) < 100:
                continue
            ms = n.mover.go(b['x'], b['y'], n.d['speed'] * n.effect.speed_factor(now), now)
            n.next_think = now + ms / 1000.0
            if n.id in w.visible:
                self.send([('MoveCommand', dict(userId=n.id, x=int(b['x']), y=int(b['y']), timeToTarget=ms))])

    # ------------------------------------------------------------ Smart Bomb, Insta-Shield, EMP
    def smart_bomb(self, now):
        w, c = self.w, S['smart_bomb']
        if (not EX.has(self.p, 'smart_bomb') or self.start_map() or gate_map(w.map_id) or w.hero_dead or w.jumping
                or not self.ready(c['cooldown_group'], now)):
            return
        paid = self.pay_mines(c)
        if paid is None:
            self.log('   Smart Bomb: not enough mines or Xenomit')
            return
        x, y = w.hero_pos(now)
        self.send([legacy('0|n|SMB|%d' % w.hid)])
        self.blast(x, y, c['radius'], c, w.hid, now, c['menu'], self_hit=False)      # does not damage its own ship (wiki)
        self.send(paid + [self.cooldown(c['menu'], now)] + self.status(c['menu'], S['insta_shield']['menu']))
        self.p.ach('shot', weapon='MINE')
        self.log('   Smart Bomb exploded')

    def insta_shield(self, now):
        w, c = self.w, S['insta_shield']
        if not EX.has(self.p, 'insta_shield') or w.hero_dead or not self.ready(c['cooldown_group'], now):
            return
        paid = self.pay_mines(c)
        if paid is None:
            self.log('   Insta-Shield: not enough mines or Xenomit')
            return
        w.hero_effect('immune_until', c['duration_sec'], source=c['menu'])
        self.send([legacy('0|n|ISH|%d' % w.hid)] + paid + [self.cooldown(c['menu'], now)]
                  + self.status(c['menu'], S['smart_bomb']['menu']))
        self.log('   Insta-Shield: %d s no damage' % c['duration_sec'])

    def emp(self, now):
        w, p, c = self.w, self.p, S['emp']
        loot = c['menu']
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(c['cooldown_group'], now):
            return
        hx, hy = w.hero_pos(now)
        if w.in_pvp_peace(hx, hy):          # not used around a station and portal, like a mine (player report 2026-10-28, real game)
            self.log('   EMP not used: safe zone')
            return
        p.use_ammo(loot, 1)
        msgs = [legacy('0|n|EMP|%d' % w.hid)]
        reset = 0
        for n in w.npcs.values():
            # every alien that targeted the player loses its lock, regardless of distance (player report 2026-10-28: those firing from afar
            # were not affected); the radius is for other players' P.E.T.s (below)
            if n.alive and n.engaged and w.ours(n):
                n.engaged = False                                   # its target is reset
                n.next_shot = max(getattr(n, 'next_shot', 0), now + c['daze_sec'])
                n.blocked = max(getattr(n, 'blocked', 0), now + c['daze_sec'])     # so the attacking type does not lock again at once
                reset += 1
        w.alien.hero_dots = [d_ for d_ in w.alien.hero_dots if not d_.get('emp')]     # forum 127094: EMP removes the Reflector's radiation
        if w.hero_effects.get('slow') or w.hero_effects.get('speed_limit'):
            w.hero_effects.remove('slow')                             # EMP removes slowdowns (aliens.md: Slowdown Orb)
            w.hero_effects.remove('speed_limit')
            msgs += self.mine_effect_msgs(now) + w.effect_stats_msgs(now)
        for other in self.mine_worlds()[1:]:          # forum 127074: a (another player's) P.E.T. in EMP range becomes inactive
            pet = getattr(other, 'pet', None)
            if pet and pet.active and math.hypot(*(a - b for a, b in zip(pet.pos(now), (hx, hy)))) <= c['radius']:
                pet.disrupt(now)
        self.send(msgs + w.ammo_msgs(loot) + [self.cooldown(loot, now)])
        self.log('   EMP: %d aliens had their target reset' % reset)

    # ------------------------------------------------------------ Chaos Alien CPUs, Cubi Portal, Ghostifier
    def alien_cpu(self, loot, now):
        """If the map is suitable (X-3..X-7 class or a battle map), a random alien from the near tier: it goes after the player,
        does not respawn. Not usable while a CPU alien lives on the map and in the safe zone (the client's texts)."""
        w, p, c = self.w, self.p, ALIEN_CPUS[loot]
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(c['cooldown_group'], now):
            return
        if H.map_class(w.map_id) not in c['maps'] and not H.name(w.map_id).startswith('4-'):
            self.log('   %s cannot be used on this map (%s)' % (loot, H.name(w.map_id)))
            return
        hx, hy = w.hero_pos(now)
        if w.in_peace(hx, hy):
            self.send([stm('msg_aliencpu_dmz')])
            return
        if any(n.alive and getattr(n, 'cpu', False) for n in w.npcs.values()):
            self.send([stm('msg_aliencpu_npc_already_exists')])
            return
        if len(w.npcs) > c.get('npc_limit', 10 ** 9):                # Bountiful: cannot be used if there are more than 250 aliens on the map
            self.send([stm('msg_aliencpu_npc_limit_reached')])
            return
        if c.get('event') and not CAL.is_active(c['event']):    # Bountiful only while the Gauntlet of Plutus is running (deleted when it ends)
            self.log('   %s: %s event is not running' % (loot, c['event']))
            return
        p.use_ammo(loot, 1)
        a = random.uniform(0, 2 * math.pi)
        x = min(max(600, hx + math.cos(a) * 800), w.map_w - 600)
        y = min(max(600, hy + math.sin(a) * 800), w.map_h - 600)
        n = w.spawn_npc_at(random.choice(c['kinds']), x, y)
        n.summoned = n.hunt = n.cpu = True
        n.saturn = bool(c.get('counts_as_player'))          # Saturn Transmitter: an enemy player in PvP quests (forum 127576)
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now)])
        self.log('   %s: %s spawned' % (loot, n.d['name']))

    def ghost_msg(self, on):
        return ('VisualModifierCommand', dict(userId=self.w.hid, modifier=S['ghost']['visual'], attribute=0, additionalAttribute='',
                                              count=0, activated=on))

    def ghostify(self, now):
        """Ghostifier: the ship looks like a ghost for a minute (the client's VisualModifier GHOST_EFFECT)."""
        w, p, c = self.w, self.p, S['ghost']
        loot = c['menu']
        if w.hero_dead or p.ammo(loot) <= 0 or not self.ready(c['cooldown_group'], now):
            return
        p.use_ammo(loot, 1)
        self.ghost_end = now + c['duration_sec']
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now), self.ghost_msg(True)])
        self.log('   Ghostifier: %d sn' % c['duration_sec'])

    # ------------------------------------------------------------ cloak CPU
    def cloaked(self):
        return bool(self.p.d.get('cpu_hidden'))

    def cloak(self, now):
        w, p = self.w, self.p
        loot = cloak_loot(p)
        if not loot or self.cloaked() or w.hero_dead:
            return
        if EX.uses(p, loot) <= 0:
            self.send([stm('cloak_cpu_failed_generic')])
            return
        left = EX.use(p, loot)
        p.ach('spend', loot=loot, count=1)       # Pass quests: "Activate the Cloak CPU" (battle_pass.py)
        w.abilities.reveal()                   # wiki: an active Ultimate Cloaking ends, the CPU's cloaking takes over
        with p.lock:
            p.d['cpu_hidden'] = True
            p.dirty = True
        self.send([legacy('0|n|INV|%d|1' % w.hid)] + self.status(S['cloak_cpu']['menu']))
        self.log('   cloaked (%s, %d left)' % (loot, left))

    def reveal(self, key='lost_invisible_attack'):
        """Cloaking ends on attack."""
        if not self.cloaked():
            return
        with self.p.lock:
            self.p.d['cpu_hidden'] = False
            self.p.dirty = True
        self.send([legacy('0|n|INV|%d|0' % self.w.hid), stm(key)] + self.status(S['cloak_cpu']['menu']))
        self.log('   cloak ended')

    # ------------------------------------------------------------ aim CPU, automatic rocket and launcher
    def aim(self, chance):
        """AIM-01/02: miss rate -25%/-50%; 10 Xenomit per shot (ineffective without)."""
        p = self.p
        item = S['aim_cpu']['menu']
        r = max((v for l, v in EX.props(p, 'aim')), default=0)
        if not r or not toggled(p, item):
            return chance
        if p.ore_count(XENOMIT) < S['aim_cpu']['xenomit']:
            if not self.aim_warned:              # "Warning: The Targeting Guidance CPU isn't working. You don't have enough Xenomit."
                self.aim_warned = True
                self.send([stm('aim_cpu_failed_xenomit')])
            return chance
        self.aim_warned = False
        p.remove_ores({XENOMIT: S['aim_cpu']['xenomit']})
        self.send(self.ore_msgs())
        return 1 - (1 - chance) * (1 - r)

    def auto_weapons(self, n, now):
        """On a laser attack: AROL-X fires the selected rocket, RL-LB1 the loaded launcher, by itself."""
        w = self.w
        uid = getattr(n, 'id', n)
        if toggled(self.p, 'equipment_extra_cpu_arol-x'):
            r = self.p.d['selected'].get('rocket')
            if r and (self.ready(item_cooldown(r)[0], now) if special(r) else now >= w.rocket_ready):
                w.rocket({'targetId': uid})
        if toggled(self.p, 'equipment_extra_cpu_rllb-x') and capacity(self.p) and loaded(self.p)[1] >= capacity(self.p):
            self.launcher_fire(now, n)

    # ------------------------------------------------------------ rocket launcher
    def launcher_tick(self, now):
        w, p = self.w, self.p
        if self.launcher_cd and now >= self.launcher_cd:        # cooldown ended: the counter is ready
            self.launcher_cd = 0.0
            self.send([('MenuItemTimerCommand', dict(activatable=True, timerState=mod('TimerStateModule', timerStateValue=0), maxTime=0,
                                                     time=0, menuItemId=S['launcher']['menu']))])
        cap = capacity(p)
        if not cap or w.hero_dead:
            return
        sel = p.d['selected'].get('launcher')
        ammo, n = loaded(p)
        msgs = []
        if n and ammo != sel:                  # ammo changed: the loaded ones come back
            if not SET.get('infinite_ammo'):   # not spent when loading with infinite ammo: a refund would be a free rocket
                p.add_ammo(ammo, n)
            msgs += w.ammo_msgs(ammo)
            ammo, n = sel, 0
            self.store(ammo, 0)
        if not sel or n >= cap:
            self.send(msgs)
            return
        rapid = bool(w.abilities.flags.get('rocket'))            # Tartarus Rapid Fire: the launcher fills at once
        if not rapid and now < self.next_load:
            self.send(msgs)
            return
        add = min(cap - n, p.ammo(sel)) if rapid else min(1, p.ammo(sel))
        if add <= 0:
            self.send(msgs)
            return
        p.use_ammo(sel, add)
        n += add
        self.store(sel, n)
        self.next_load = now + (S['launcher']['refill_sec'] * max(0.1, 1 + p.mods().get('launcher_cooldown', 0))   # Star +%33 …
                                * SET.multiplier('rocket_cooldown'))                                               # panel
        self.send(msgs + w.ammo_msgs(sel) + self.status(S['launcher']['menu'])
                  + [legacy('0|RL|S|%d|%d|%d' % (launcher_type(p), LAUNCHER_AMMO.get(sel, {}).get('uid', 7), n))])

    def store(self, ammo, n):
        with self.p.lock:
            self.p.d['launcher_loaded'] = [ammo, n]
            self.p.dirty = True

    def launcher_fire(self, now, n=None):
        w, p = self.w, self.p
        if now < self.launcher_cd:
            return
        if n is None and not capacity(p):              # from the shortcut, no launcher fitted
            return self.send([stm('hellstorm_launcher_not_equipped')])
        uid = getattr(n, 'id', n) if n is not None else w.target
        n = w.npcs.get(uid)
        asset = w.asset_at(uid) if not n else None
        ammo, cnt = loaded(p)
        if (not asset and (not n or not n.alive)) or cnt <= 0 or w.hero_dead or w.jumping or ammo not in LAUNCHER_AMMO:
            return
        if asset:
            denied = w.asset_targets.asset_attackable(uid)
            if denied:
                return self.send(denied)
        hx, hy = w.hero_pos(now)
        nx, ny = asset if asset else n.mover.pos(now)
        rng = S['launcher']['range']
        if math.hypot(nx - hx, ny - hy) > rng:
            self.send([('AttackRangeExceededCommand', {'uid': uid, 'maxRange': rng, 'type': 0})])
            return
        w.end_invuln(force=True)
        w.abilities.reveal()
        self.reveal()
        w.last_combat = now
        w.stop_repair()
        cfg = LAUNCHER_AMMO[ammo]
        hit = random.random() < cfg.get('hit', 1.0)
        self.store(ammo, 0)
        if random.random() < p.ship_row().get('extra_rocket_chance', 0):
            cnt += 1                                    # Tartarus Plus: "1 in 5 chance of firing an extra rocket" (cephanesiz)
        self.next_load = now + (S['launcher']['refill_sec'] * max(0.1, 1 + p.mods().get('launcher_cooldown', 0))   # Star +%33 …
                                * SET.multiplier('rocket_cooldown'))                                               # panel
        p.ach('shot', weapon='ROCKET_LAUNCHER')
        self.launcher_cd = now + LAUNCHER_COOLDOWN            # recording (2026-10-27, 117 shots): exactly 3.0 s counter after a shot
        w.attacked(now, LAUNCHER_COOLDOWN + ROCKET_FLIGHT)    # a miss too
        menu = S['launcher']['menu']
        self.send([('MenuItemTimerCommand', dict(activatable=False, timerState=mod('TimerStateModule', timerStateValue=2),
                                                 maxTime=int(LAUNCHER_COOLDOWN * 1000), time=int(LAUNCHER_COOLDOWN * 1000), menuItemId=menu))])
        first = salvo(w.hid, uid, hit, cnt, cfg['type'])
        self.send([first, legacy('0|RL|S|%d|%d|0' % (launcher_type(p), cfg['uid']))] + self.status(S['launcher']['menu']))
        self.log('   launcher: %d x %s%s' % (cnt, ammo, '' if hit else ' (miss)'))
        if p.lab_bonus(1):
            w.lab_spend(1, cnt)                         # rocket upgrade: one per rocket of the volley (like the single rocket, misses too)
        if not hit:
            return
        mods = p.mods()
        dmg = sum(cfg.get('damage', 0) * random.uniform(0.85, 1.0) for _ in range(cnt))
        fusion = SKL.mods(p).get('rocket', 0)                  # Rocket Fusion does not boost Hellstorm (fandom Rocket launcher)
        dmg = int(dmg * (1 + mods.get('rocket', 0) - fusion + (mods.get('npc', 0) if n else 0) + mods.get('launcher_damage', 0))     # Rapid Fire Plus +%20
                  * (1 + p.lab_bonus(1)) * launcher_upgrade(p))
        drain = cfg.get('shield_drain', 0) * cnt
        impact = w.hit_asset if asset else w.hit_npc
        kw = {} if asset else {'ammo': ammo}            # Referee-Bot takes damage only from CBR (world.hit_npc)

        def land(part, share):
            if part:                           # SAR/CBR/PIR: to the player drawn from the alien's shield
                w.last_shield_hit = 0
                impact(uid, part, cfg.get('attack_at', 0), shield_only=True, **kw)
                if w.last_shield_hit:
                    g = p.d['ship']
                    p.set_hull(shield=g.get('shield', 0) + w.last_shield_hit)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
            if share:
                impact(uid, share, 0, **kw)
        # recording (2026-10-27, ~100 salvos): the damage is a separate AttackHitCommand per rocket, consecutive rockets 2.18 s apart (2.1-2.24);
        # the first damage 0.73-1.9 s after the salvo. Total damage the same: divided among the rockets, the remainder to the last.
        first = random.uniform(LAUNCHER_FIRST_DELAY[0], LAUNCHER_FIRST_DELAY[1])
        for i in range(cnt):
            w.later(first + i * LAUNCHER_INTERVAL, lambda b=dmg // cnt + (dmg % cnt if i == cnt - 1 else 0),
                    c=drain - drain // cnt * (cnt - 1) if i == cnt - 1 else drain // cnt: land(c, b))

    # ------------------------------------------------------------ special rockets
    def fire_special(self, rocket, n, now):
        w, p = self.w, self.p
        r = ROCKETS[rocket]
        uid = getattr(n, 'id', n)
        asset = not hasattr(n, 'id')
        if asset and (not w.asset_at(uid) or w.asset_targets.asset_attackable(uid)
                      or not (r.get('damage') or r.get('shield_damage'))):
            return
        if not self.ready(r['cooldown_group'], now) or p.use_ammo(rocket, 1) is None:
            return
        w.end_invuln(force=True)
        w.abilities.reveal()
        self.reveal()
        w.last_combat = now
        w.attacked(now, ROCKET_FLIGHT)                        # a miss too
        w.stop_repair()
        p.ach('shot', weapon='ROCKET_LAUNCHER')
        hit = random.random() < w.rocket_hit(rocket)
        self.send(w.ammo_msgs(rocket) + [w.rocket_msg(uid, hit, r.get('uid', 1)), self.cooldown(rocket, now)])
        if hit:
            w.later(ROCKET_FLIGHT, lambda: self.special_hit(rocket, uid))
        else:
            w.later(ROCKET_FLIGHT, lambda: self.send([('AttackMissedCommand', dict(attackType=attack_type(0), targetUserId=uid,
                                                                                    skillColorId=0))]))
        self.log('   special rocket: %s' % rocket)

    def special_hit(self, rocket, uid):
        import lasers as LASERS
        w, p = self.w, self.p
        n = w.npcs.get(uid)
        asset = w.asset_at(uid) if not n else None
        if w.hero_dead or w.jumping or (not asset and (not n or not n.alive)):
            return
        if asset and w.asset_targets.asset_attackable(uid):
            return
        impact = w.hit_asset if asset else w.hit_npc
        r = ROCKETS[rocket]
        dmg = r.get('damage', 0) * ((LASERS.name_match(r.get('target_multiplier', {}), n) or 1) if n else 1)      # AGT-500: Agatus'a x5
        if dmg:
            mods = p.mods()
            impact(uid, int(dmg * random.uniform(0.85, 1.0) * (1 + mods.get('rocket', 0) + (mods.get('npc', 0) if n else 0))), 0,
                      hull_only=bool(r.get('hull_only')))                                  # SP-100X: bypasses the shield
        if r.get('shield_damage'):                                                             # SR-5: steal from the shield
            w.last_shield_hit = 0
            impact(uid, r['shield_damage'], 0, shield_only=True)
            got = int(w.last_shield_hit * r.get('shield_steal', 0))
            if got:
                g = p.d['ship']
                p.set_hull(shield=g.get('shield', 0) + got)
                self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
            if r.get('self_slow'):
                w.hero_effect('slow', r['self_slow'][1], r['self_slow'][0], source=rocket)
        if asset:                       # structures have no ship look, speed or hit effects
            return
        if not n.alive:
            return
        if r.get('look_sec'):                                                               # WIZ-X: another ship's look
            models = {int(t.get('model', k)) for k, t in _N['types'].items() if str(t.get('model', k)).isdigit()}
            ev = [m for k, m in sorted(r.get('look_event', {}).items()) if CAL.is_active(k)]    # Thanksgiving: hindi, her isabette
            pool = [m for k, ms in sorted(r.get('look_chances', {}).items()) if CAL.is_active(k) for m in ms]    # event designs
            if ev:
                model = str(ev[0])
            elif pool and random.random() < r.get('look_chance', 1.0):              # during the event a 30% chance of an event design (wiki)
                model = str(random.choice(pool))
            else:
                model = str(random.choice(sorted(models - {int(n.model) if str(n.model).isdigit() else None})))
            vis = lambda on: [('VisualModifierCommand', dict(userId=uid, modifier=25, attribute=0, additionalAttribute=model, count=0,
                                                             activated=on))]
            self.send(vis(True))
            w.later(r['look_sec'], lambda: self.send(vis(False)) if uid in w.npcs else None)
        for kind, (val, sec) in r.get('effect', {}).items():
            w.npc_effect(n, kind, sec, val, source=rocket)
        fx = r.get('fx')
        if fx:
            sec = max(s for v, s in r.get('effect', {}).values())
            self.send([legacy('0|n|fx|start|%s|%d' % (fx, uid))])
            w.later(sec, lambda: self.send([legacy('0|n|fx|end|%s|%d' % (fx, uid))]))
        if not n.engaged:
            n.engaged = True

    # ------------------------------------------------------------ jump CPUs
    def jump_cpu(self, now):
        w, p = self.w, self.p
        loot = jump_loot(p)
        if not loot or w.hero_dead or w.jumping or self.jump:
            return
        home = int(w.map_id) == home_map(p)             # map_id is text: before, it never matched, and it also jumped on the main map
        if home or not jump_allowed(loot, w.map_id) or EX.uses(p, loot) <= 0:
            # the client's texts: "…already on the target map." / "Jump from the current map not possible with your CPU!"
            why = 'jump_cpu_failed_ontarget' if home else None if jump_allowed(loot, w.map_id) else 'jump_cpu_failed_map'
            self.send(self.status(S['jump_cpu']['menu']) + ([stm(why)] if why else []))
            return
        if self.too_soon(now):
            return
        self.start_jump(home_map(p), loot, now)

    def too_soon(self, now):
        """The client's text: "your last jump or login was less than 10 seconds ago"."""
        if now - self.born < S['jump_cpu'].get('cooldown_sec', 10):
            self.send([stm('jump_cpu_failed_time')])
            return True
        return False

    def start_jump(self, dest, loot, now, voucher=False):
        w = self.w
        if now - w.last_combat < S['jump_cpu']['combat_sec']:
            self.send([stm('jump_cpu_failed_attack3')])          # "5 s after combat with an alien" (savas_sn)
            return False
        if w.radiation_since is not None:                      # forum 127075: no jumping in a radiation zone
            self.send([stm('jump_cpu_failed_map')])
            return False
        if loot == 'ajp' and now < self.p.d.get('ajp_ready', 0):
            self.send([stm('ttip_block_cooldown')])                 # "CPU cooling down. Jump not possible." (forum 127075: 120 sn)
            return False
        sec = S['jump_cpu']['countdown_sec_ajp' if loot == 'ajp' else 'countdown_sec']     # JP-01/02 instant, AJP-01 10 s
        self.jump = dict(target=dest, time=now + sec, cpu=loot, start=now, voucher=voucher, place=w.hero_pos(now))
        if sec:                                                  # without a countdown the jump is on the next step (jump_tick)
            self.send([legacy('0|A|JCPU|S|%d|%d' % (sec, dest))])
        self.log('   CPU jump: %s -> %s, %d s' % (H.name(w.map_id), H.name(dest), sec))
        return True

    def cancel_jump(self, key='jump_cpu_failed_attack3'):
        """An attack during the countdown: the attack3 alien text (attack2 "20 s with another pilot" is PvP's; live test H22)."""
        if not self.jump:
            return
        self.jump = None
        self.send([legacy('0|A|JCPU|S|-1|0'), stm(key)])
        self.log('   CPU jump cancelled')

    def jump_tick(self, now):
        j = self.jump
        if not j:
            return
        w, p = self.w, self.p
        if w.hero_dead or w.last_combat > j['start']:
            self.cancel_jump()
            return
        x, y = w.hero_pos(now)
        if j.get('place') and math.hypot(x - j['place'][0], y - j['place'][1]) > 5:     # forum 127075: if you move during the countdown it is cancelled
            self.cancel_jump('error_cpu_jump_cancelled_through_move')
            return
        if now < j['time']:
            return
        self.jump = None
        if j['cpu'] == 'ajp':
            if not self.pay_ajp(j['target']):
                self.send([legacy('0|A|JCPU|S|-1|0'), stm('jump_cpu_malfunction')])
                return
            with p.lock:
                p.d['ajp_ready'] = now + S['advanced_jump']['cooldown_sec'] * SET.multiplier('skill_cooldown')
                p.dirty = True
        else:
            EX.use(p, j['cpu'])
        w.jumping, w.attacking, w.target = True, False, None
        for n in w.npcs.values():
            n.engaged = False
        dest, pos = j['target'], 'random' if j['cpu'] == 'ajp' else 'station'   # AJP-01: to a random place on the target map (real game)
        if (j['cpu'] != 'ajp' and int(w.map_id) != 42 and SET.get('jump_deviation')                 # panel: can be turned off
                and random.random() < S['jump_cpu'].get('graveyard_chance', 0)):
            dest, pos = 42, None                      # Cubikon Graveyard (wiki: "once every 1,000 jumps"; single-player rate)
            self.log('   jump CPU strayed to the Cubikon Graveyard')
        if w.on_jump:
            self.send([stm('msg_cpu_jump_sequence_complete')])     # "CPU jump completed. Map switched." (forum 127075)
            w.on_jump(dest, None, pos)

    def pay_ajp(self, dest):
        p, c = self.p, S['advanced_jump']
        if p.resource(c['voucher']):
            p.add_resource(c['voucher'], -1)
            self.send([vouchers_msg(p)])
            return True
        price = ajp_price(p, dest, self.w.map_id)
        if p.d['pilot'].get('uridium', 0) < price:
            return False
        p.gain(uridium=-price, reason='buy_cpu_jump')
        self.send(self.w.money_msgs() if self.w.money_msgs else [])
        return True

    def jcpu(self, parts):
        """The client's JCPU request (space map): S|map choice, J jump (GET at login; game.py replies)."""
        w, p = self.w, self.p
        cmd = parts[1] if len(parts) > 1 else ''
        if cmd == 'GET':
            self.send([jcpu_list(p), vouchers_msg(p)])
        elif cmd == 'S' and len(parts) > 2 and parts[2].isdigit():
            m = int(parts[2])
            ok = (has_ajp(p) and m != int(w.map_id) and m in H.NAMES and jump_allowed('equipment_extra_cpu_ajp-01', m)
                  and jump_allowed('equipment_extra_cpu_ajp-01', w.map_id) and not ajp_locked(p, m))
            price = ajp_price(p, m, w.map_id) if m in H.NAMES else 0
            self.ajp_target = m if ok else None
            self.send([legacy('0|A|JCPU|C|%d|%d|%d' % (m, price, 1 if ok else 0))])
        elif cmd == 'J':
            m = self.ajp_target
            if m is None or not has_ajp(p) or w.hero_dead or w.jumping or self.jump:
                self.send([stm('jump_cpu_malfunction')])
                return
            price = ajp_price(p, m, w.map_id)
            if price and p.d['pilot'].get('uridium', 0) < price:
                self.send([stm('jump_cpu_malfunction')])
                return
            if self.too_soon(time.time()):
                return
            self.start_jump(m, 'ajp', time.time())

    # ------------------------------------------------------------ death
    def on_death(self):
        self.cancel_jump('jump_cpu_malfunction')
        if self.cloaked():
            with self.p.lock:
                self.p.d['cpu_hidden'] = False
                self.p.dirty = True
