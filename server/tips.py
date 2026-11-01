"""Hints for new players and one-time notifications (roadmap stage 2).

Client (HintSystemContentProvider): HintWindowAddComand {window {content: HintType}, visibility 0, soundModule, addToList,
openedFromArchive} opens the hint window; with addToList it also enters the hint archive (HintWindowListInitCommand sets up the archive on
login). The client's dictionary has 39 types, without CONFIG_SWITCH (15): that one is not sent. The texts come in two kinds:
"gameentry_hintwindow_message_*" (when something happens: cargo full, ammo out, repair) and "targeted_hintwindow_message_*" (an invitation
to a feature: Galaxy Gates, skill tree, Tech Factory). In the recording, WELCOME (12) was on login and HOW_TO_FLY and REQUEST_MISSION
(13, 14) in the archive.

Single-player adaptation: each hint once (tips_shown in the profile); hints the player closed (hints_closed, game.py) do not reopen;
if the panel's "hints" setting is off, none is sent.
- Event hints (by their text): repair (the 3 key) after leaving a fight damaged, first ore (sell at the refinery), cargo full, ammo out
  (quick buy), first kill (earn XP/honor/credits), first target selection (attack keys), first approach to a portal (J), another company's
  map or 4-X (PvP warning), firing another rocket while holding PLT-2021, first equipment from the shop (equip in the hangar), second ship
  (ship teleport).
- Invitation hints on level-up (LEVELS); not shown if the feature is already in use (used): e.g. the rocket launcher hint does not open
  for a player who already has a rocket launcher.

Event notification: the description of the running map event (the client's <text>_event_description, e.g. curcubitor) once per event
period in a message box via NormalTipsCommand {messageKey} (event_notification in the profile).
"""
import settings as SET

SHIP_REPAIR, SKYLAB, PVP_WARNING, THE_SHOP, CHANGING_SHIPS, INSTALLING_NEW_EQUIPMENT, JUMP_GATES, PREPARE_BATTLE = 0, 1, 2, 3, 4, 5, 6, 7
GET_MORE_AMMO, BOOST_YOUR_EQUIP, SELL_RESOURCE, WEALTHY_FAMOUS = 8, 9, 10, 11
EQUIP_YOUR_ROCKETS, ATTACK, FULL_CARGO, SECOND_CONFIGURATION, ITEM_UPGRADE = 17, 19, 21, 22, 23
GALAXY_GATE, SKILL_TREE, TECH_FACTORY, PALLADIUM, AUCTION_HOUSE, ROCKET_LAUNCHER, EXTRA_CPU, SHIP_DESIGN = 24, 25, 26, 28, 29, 30, 31, 32
ORE_TRANSFER, PRO_ACTION_BAR_INFO, ASSEMBLY = 35, 37, 39
PLT_2021 = 'ammunition_rocket_plt-2021'
CLIENT_TYPES = set(range(40)) - {15}  # the types the client knows (HintSystemContentProvider)
SOUND = 132                           # the sound of the hint in the recording

# the levels of the invitation hints (adaptation: the feature becomes useful at that level; the trader of 5-2 ~10-12, Tech Factory/Assembly
# mid levels)
LEVELS = {2: (THE_SHOP, PREPARE_BATTLE), 3: (BOOST_YOUR_EQUIP,), 4: (GALAXY_GATE, PRO_ACTION_BAR_INFO),
          5: (SECOND_CONFIGURATION, EXTRA_CPU, AUCTION_HOUSE), 6: (SKILL_TREE, SKYLAB), 7: (ROCKET_LAUNCHER, ITEM_UPGRADE),
          8: (TECH_FACTORY, ASSEMBLY, ORE_TRANSFER), 10: (SHIP_DESIGN,), 12: (PALLADIUM,)}


def owned_items(p):
    return set(p.d.get('items', {}).values())


def used(p, kind):
    """Is the feature already in use (the invitation hint is unnecessary)."""
    items = owned_items(p)
    if kind == EXTRA_CPU:
        return any(i.startswith('equipment_extra_cpu_') for i in items)
    if kind == ROCKET_LAUNCHER:
        return any(i.startswith('equipment_weapon_rocketlauncher_') for i in items)
    if kind == SHIP_DESIGN:
        return any(s.get('designs') for s in p.d.get('ships', {}).values())
    if kind == GALAXY_GATE:
        return any(g.get('parts') or g.get('done') for g in ((p.d.get('gates') or {}).get('gates') or {}).values() if g)
    return False


def for_purchase(p, loot, first_equipment):
    """An item bought from the shop -> hint type or None."""
    if loot.startswith('ship_') and '_design_' not in loot and len(p.d.get('ships', {})) >= 2:
        return CHANGING_SHIPS
    if first_equipment:
        return INSTALLING_NEW_EQUIPMENT
    return None


class Hints:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log

    def shown(self):
        return self.p.d.setdefault('tips_shown', [])

    def show(self, kind):
        """A hint once -> [HintWindowAddComand] or empty (already shown, closed, not in the client, or off in the panel)."""
        if kind not in CLIENT_TYPES or not SET.get('hints'):
            return []
        if kind in self.shown() or kind in self.p.d.get('hints_closed', []):
            return []
        with self.p.lock:
            self.shown().append(kind)
            self.p.dirty = True
        self.log('   hint: %d' % kind)
        return [('HintWindowAddComand', dict(paymentLink='', visibility=0, addToList=True, openedFromArchive=False,
                                             soundModule={'_': 'SoundTriggerModule', 'playSound': True, 'soundId': SOUND},
                                             window={'_': 'HintWindowModule', 'content': kind}))]

    def level(self, lv):
        """Level-up: the first not-yet-shown one among the invitation hints up to that level (and the levels skipped). One window at a time
        (so they do not stack); the rest come at later levels."""
        for at in sorted(LEVELS):
            if at > lv:
                break
            for kind in LEVELS[at]:
                if kind in self.shown() or used(self.p, kind):
                    continue
                msgs = self.show(kind)
                if msgs:
                    return msgs
        return []

    def event_tips(self, specs, period):
        """The description of running map events once per period (NormalTipsCommand). specs: [(event, section)]; period:
        event -> start of the period (0 if none)."""
        if not SET.get('hints'):
            return []
        st = self.p.d.setdefault('event_notification', {})
        out = []
        for k, s in specs:
            text = (s.get('info') or {}).get('text')
            if not text or st.get(k) == period(k):
                continue
            with self.p.lock:
                st[k] = period(k)
                self.p.dirty = True
            out.append(('NormalTipsCommand', {'messageKey': '%s_event_description' % text}))
            self.log('   event notification: %s' % k)
        return out
