"""N.O.V.A. captains (roadmap stage 9; data data/new_systems.json 'nova' <- tools/new_systems.py, source darkorbitwiki).

The client's N.O.V.A. window (UINovaSystem; requests taken from the client's code): CaptainActionRequest {command, captainId, perkId,
upgradeLevel}
  getRosterList          -> CaptainRosterListCommand {captainList: [CaptainCommand]}
  getResources           -> CaptainGetResourcesBackCommand {lootId: Evocation Chip, amount}
  updateActiveCaptain    {captainId} -> CaptainUpdateActiveBackCommand {result, captainId, errorId}; only at the station ("You can
                         only change your N.O.V.A. at the station."). Toggle: the client's EQUIP and UNEQUIP buttons send the same request
                         (with the id of the selected N.O.V.A.); if the success response has the same id equipped it counts as unequipped
                         (CaptainData.UpdateEquipRosterData); on success the client asks for the list again
  dismissCaptain         {captainId} -> CaptainDismissBackCommand {result, captainId, errorId}: 50 Evocation Chip; not possible while equipped
  upgradePerk            {captainId, perkId, upgradeLevel (target + 1)} -> CaptainUpgradPerkBackCommand {result, captainId, perkId, level,
                         errorId}
                         (uridium + Evocation Chip; Calling Chip too in the U.P.S. sections)
CaptainCommand: captainName (first name) and captainTypeId (family; the client appends the 'captain_<family>_lastname' translation after the name),
perkList (CaptainPerkCommand: perkTypeId 'perk_<perk>' -> 'captain_perk_<perk>_fullname', perkModifier percent, perkDrain
energy/s, upgradLevelList value and cost per level), captainEnergy/maxEnergy, sellingPrice (chips when dismissed).

Rules (wiki): 100,000 U in the shop (random from the Neo or Eos section), at most 30 (beyond that 10,000 U), two random perks, base
value BASE I-VI, upgrade up to level 5. An equipped N.O.V.A. spends energy per second equal to the sum of its perks' costs;
if the energy is less than the cost the perks do not work. A resting (unequipped) N.O.V.A. gains 10 per second. Galaxy Gate perks work only on
gate maps (those with A/B/G on Alpha, Beta, Gamma).
In the profile: nova {roster: [{id, section, family, name, energy, t, skills: [{id, type, base, level}]}], active, next}.
"""
import json, os, random, threading, time

import inventory as INV
import galaxy_gates as KAPI
from legacy_protocol import stm

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['nova']
PERKS = D['skills']
CHIP, CALLING = D['chip'], D['calling_chip']
MAX_E, REGEN = D['max_energy'], D['rest_sec']
REQUESTS = {'CaptainActionRequest'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def value(kind, base, level):
    """The perk's value (%): base tier + increase per level."""
    t = PERKS[kind]
    return round(t['base'][base - 1] + t['increase'] * (level - 1), 2)


def where(map_id):
    """The map's place in the perks: 'abg' (Alpha/Beta/Gamma), 'gate' (other gates) or None."""
    g = KAPI.BY_MAP.get(int(map_id or 0))
    return None if not g else 'abg' if g in ('alpha', 'beta', 'gamma') else 'gate'


class Nova:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                              # shop (currency display); the session binds it
        self.at_station = lambda: True             # the session binds it: is the player at the station
        self.lock = threading.RLock()              # energy: player_profile.mods() is also called while the profile's lock is held (that lock is not re-entered)
        with profile.lock:
            self.d = profile.d.setdefault('nova', {'roster': [], 'active': 0, 'next': 1})
        self.resume()

    # ------------------------------------------------------------ energy
    def resume(self, now=None):
        """Session opened: the equipped N.O.V.A. does not spend during offline time (adaptation); resting ones filled up in that time."""
        c = self.active()
        if c:
            c['t'] = now or time.time()

    def drain(self, c):
        return sum(PERKS[y['type']]['spending'] for y in c['skills'])

    def update(self, c, now=None):
        now = now or time.time()
        dt = max(0.0, now - c.get('t', now))
        if c['id'] == self.d['active']:
            c['energy'] = max(0.0, c['energy'] - self.drain(c) * dt)
        else:
            c['energy'] = min(float(MAX_E), c['energy'] + REGEN * dt)
        c['t'] = now
        self.p.dirty = True
        return c['energy']

    def find(self, cid):
        return next((c for c in self.d['roster'] if c['id'] == int(cid or 0)), None)

    def active(self):
        return self.find(self.d['active']) if self.d['active'] else None

    def working(self, now=None):
        """The N.O.V.A. whose perks work (equipped and its energy exceeds its cost) or None."""
        c = self.active()
        if not c:
            return None
        with self.lock:
            e = self.update(c, now)
        return c if e > self.drain(c) else None

    def mods(self, map_id):
        """The equipped N.O.V.A.'s perks -> the profile's bonus keys (fraction); gate perks only on their own maps."""
        c = self.working()
        if not c:
            return {}
        here, out = where(map_id), {}
        for y in c['skills']:
            key, place = D['effects'].get(y['type'], (None, None))
            if key and (place == 'all' or place == here or (place == 'gate' and here == 'abg')):
                out[key] = out.get(key, 0) + value(y['type'], y['base'], y['level']) / 100.0
        return out

    def hud(self):
        """Energy on the gauge (ShipInitializationCommand captainEnergy/maxCaptainEnergy): the equipped N.O.V.A.'s, 0 if none."""
        c = self.active()
        if not c:
            return {'captainEnergy': 0, 'maxCaptainEnergy': 0}
        with self.lock:
            e = self.update(c)
        return {'captainEnergy': int(e), 'maxCaptainEnergy': MAX_E}

    def energy_cmd(self):
        """EnergyUpdateCommand: the N.O.V.A. energy on the gauge and its per-second cost."""
        c, h = self.active(), self.hud()
        return 'EnergyUpdateCommand', dict(maxCaptainEnergy=h['maxCaptainEnergy'], captainEnergyDrain=self.drain(c) if c else 0,
                                           currentCaptainEnergy=h['captainEnergy'])

    # ------------------------------------------------------------ edinme
    def new_captain(self, section, rng=random):
        info = D['sections'][section]
        pool = dict(info['skills'])
        perks = [rng.choices(list(pool), list(pool.values()))[0]]
        rest = {k: v for k, v in (pool if len(pool) > 1 else D['sections']['captain_captain-gen1-neo']['skills']).items()
                if k not in perks}
        while len(perks) < D['perk_count'] and rest:
            k = rng.choices(list(rest), list(rest.values()))[0]
            perks.append(k)
            rest.pop(k)
        with self.p.lock:
            cid = self.d['next']
            self.d['next'] = cid + 1
            c = {'id': cid, 'section': section, 'family': rng.choice(info['families']), 'name': rng.choice(D['names']), 'energy': float(MAX_E),
                 't': time.time(), 'skills': []}
            for i, k in enumerate(perks):
                tier = rng.choices(range(1, 7), D['base_weight'])[0]
                c['skills'].append({'id': cid * 10 + i + 1, 'type': k, 'base': tier, 'level': 1})
            self.d['roster'].append(c)
            self.p.dirty = True
        return c

    def hire(self, loot, n=1, rng=random):
        """Shop, Assembly, Battle Pass: captain_captain-generic (Neo or Eos) or the section itself. If the roster is full, 10,000 U."""
        msgs, extra = [], 0
        for _ in range(n):
            section = loot
            if loot in D['general']:
                w = D['general'][loot]
                section = rng.choices(list(w), list(w.values()))[0]
            if section not in D['sections']:
                self.log('   N.O.V.A.: unknown section %s' % loot)
                continue
            if len(self.d['roster']) >= D['max_roster']:
                extra += D['excess_uridium']
                continue
            c = self.new_captain(section, rng)
            self.log('   N.O.V.A. obtained: %s %s (%s; %s)' % (c['name'], c['family'], section, ', '.join(
                '%s %.1f%%' % (y['type'], value(y['type'], y['base'], 1)) for y in c['skills'])))
            msgs.append(stm('captain_received_s'))         # "Recruited: N.O.V.A." (not in flashres: CSTM; live test H64)
        if extra:
            self.p.gain(uridium=extra, reason='aktion_system_back')
            self.log('   N.O.V.A. roster full: %d U' % extra)
            msgs += self.m.money_msgs() if self.m else []
        return msgs

    # ------------------------------------------------------------ window
    def costs(self, c, level):
        row = next((r for r in D['upgrade'] if r['level'] == level), None)
        if not row:
            return {}
        need = {'currency_uridium': row['uridium'], CHIP: row['chip']}
        if D['sections'][c['section']].get('calling_chip'):
            need[CALLING] = row['calling_chip']
        return need

    def perk_cmd(self, c, y):
        # Client (CaptainPerkData, UINovaSystem.CreateCostTextItem): the list starts from the current level (it is cleared from the start when upgraded),
        # the cost of target T is the sum of the costLists of the list's first T-current entries (in order, with the same index), the row count from the target
        # entry's. That is, at entry L the L -> L+1 cost; at the top entry, for the types the cost of the previous one. Before, the list starting from 1
        # and the "reaching L" cost were sent: Total Cost stayed empty (live test H66)
        levels, top = [], D['max_level']
        for lv in range(y['level'], top + 1):
            nxt = self.costs(c, lv + 1) if lv < top else self.costs(c, lv)
            cost = [mod('CaptainPerkUpgradLevelCostCommand', lootId=k, amount=v) for k, v in nxt.items()]
            levels.append(mod('CaptainPerkUpgradLevelCommand', modifier=float(value(y['type'], y['base'], lv)), upgradeLevel=lv,
                              costList=cost))
        return mod('CaptainPerkCommand', perkModifier=float(value(y['type'], y['base'], y['level'])), perkId=y['id'],
                   perkTypeId='perk_' + y['type'], perkDrain=PERKS[y['type']]['spending'], levelMax=D['max_level'],
                   upgradLevelList=levels, level=y['level'])

    def captain_cmd(self, c):
        with self.lock:
            e = self.update(c)
        return mod('CaptainCommand', sellingPrice=D['release_chip'], isSelected=c['id'] == self.d['active'], sellItemObtained=CHIP,
                   captainTypeId=c['family'], captainName=c['name'], perkList=[self.perk_cmd(c, y) for y in c['skills']],
                   maxEnergy=MAX_E, captainId=c['id'], captainEnergy=int(e))

    def roster_cmd(self):
        return 'CaptainRosterListCommand', {'captainList': [self.captain_cmd(c) for c in self.d['roster']]}

    def chips_cmd(self):
        return 'CaptainGetResourcesBackCommand', {'amount': INV.count(self.p, CHIP), 'lootId': CHIP}

    def handle(self, f):
        from shop import stack_msg
        cmd, cid = f.get('command', ''), int(f.get('captainId') or 0)
        if cmd == 'getRosterList':
            return [self.roster_cmd()]
        if cmd == 'getResources':
            return [self.chips_cmd()]
        if cmd == 'updateActiveCaptain':
            err = None
            c = self.find(cid)
            if not self.at_station():
                err = 'captain_error_not_near_spacestation'
            elif cid and not c:
                err = 'captain_error_unhandled'
            if err:
                self.log('   N.O.V.A. unchanged: %s' % err)
                return [('CaptainUpdateActiveBackCommand', dict(result=False, captainId=cid, errorId=stack_msg(err)))]
            with self.lock:
                old = self.active()
                if old:
                    self.update(old)                       # the energy it spent; it rests from now on
                if c and old and old['id'] == c['id']:
                    c = None                               # the id of the equipped one arrived: UNEQUIP (live test H65; before, it equipped again)
                if c:
                    self.update(c)
                self.d['active'] = cid if c else 0
                self.p.dirty = True
            self.log('   N.O.V.A. %s' % ('equipped: %s %s' % (c['name'], c['family']) if c else 'unequipped'))
            return [('CaptainUpdateActiveBackCommand', dict(result=True, captainId=cid, errorId=None)), self.energy_cmd()] + self.stats()
        if cmd == 'dismissCaptain':
            c = self.find(cid)
            err = 'captain_popup_dismiss_active_nova' if c and cid == self.d['active'] else None if c else 'captain_error_unhandled'
            if err:
                return [('CaptainDismissBackCommand', dict(errorId=stack_msg(err), result=False, captainId=cid))]
            with self.p.lock:
                self.d['roster'].remove(c)
                self.p.dirty = True
            self.p.add_resource(CHIP, D['release_chip'])
            self.log('   N.O.V.A. dismissed: %s %s (+%d Evocation Chip)' % (c['name'], c['family'], D['release_chip']))
            return [('CaptainDismissBackCommand', dict(errorId=None, result=True, captainId=cid)), self.chips_cmd()]
        if cmd == 'upgradePerk':
            return self.upgrade(cid, int(f.get('perkId') or 0), int(f.get('upgradeLevel') or 0))
        self.log('   N.O.V.A.: unknown command %r' % cmd)
        return []

    def upgrade(self, cid, pid, target):
        from shop import stack_msg
        c = self.find(cid)
        y = next((x for x in (c or {}).get('skills', []) if x['id'] == pid), None)
        back = lambda ok, err=None, lv=0: ('CaptainUpgradPerkBackCommand', dict(
            errorId=stack_msg(err) if err else None, level=lv, perkId=pid, captainId=cid, result=ok))
        if not y:
            return [back(False, 'captain_error_unhandled')]
        if y['level'] + 1 > D['max_level']:
            return [back(False, 'captain_hangar_error_perk_lvl_cap', y['level'])]
        # upgradeLevel is the client's counter: level+1 on opening, each "+" raises it by one ("-" does not lower it; UINovaSystem.RefreshNotLevelInfo),
        # so the target chosen with "+" is + 1. Target = upgradeLevel - 1 (at most the maximum); if not greater than the current, one level. Before, it always
        # went up one level, while the window showed the total cost of the selected target (live test H67)
        nxt = max(y['level'] + 1, min(target - 1, D['max_level']))
        need = {}
        for lv in range(y['level'] + 1, nxt + 1):
            for k, v in self.costs(c, lv).items():
                need[k] = need.get(k, 0) + v
        if INV.spend(self.p, need, 'captain_perk_upgrade', y['type']) is None:
            return [back(False, 'captain_hangar_error_not_enough_resources', y['level'])]
        with self.p.lock:
            y['level'] = nxt
            self.p.dirty = True
        self.log('   N.O.V.A. %s: %s level %d (%.1f%%)' % (c['name'], y['type'], nxt, value(y['type'], y['base'], nxt)))
        return [back(True, None, nxt), self.chips_cmd()] + (self.m.money_msgs() if self.m else []) + self.stats()

    def stats(self):
        """Values such as cargo and speed change with N.O.V.A.: the ship's values again (shop); the hint in the player box."""
        return (self.m.apply_stats() if self.m else []) + [self.perk_update_cmd()]

    def perk_update_cmd(self):
        """The N.O.V.A. hint in the player box (Ö1): ActivePerkUpdateCommand {activePerkModuleList [ActivePerkModule {perkTypeId,
        modifierValue}]}; the client builds each row from ttip_captain_<perkTypeId>_description with %VALUE% (ActivePerkUpdateCommandHandler;
        it makes those containing "evasion" negative). An empty list if no N.O.V.A. is equipped."""
        c = self.active()
        rows = [mod('ActivePerkModule', perkTypeId='perk_' + y['type'], modifierValue=float(value(y['type'], y['base'], y['level'])))
                for y in (c['skills'] if c else [])]
        return 'ActivePerkUpdateCommand', {'activePerkModuleList': rows}
