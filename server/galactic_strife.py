"""Galactic Strife: the PvP reputation event on 4-1..4-4 (data: data/extra_events.json 'galactic_strife').

Rules (darkorbitwiki events/galactic-strife, 2026-09-16; client texts galacticStrife_*):
  everyone starts the event with 500 reputation; a PvP kill on a Galactic Strife map moves reputation from the loser to the winner; only the top 2
  damage dealers who dealt at least 15% gain, in proportion to their share; the first 10 different victims of the day give x1.5 (the winner's gain
  only); a victim of the same clan gives and loses nothing; pilots below level 6 neither gain nor lose. Milestones 750 / 1,000 / 1,250 / 1,500 and every
  250 after pay a reward the first time. Reputation Fever (Mon-Fri 19-21, Sat-Sun 13-15 and 19-21): the gain is doubled, the loss is not, repairs
  are free (client tooltip galacticStrife_tab_overview_fever_ttip).
Adaptation (not published): the per-kill amount, Elo-like (see the data's _adaptation); bot players keep their reputation in their own profile
  and play by the same rules against the pilot.
Client (window pvp_summer, UIPvpSummerSystem):
  PVPSummerEventInfoCommand {perKillRanges, timeToEndFever, timeToNextFever (s), reputationUpdateCommand
    PVPSummerEventSelfReputationUpdateCommand {reputation, repPerKill, nextMilestone}, reputationRanges [RankRewardRangeModule], shuffleInfoCommand
    {timeToNextShuffle (s)}}; on opening the window RewardContentRequest -> RewardContentCommand {rewardType 0 PVP_SUMMER_EVENT_MILESTONE, the next
    milestone's rewards}; the reward tab RankRewardRequest {ranking, rankType 3 REPUTATION | 4 PER_KILL}.
  PVPSummerEventReputationUpdateCommand {uid, reputation}: the reputation and its badge under a ship's name (UnitDataComponentSystem: shown when >= 0).
  perKillRanges stays empty: no reward per reputation-per-kill band is published.
In the profile: galactic_strife {period, rep, paid (highest milestone paid), day, unique [names], victims {name: n}, losses [t]}.
"""
import json, math, os, time

import event_calendar as CAL
import map_links as H
import rankings as RK
from legacy_protocol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('galactic_strife', {})
EVENT = D.get('event', 'galactic_strife')
MAPS = tuple(D.get('maps', ()))
RANK_REP, RANK_PER_KILL = 3, 4                # RankRewardRequest.RankType PVP_SUMMER_EVENT_REPUTATION / _PER_KILL
MILESTONE_REWARD = 0                          # RewardContentRequest.RewardType PVP_SUMMER_EVENT_MILESTONE
LABEL_SEC = 2.0
VM_FLUX, VM_MIRE, VM_MIRE_TARGET, VM_PVP_PROTECTION = 118, 119, 120, 79      # VisualModifierCommand.modifier (the client's enum)
CRATE_LIFE = 0                                # crates stay until taken


def mod(name, **f):
    f['_'] = name
    return f


def active(now=None):
    return bool(D) and CAL.is_active(EVENT, now)


def on_map(map_id):
    try:
        return H.name(int(map_id)) in MAPS
    except (TypeError, ValueError):
        return False


def milestones(upto=None):
    """[(milestone, rewards)] in order: the fixed ones, then every step after the last (as many as the window shows)."""
    fixed = sorted((int(k), v) for k, v in D.get('milestones', {}).items() if k.isdigit())
    out = list(fixed)
    step, last = D.get('milestone_step', 250), fixed[-1][0] if fixed else 500
    while len(out) < D.get('milestone_rows', 8) or (upto is not None and out[-1][0] < upto):
        last += step
        out.append((last, D['milestones']['every']))
    return out


def next_milestone(rep):
    return next(m for m, _ in milestones(rep + 1) if m > rep)


def _table():
    rows = milestones()
    return {'ranges': [dict(from_=m, e=(rows[i + 1][0] - 1 if i + 1 < len(rows) else m + D.get('milestone_step', 250) - 1),
                            items=items, title=None) for i, (m, items) in enumerate(rows)]}


if D:
    RK.TABLES[RANK_REP] = _table()               # the REPUTATION column of the reward tab (milestone rewards per band)


def period_key(now=None):
    p = CAL.period(EVENT, now)
    return int(p[0]) if p else 0


def state(p, now=None):
    st = p.d.setdefault('galactic_strife', {})
    key = period_key(now)
    if st.get('period') != key:                  # a new event: reputation from 500 again
        st.clear()
        st.update(period=key, rep=D.get('start', 500), paid=D.get('start', 500), day='', unique=[], victims={}, losses=[])
        p.dirty = True
    day = time.strftime('%Y-%m-%d', time.localtime(now or time.time()))
    if st.get('day') != day:                     # the unique-victim list and the repeat counters reset at 00:00 (local)
        st.update(day=day, unique=[], victims={})
    return st


def rep(p, now=None):
    return int(state(p, now)['rep'])


def fever_times(now=None):
    """(seconds to the end of the fever running now or 0, seconds to the next fever)."""
    now = time.time() if now is None else now
    f = D.get('fever', {})
    iv = []
    t0 = time.localtime(now)
    midnight = time.mktime((t0.tm_year, t0.tm_mon, t0.tm_mday, 0, 0, 0, 0, 0, -1))
    for d in range(0, 8):
        base = midnight + d * 86400
        wd = time.localtime(base + 3600).tm_wday
        for a, b in f.get('weekend' if wd >= 5 else 'weekday', []):
            iv.append((base + a * 3600, base + b * 3600))
    cur = next((e for s, e in iv if s <= now < e), None)
    nxt = next((s for s, e in iv if s > now), None)
    return (int(cur - now) if cur else 0), (int(nxt - now) if nxt else 0)


def fever(now=None):
    return fever_times(now)[0] > 0


def expected(a, b):
    return 1.0 / (1.0 + 10 ** ((b - a) / 400.0))


def base_amount(winner, loser):
    """The per-kill reputation between two reputations (adaptation: Elo-like, see the data's _adaptation)."""
    if winner - loser > D.get('max_gap', 400):
        return 0
    return int(round(2 * D.get('k', 20) * (1 - expected(winner, loser))))


def per_kill(p, now=None):
    """The window's "Reputation Per Kill": the gain against an opponent of the same reputation now (fever doubles it)."""
    return base_amount(rep(p, now), rep(p, now)) * (2 if fever(now) else 1)


def _name(p):
    return str(p.d['pilot'].get('userName', ''))


def _clan(p):
    return int(p.d['pilot'].get('clanId') or 0)


def settle(winners, loser, now=None):
    """A PvP kill on a Galactic Strife map. winners: [(profile, share)] of the damage dealers (players and bots), loser: profile.
    -> {profile: change} (the gains and the loss)."""
    now = time.time() if now is None else now
    out = {}
    lst = state(loser, now)
    lrep = lst['rep']
    rated = lambda q: q.d['pilot'].get('level', 1) >= D.get('rated_level', 6)
    top = sorted(((w, s) for w, s in winners if s >= D.get('min_share', 0.15)), key=lambda ws: -ws[1])[:D.get('top', 2)]
    lost = 0
    for w, share in top:
        if w is loser or (_clan(w) and _clan(w) == _clan(loser)):
            continue                              # the same clan: neither gain nor loss
        wst = state(w, now)
        base = base_amount(wst['rep'], lrep)
        lost = max(lost, base)
        if not rated(w) or not base:
            continue
        n = wst['victims'].get(_name(loser), 0)
        gain = base * min(1.0, share) / (1 + n)
        if _name(loser) not in wst['unique'] and len(wst['unique']) < D.get('unique_count', 10):
            wst['unique'].append(_name(loser))
            gain *= D.get('unique_bonus', 1.5)
        if fever(now):
            gain *= 2
        gain = int(round(gain))
        wst['victims'][_name(loser)] = n + 1
        wst['rep'] += gain
        w.dirty = True
        out[w] = gain
    if lost and rated(loser):
        lst['rep'] = max(0, lrep - lost)
        lst['losses'] = [t for t in lst.get('losses', []) if now - t < D.get('loss_window_sec', 3600)] + [now]
        loser.dirty = True
        out[loser] = -lost
    return out


def shares(damage):
    """{who: damage} -> [(who, share)]."""
    total = float(sum(damage.values())) or 1.0
    return [(k, v / total) for k, v in damage.items()]


class GalacticStrife:
    REQUESTS = ('RewardContentRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.world = None
        self.taken = {}             # damage taken by the hero while alive: ('p', hid) | ('b', bot uid) -> amount
        self.sent_rep = None        # the reputation last sent to the client
        self.labels = {}            # unit id -> reputation shown under its name
        self.next_label = 0.0
        self.change_map = None      # the session binds: (map, portal, position)
        self.next_shuffle = 0.0
        self.crates = {}            # box hash -> kind (this map's Flux/Mire crates)
        self.crate_due = []         # [(time, kind)] crates to place again
        self.protect_end = 0.0      # PvP protection running (spawn 5 s, loss streak 60 min): its end
        self.protect_from = 0.0

    # ------------------------------------------------------------ client
    def info_cmd(self, now=None):
        now = time.time() if now is None else now
        st = state(self.p, now)
        to_end, to_next = fever_times(now)
        return ('PVPSummerEventInfoCommand', dict(
            perKillRanges=[], timeToEndFever=to_end, timeToNextFever=to_next, reputationUpdateCommand=self.self_cmd(now)[1],
            reputationRanges=RK.ranges(RANK_REP), shuffleInfoCommand=mod('PVPSummerEventShuffleInfoCommand',
                                                                        timeToNextShuffle=self.shuffle_left(now))))

    def self_cmd(self, now=None):
        st = state(self.p, now)
        return ('PVPSummerEventSelfReputationUpdateCommand', mod('PVPSummerEventSelfReputationUpdateCommand', reputation=int(st['rep']),
                                                                repPerKill=per_kill(self.p, now), nextMilestone=next_milestone(int(st['rep']))))

    def shuffle_left(self, now=None):
        now = time.time() if now is None else now
        step = D.get('shuffle_sec', 1800)
        return int(step - (now % step))

    def login_msgs(self):
        return [self.info_cmd()] if active() else []

    def window(self, item):
        return [self.info_cmd()] if item == 'pvp_summer' and active() else []

    def handle(self, name, f):
        if name == 'RewardContentRequest' and active():
            nxt = next_milestone(rep(self.p))
            items = dict(milestones(nxt)).get(nxt, [])
            return [('RewardContentCommand', dict(rewardType=MILESTONE_REWARD,
                                                  rewardContentModuleList=[mod('RewardModule', lootId=l, amount=a) for l, a in items]))]
        return []

    # ------------------------------------------------------------ world
    def attach(self, world):
        self.world = world
        self.taken = {}
        world.damage_hooks.append(self.on_damage)
        world.death_hooks.append(self.on_death)
        world.collect_hooks.append(self.collect)
        world.free_repair = lambda: active() and fever() and on_map(world.map_id)
        self.labels, self.crates, self.crate_due = {}, {}, []
        self.next_shuffle = self.shuffle_at(time.time())
        if not self.here():
            self.protect_end = 0.0
            return []
        now = time.time()
        st = state(self.p, now)
        world.later(1.0, self.place_crates)
        until = max(now + D.get('spawn_protection_sec', 5), st.get('protect_until', 0))     # entering / respawning on the maps
        world.later(1.5, lambda: self.protect(until))
        return []

    # ------------------------------------------------------------ PvP protection
    def protect(self, until):
        """PvP protection until 'until' (wiki: 5 s after spawning or a shuffle; 60 min after 3 losses within 60 min up to level 17):
        players and bots cannot attack (world.invuln_until; aliens still can), the client's PVP_PROTECTION look on the ship."""
        w = self.world
        if w is None or w.hero_dead:
            return
        w.invuln_until = max(w.invuln_until, until)
        self.protect_end, self.protect_from = until, time.time()
        w.send([self.protect_look(True)])

    def protect_look(self, on):
        return ('VisualModifierCommand', dict(userId=self.world.hid, modifier=VM_PVP_PROTECTION, attribute=0, additionalAttribute='',
                                              count=0, activated=on))

    def protect_step(self, now):
        """The protection ends: its time is up, the pilot fired at a player/bot (wiki: also special ammo or tech), or left the maps."""
        w = self.world
        if not self.protect_end:
            return []
        shot = getattr(w, 'last_pvp', 0) > self.protect_from + 0.5
        if now < self.protect_end and not shot and self.here():
            return []
        if w.invuln_until <= self.protect_end + 0.01:
            w.invuln_until = min(w.invuln_until, now)
        if shot or not self.here():
            state(self.p, now)['protect_until'] = 0
        self.protect_end = 0.0
        return [self.protect_look(False)]

    # ------------------------------------------------------------ shuffle
    def shuffle_at(self, now):
        step = D.get('shuffle_sec', 1800)
        return (now // step + 1) * step

    def shuffle(self, now):
        """Every 30 min the pilots on the Galactic Strife maps are moved to a random one of them, at a random place (wiki)."""
        import random
        w = self.world
        if not self.change_map or w.hero_dead or w.jumping:
            return
        maps = [m for m in H.NAMES if on_map(m) and str(m) != str(w.map_id)] or [int(w.map_id)]
        dest = random.choice(maps)
        x, y = H.random_arrival(dest)
        self.log('   Galactic Strife: shuffle -> %s' % H.name(dest))
        self.change_map(dest, None, (x, y))

    # ------------------------------------------------------------ Flux / Mire crates
    def place_crates(self):
        w = self.world
        if w is None or not self.here():
            return
        import random
        have = {}
        for h, kind in list(self.crates.items()):
            if h in w.boxes:
                have[kind] = have.get(kind, 0) + 1
            else:
                del self.crates[h]
        for kind, n in D.get('crates', {}).items():
            for _ in range(n - have.get(kind, 0)):
                x, y = H.random_arrival(int(w.map_id))
                h = w.drop_box(kind, x + random.randint(-1500, 1500), y + random.randint(-1000, 1000), {}, CRATE_LIFE)
                w.boxes[h]['no_pet'] = True               # the P.E.T. auto looter cannot pick them up (wiki)
                self.crates[h] = kind

    def collect(self, w, h, b, by_pet):
        kind = self.crates.get(h)
        if kind is None:
            return None
        if by_pet:
            return False
        now = time.time()
        msgs = []
        vm = lambda uid, m, a, on: ('VisualModifierCommand', dict(userId=uid, modifier=m, attribute=int(a), additionalAttribute='', count=0,
                                                                  activated=on))
        if kind == 'FLUX_CRATE':
            if any(e['source'] == 'gs_flux' for e in w.hero_effects.get('skill', now)):
                return False                              # already boosted: cannot be picked up (wiki)
            f = D['flux']
            speed = w.p.d['ship'].get('speed', 0) or 1
            boost = max(0.0, min(f['speed'], f['cap'] / float(speed) - 1))       # not above the 750 cap (wiki)
            w.hero_effect('skill', f['duration_sec'], {'mods': {'speed': boost}}, source='gs_flux')
            msgs.append(vm(w.hid, VM_FLUX, f['duration_sec'], True))      # attribute: the HUD's seconds (CrateHUDEffect)
            w.later(f['duration_sec'], lambda: w.send([vm(w.hid, VM_FLUX, 0, False)]))
        else:
            m = D['mire']
            hx, hy = w.hero_pos(now)
            msgs.append(vm(w.hid, VM_MIRE, m['radius'], True))           # attribute: the ring's radius
            hit = []
            for n in list(w.npcs.values()):
                if (n.alive and getattr(n, 'bot', None) is not None and not w.is_group_member(n.bot.uid)
                        and math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= m['radius']):
                    n.effect.remove('slow', source='gs_mire')        # does not stack; the timer resets (wiki)
                    n.effect.add('slow', m['duration_sec'], m['slow'], 'gs_mire', now)
                    hit.append(n.id)
            for o in (w.shared.members if w.shared else []):
                if (o is not w and o.running and o.map_id == w.map_id and not w.is_group_member(o.hid)
                        and math.hypot(o.hero_pos(now)[0] - hx, o.hero_pos(now)[1] - hy) <= m['radius']):
                    o.hero_effects.remove('slow', source='gs_mire')
                    o.hero_effect('slow', m['duration_sec'], m['slow'], source='gs_mire')
                    hit.append(o.hid)
            msgs += [vm(uid, VM_MIRE_TARGET, 0, True) for uid in hit]
            w.later(m['duration_sec'], lambda: w.send([vm(uid, VM_MIRE_TARGET, 0, False) for uid in hit]))
        del w.boxes[h]
        self.crates.pop(h, None)
        self.crate_due.append((now + D.get('crate_respawn_sec', 60), kind))
        w.send(msgs + [w.beam_msg(False), ('RemoveCollectableCommand', {'collected': True, 'hash': h})])
        self.log('   Galactic Strife: %s' % kind)
        return True

    def here(self):
        w = self.world
        return w is not None and active() and on_map(w.map_id)

    def on_damage(self, w, dmg, killer, source_player):
        if not self.here():
            return
        if source_player is not None:
            key = ('p', source_player.hid)
        elif killer is not None and getattr(killer, 'bot', None) is not None:
            key = ('b', killer.bot.uid)
        else:
            return
        self.taken[key] = self.taken.get(key, 0) + dmg

    def profile_of(self, key):
        kind, uid = key
        w = self.world
        if kind == 'p':
            o = w.player(uid) if w else None
            return o.p if o is not None else None
        import bot.manager as MGR
        import bot.society as T
        y = MGR.ACTIVE
        b = next((b for b in (y.bots if y else ()) if b.uid == uid), None)
        return T.profile(b) if b is not None else None

    def on_death(self, w, killer, source_player):
        """The hero was destroyed on a Galactic Strife map: the damage dealers gain, the hero loses."""
        taken, self.taken = self.taken, {}
        self.protect_end = 0.0
        if not self.here() or not (source_player is not None or getattr(killer, 'bot', None) is not None):
            return []
        winners = [(self.profile_of(k), s) for k, s in shares(taken)]
        changes = settle([(q, s) for q, s in winners if q is not None], self.p)
        st, now = state(self.p), time.time()
        if (changes.get(self.p, 0) < 0 and self.p.d['pilot'].get('level', 1) <= D.get('loss_protection_max_level', 17)
                and len([t for t in st.get('losses', []) if now - t < D.get('loss_window_sec', 3600)]) >= D.get('loss_streak', 3)):
            st['protect_until'] = now + D.get('loss_protection_sec', 3600)      # 3 losses within 60 min: 60 min protection (wiki)
            st['losses'] = []
            self.log('   Galactic Strife: 60 min PvP protection (3 losses)')
        self.log('   Galactic Strife: destroyed, reputation %+d -> %d' % (changes.get(self.p, 0), rep(self.p)))
        return self.update_msgs()

    def on_kill(self, w, n, x, y):
        """The hero destroyed a bot ship on a Galactic Strife map (world.kill_hooks)."""
        if not self.here() or getattr(n, 'bot', None) is None:
            return []
        import bot.society as T
        dmg = {k: v for k, v in n.__dict__.get('pvp_damage', {}).items() if v > 0}
        if not dmg:
            dmg = {('p', w.hid): 1}                  # no damage on record (a P.E.T. or a technology finished it): the killer alone
        winners = [(self.p if k == ('p', w.hid) else self.profile_of(k), s) for k, s in shares(dmg)]
        changes = settle([(q, s) for q, s in winners if q is not None], T.profile(n.bot))
        self.log('   Galactic Strife: %s destroyed, reputation %+d -> %d' % (n.bot.name, changes.get(self.p, 0), rep(self.p)))
        self.labels.pop(n.id, None)
        return self.update_msgs()

    def update_msgs(self, now=None):
        """The pilot's reputation changed: the window, the label under the ship and the milestone rewards reached for the first time."""
        now = time.time() if now is None else now
        st = state(self.p, now)
        msgs = [self.self_cmd(now), ('PVPSummerEventReputationUpdateCommand', dict(uid=self.world.hid if self.world else 0,
                                                                                  reputation=int(st['rep'])))]
        self.sent_rep = int(st['rep'])
        for m, items in milestones(int(st['rep'])):
            if st['paid'] < m <= st['rep']:
                with self.p.lock:
                    st['paid'] = m
                    self.p.dirty = True
                for l, a in items:
                    msgs += self.m.reward(l, a) if self.m else []
                self.log('   Galactic Strife: milestone %d reached' % m)
        return msgs

    def tick(self, now):
        w = self.world
        if w is None:
            return []
        msgs = self.protect_step(now)
        if self.here():
            if now >= self.next_shuffle:
                self.next_shuffle = self.shuffle_at(now)
                self.shuffle(now)
                return msgs
            if any(t <= now for t, k in self.crate_due):
                self.crate_due = [(t, k) for t, k in self.crate_due if t > now]
                self.place_crates()
        if now < self.next_label:
            return msgs
        self.next_label = now + LABEL_SEC
        if not self.here():
            if self.labels:                       # left the maps or the event ended: the labels go (a negative value hides them)
                msgs = [('PVPSummerEventReputationUpdateCommand', dict(uid=uid, reputation=-1)) for uid in self.labels]
                self.labels = {}
            return msgs
        if self.sent_rep != rep(self.p):
            msgs += self.update_msgs(now)         # changed elsewhere (killed another player's ship: their session settled it)
        import bot.society as T
        want = {w.hid: rep(self.p)}
        for n in list(w.npcs.values()):
            if n.alive and getattr(n, 'bot', None) is not None and n.id in w.visible:
                want[n.id] = rep(T.profile(n.bot), now)
        for o in (w.shared.members if w.shared else []):
            if o is not w and o.running and o.map_id == w.map_id:
                want[o.hid] = rep(o.p, now)
        msgs += [('PVPSummerEventReputationUpdateCommand', dict(uid=uid, reputation=r)) for uid, r in want.items()
                 if self.labels.get(uid) != r]
        self.labels = want
        return msgs
