"""Omega AutoTactic (autopilot; roadmap stage 9; sources: the darkorbit wiki and the client's code).

The client plays by itself (HangUpAI: attacking aliens, collecting boxes, buying ammo via ShopItemBuyRequest 'ammunition', abilities,
repair robot at low HP, and the safe zone; jumping to the next wave in a Galaxy Gate); these reach the server as ordinary requests. F12 or
the window's APPLY&START button requires Premium ("You need to purchase the Premium Pack to operater."; in single player everyone is Premium).
The server's job:
  AutopilotInfoRequest                  -> AutopilotInfoCommand {remainingSeconds, laserRange, result, autopilotInfos (the settings' JSON)}
  AutopilotInfoSaveRequest {autopilotInfos} -> AutopilotInfoSaveCommand {result}; settings are kept in the profile
  AutopilotStatus {status: 0 START, 1 STOP}  the client's notification (STOP on login and on movement); logged, duration is counted
In the profile: autopilot {setting, state, start, total_sec, session, selection}.

Selected aliens and boxes (2026-10-18, user report: selections reset when the map changes, the list only shows what is in view):
  - The client keeps selections per map (NPCSelectedList / CollectSelectedList: map -> list; the settings themselves are in PlayerPrefs
    "AutoAFKData", written when info arrives). When the window opens and the current map's key is missing, it replaces the dictionary
    with a new one (UIAssistantSystem.UpdateInfo): the selections of the other maps were deleted and only the new map was saved. The
    autopilot's box filter also reads the key directly (UnitComponentSystem.GetCollectables). The server keeps the selection independent
    of the map (secim) and sends it with every map's key: boxes are the same on every map, aliens are those that appear on that map
    (npc.json's table, those living on the map, those selected on that map). On save every key is compared with what the client holds;
    additions are selected, removals are dropped.
  - The client builds the lists on the right only from units and boxes it knows (GetNPCIDList, GetBoxList; once a second): those within
    view range. Listing the whole map required reporting all of them; the version that reported them while the window was open and the
    autopilot was running (4878be2a) was removed: the game froze badly when the menu opened (user, 2026-10-18).
"""
import json, os, time

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['autopilot']
START, STOP = 0, 1
REQUESTS = {'AutopilotInfoRequest', 'AutopilotInfoSaveRequest', 'AutopilotStatus'}
NPC_LIST, BOX_LIST = 'NPCSelectedList', 'CollectSelectedList'     # AssistantData: map -> NpcData {Name, NpcID, NpcType} / "box_<type>"
LIMIT = 8000               # upper limit of the JSON sent: the autopilot settings are re-decoded from PlayerPrefs on every read
                           # (HangUpAI.get_Data); the real settings in a save are ~0.7 KB


def _maps(v):
    """The settings' map -> list dictionary (empty if corrupt)."""
    return {str(k): x for k, x in v.items() if isinstance(x, list)} if isinstance(v, dict) else {}


def _npc_key(e):
    return (e.get('Name') or None) if isinstance(e, dict) else None     # the field the client matches on too (NpcData.Name)


def _box_key(e):
    return (e or None) if isinstance(e, str) else None


def _num(k):
    return (0, int(k)) if k.isdigit() else (1, k)


class Autopilot:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.laser_range = lambda: D['laser_range']      # bound per session: the world's laser range
        self.maps = lambda: (None, {})                    # bound per session: (current map, map -> names of the aliens that appear there)
        with profile.lock:
            self.d = profile.d.setdefault('autopilot', {'setting': '', 'state': STOP, 'start': 0, 'total_sec': 0, 'session': 0})
            self.d['state'] = STOP                        # new session: the client reports STOP on login

    # ------------------------------------------------------------ selections
    def selection(self):
        """Map-independent selection {npc: [NpcData], box: [name], npc_map: name -> maps it was selected on}. If missing from the earlier save,
        the union of the per-map lists."""
        s = self.d.get('choice')
        if s is None:
            s = {'npc': [], 'box': [], 'npc_map': {}}
            try:
                old = json.loads(self.d.get('setting') or '{}')
            except ValueError:
                old = {}
            self.merge(s, {}, old if isinstance(old, dict) else {})
            self.d['choice'] = s
        return s

    @staticmethod
    def merge(s, old, new):
        """Applies the saved settings' selections to the map-independent selection: each map's list is compared with what the client holds (what
        the server last sent or the client last saved); additions are selected, removals are dropped. The client changes only the map it is
        on; the others arrive unchanged, so they change nothing."""
        for field, key, store in ((NPC_LIST, _npc_key, 'npc'), (BOX_LIST, _box_key, 'box')):
            before = _maps(old.get(field))
            for mid, items in _maps(new.get(field)).items():
                prev = {key(e) for e in before.get(mid, [])}
                now = {key(e) for e in items}
                gone = prev - now
                if gone:
                    s[store] = [e for e in s[store] if key(e) not in gone]
                have = {key(e) for e in s[store]}
                for e in items:
                    k = key(e)
                    if k is None or k in prev:
                        continue
                    if k not in have:
                        s[store].append(e)
                        have.add(k)
                    if store == 'npc' and mid not in s['npc_map'].setdefault(k, []):
                        s['npc_map'][k].append(mid)

    def info_json(self, cur=None, names=None):
        """Settings to send to the client: the saved ones, with selection lists under every map's key (current map cur, then the maps with a
        selection, then the others; up to the limit). names: map -> names of the aliens that appear there. Empty if there are no settings at all
        (the client sets up its own defaults)."""
        names = names or {}
        text = self.d.get('setting') or ''
        s = self.selection()
        if not text and not s['npc'] and not s['box']:
            return ''
        try:
            base = json.loads(text) if text else {}
        except ValueError:
            base = {}
        base = base if isinstance(base, dict) else {}
        mine = {m for ms in s['npc_map'].values() for m in ms}           # maps with a selection first
        rest = set(names) | set(_maps(base.get(NPC_LIST))) | set(_maps(base.get(BOX_LIST)))
        order = ([cur] if cur else []) + sorted(mine - {cur}, key=_num) + sorted(rest - mine - {cur}, key=_num)
        npcs, boxes = {}, {}
        base[NPC_LIST], base[BOX_LIST] = npcs, boxes
        size = len(json.dumps(base, separators=(',', ':')))
        box_cost = len(json.dumps(s['box'], separators=(',', ':')))
        for mid in order:
            seen = set(names.get(mid, ())) | {k for k, ms in s['npc_map'].items() if mid in ms}
            row = [e for e in s['npc'] if _npc_key(e) in seen]
            cost = len(json.dumps(row, separators=(',', ':'))) + box_cost + 2 * len(mid) + 8
            if size + cost > LIMIT and mid != cur:
                continue
            npcs[mid], boxes[mid] = row, list(s['box'])
            size += cost
        return json.dumps(base, separators=(',', ':'))

    def info_cmd(self):
        # in single player everyone is Premium (it is sold for real money, no uridium equivalent): the recorded account's premium was false,
        # F12 said "You need to purchase the Premium Pack" (live test H72). A rule; the profile field is not consulted or written
        premium = True
        cur, names = self.maps()                          # the world's lock is taken before (outside) the profile's
        with self.p.lock:
            text = self.info_json(cur, names)
            if text != (self.d.get('setting') or ''):
                self.d['setting'] = text                     # what the client holds: the next save is compared with this
                self.p.dirty = True
        return 'AutopilotInfoCommand', dict(remainingSeconds=D['premium_sec'] if premium else 0, laserRange=int(self.laser_range()),
                                            result=premium, autopilotInfos=text)

    def handle(self, name, f, now=None):
        now = now or time.time()
        if name == 'AutopilotInfoRequest':
            return [self.info_cmd()]
        if name == 'AutopilotInfoSaveRequest':
            text = f.get('autopilotInfos') or ''
            try:
                new = json.loads(text) if text else None
                ok = True
            except ValueError:
                ok = False
            if ok:
                with self.p.lock:
                    s = self.selection()
                    try:
                        old = json.loads(self.d.get('setting') or '{}')
                    except ValueError:
                        old = {}
                    self.merge(s, old if isinstance(old, dict) else {}, new if isinstance(new, dict) else {})
                    self.d['setting'] = text
                    self.p.dirty = True
            self.log('   autopilot settings %s (%d characters)' % ('saved' if ok else 'invalid', len(text)))
            return [('AutopilotInfoSaveCommand', {'result': ok})]
        if name == 'AutopilotStatus':
            st = f.get('status')
            st = st.get('typeValue', st) if isinstance(st, dict) else st
            st = int(st or 0)
            with self.p.lock:
                if st == START and self.d['state'] != START:
                    self.d.update(state=START, start=now, session=self.d.get('session', 0) + 1)
                    self.log('   autopilot started')
                elif st == STOP and self.d['state'] == START:
                    dt = max(0, int(now - self.d.get('start', now)))
                    self.d.update(state=STOP, total_sec=self.d.get('total_sec', 0) + dt)
                    self.log('   autopilot stopped (%d s)' % dt)
                self.p.dirty = True
            return []
        return []
