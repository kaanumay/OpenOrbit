"""Keyed loot boxes (roadmap Stage 5; data data/boxes.json <- tools/boxes.py, wiki + the client's names).

On the map AddBoxCommand {boxType: PIRATE_BOOTY | PIRATE_BOOTY_GOLD | PIRATE_BOOTY_RED | PIRATE_BOOTY_BLUE | BLACK_BOOTY_BOX |
PIRATE_BOOTY_SILVER | UNSTABLE_BLACKLIGHT_CACHE | BLACKLIGHT-CRYPT | ASTRAL_BOOTY_BOX | ASTRAL_PRIME_BOOTY_BOX | MASQUE_BOOTY_BOX
(Apocalypse) | PERSEUS_BLESSING_BOOTY_BOX | PROMETHEUS_BOOTY_BOX | LAUREL_BOX (the last two in E8's events) | event boxes};
when collecting (CollectBoxRequest), if the player has no key of the type the box
stays in place and the client's text arrives (0|A|STM|msg_loot_failed_no_booty-key-...); if they have one a key is spent, the HUD counter is updated
("0|A|<code>|<remaining>"), a reward is drawn from the contents (weighted; an owned ship/design/drone is not drawn; if an Epic package comes up,
all of its parts) and given with the shop's reward function. If the design in the Black Light Cache is already owned, 10,000 uridium (wiki).
If there is no green key and automatic purchase is on in the settings (autoBuyGreenBootyKeys) a key is bought at the shop price.
Maps: X-2..X-8 (1-2 ... 3-8), X-1..X-8 (Perseus, Laurel), 4-X, 5-X (5-1..5-3), 5-4 (silver), BL (BL-1..3). Gold boxes every other
week on Friday (wiki).
"""
import json, os, random, re, time
import game_data as DATA

import event_appearances as EG

HERE = os.path.dirname(os.path.abspath(__file__))
K = DATA.load('boxes.json')
BOXES = K['boxes']
for _k, _b in BOXES.items():                 # event looks: the box's local design rows (outside the wiki table; pick_all)
    _b['local'] = EG.box_rows(_k)
PACKAGE = 'package'                               # Epic package row: ['package', [[lootId, count], ...], weight]; on opening, all of the parts
MAPS = {k: re.compile(v) for k, v in K['maps'].items()}
GREEN_KEY = 'resource_booty-key'
OPEN_SEC = 3                                   # opening time (whole seconds: the client's counter): official ~5 s, the user's decision 3 s
BL_CACHE = 'UNSTABLE_BLACKLIGHT_CACHE'
KEYS = {}                                     # key -> the first box type that uses it (for the HUD code)
for _k, _b in BOXES.items():
    KEYS.setdefault(_b['anahtar'], _k)
CODES = {b['code']: KEYS[b['anahtar']] for b in BOXES.values() if b.get('code')}   # HUD code -> box type (the "0|A|BK...|0" lines at login)


def active(kind, now=None):
    """Calendar (the box's 'calendar' is the name of the event in event_calendar.py): the gold box on the 2nd and 4th Friday of the month, Obsidian / R&B / Apocalypse
    in weekly rotation (E8), event boxes (Empyrian, Prosperous, Lucent Egg) while the event runs; list: while one runs (Battle
    Pass Box)."""
    return bool(BOXES[kind].get('calendar') is None or box_event(kind, now))


def box_event(kind, now=None):
    """The active event in the box's calendar (None if there is none)."""
    import event_calendar as CAL
    cal = BOXES[kind].get('calendar')
    return next((k for k in (cal if isinstance(cal, list) else [cal]) if k in CAL.EVENTS and CAL.is_active(k, now)), None)


def spawns(map_name, now=None):
    """Boxes that spawn on this map -> [(type, count)]."""
    return [(k, b['count']) for k, b in BOXES.items()
            if active(k, now) and any(MAPS[m].match(map_name or '') for m in b['maps'])]


def respawn_delay(kind):
    lo, hi = BOXES[kind]['renew_sec']
    return random.uniform(lo, hi)


def owned(p, loot):
    """Does the player own the unique reward: ship, ship design (on the ship or in storage), drones, drone and P.E.T. designs (in the inventory or in storage)."""
    if '_design_' in loot:
        if any(loot in s.get('designs', []) for s in p.d['ships'].values()):
            return True
        return p.resource(loot) > 0
    if loot.startswith('ship_'):
        return any(s['lootId'] == loot for s in p.d['ships'].values())
    if loot.startswith('drone_') and any(d.get('lootId') == loot for d in p.d.get('drones', [])):
        return True
    return p.resource(loot) > 0 or loot in p.d.get('items', {}).values()     # drone and P.E.T. designs in the inventory


def unique(loot):
    return loot.startswith(tuple(K['single'])) or '_design_' in loot


def design(r):
    """A row in the design bucket: a unique reward (ship, design, drone) or an Epic package."""
    return r[0] == PACKAGE or unique(r[0])


def gone(p, r):
    """Can the row not be drawn: an owned unique reward or a package all of whose parts are owned."""
    return all(owned(p, l) for l, _ in r[1]) if r[0] == PACKAGE else unique(r[0]) and owned(p, r[0])


def pick_all(p, kind, rng=random):
    """Reward from the contents -> [(lootId, count)]: one row; if an Epic package comes up, all of its parts that are not owned. Owned unique
    rewards are not drawn; in a box with 'reward_event' (Battle Pass Box) the rows of the running event. Local design rows ('local': box_extra
    and event looks; not in the wiki table) share the design draw with the table's designs: the designs' total chance
    stays as in the wiki and is only divided among them; the chance of the table's other rows is not disturbed."""
    box = BOXES[kind]
    rows = box['reward'] or box.get('reward_event', {}).get(box_event(kind)) or []
    if not rows:                             # Battle Pass Box collected after the event ended: the key back
        return [(box['anahtar'], 1)]
    if kind == BL_CACHE:                     # wiki: the design at random, 10,000 uridium if already owned
        loot = rng.choice(rows)[0]
        return [('currency_uridium', K['bl_repeat_uridium']) if owned(p, loot) else (loot, 1)]
    pool = [r for r in rows if not gone(p, r)] or [r for r in rows if not design(r)]
    local = [r for r in box['local'] if not owned(p, r[0])]
    wd, wl = sum(r[2] for r in pool if design(r)), sum(r[2] for r in local)
    k = wd / (wd + wl) if wd else 1.0
    pool += local
    row = rng.choices(pool, [r[2] * k if design(r) else r[2] for r in pool])[0]
    if row[0] == PACKAGE:
        return [(l, n) for l, n in row[1] if not (unique(l) and owned(p, l))]
    loot, amount = row[0], row[1]
    if isinstance(amount, list):
        amount = rng.randint(amount[0], amount[1])
    return [(loot, int(amount))]


def pick(p, kind, rng=random):
    """pick_all's first reward -> (lootId, count) (the single reward in boxes without packages)."""
    return pick_all(p, kind, rng)[0]


def key_line(p, kind):
    """The key counter in the HUD (old protocol: SetAttributeAssemblyHelper.AssembleBootyKeysUpdate, code -> Hero.BootyKeys*Amount: BK green,
    BKP Prosperous, BKPR Prometheus; green was sent as BKP, the client wrote Prosperous: user report 2026-10-24); None for a key
    with no counter (Battle Pass Key)."""
    b = BOXES[kind]
    return '0|A|%s|%d' % (b['code'], p.resource(b['anahtar'])) if b.get('code') else None
