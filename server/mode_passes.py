"""Mode passes (roadmap Stage 8): the scored reward tracks of Voyagers' Ascent and Trinity Trials (the client's
porting.passevent.PassEventCommand: VoyagersPassCommand, TrinityTrialsPassCommand).

A pass: levels (each level's point threshold), the rewards of the free and VIP tracks (one item per level). Points come from the mode's
finishes; when a level is reached the reward can be claimed (PassItemModule.statusType: 0 LOCK, 1 CLAIMED, 2 CLAIMABLE,
3 BELOW_LEVEL; the client's PassItemStatusType). The VIP pass is bought in the shop with uridium (single-player rule); the VIP track opens, points
rise by the 'vip_points' ratio. The mode's VIP badge (Trinity / Voyagers VIP Badge) in the inventory also opens the VIP track. The period is the calendar month: when the month changes, points, level and claimed rewards reset (VIP too).
In the profile: passes {name: {period, points, vip, claimed: {"n": [level], "v": [level]}}}.
"""
import datetime, time

LOCK, CLAIMED, CLAIMABLE, BELOW_LEVEL = 0, 1, 2, 3


def period(now=None):
    return datetime.date.fromtimestamp(time.time() if now is None else now).strftime('%Y-%m')


def seconds_left(now=None):
    now = time.time() if now is None else now
    d = datetime.datetime.fromtimestamp(now)
    nxt = datetime.datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return max(0, int(nxt.timestamp() - now))


class Pass:
    """data: {levels: [threshold points …] (total points for level i+1), ucretsiz: [[level, lootId, count]], vip: [[…]],
    vip_points: ratio, vip_params: [...]}."""

    def __init__(self, profile, name, data, badge=None):
        self.p, self.name, self.D = profile, name, data
        self.badge = badge               # VIP badge lootId (e.g. resource_trinity-vip-badge): owning it unlocks the VIP track

    def is_vip(self):
        """VIP track open: bought (st['vip']) or the mode's VIP badge is in the inventory (kept, not consumed)."""
        return bool(self.st['vip']) or bool(self.badge and self.p.resource(self.badge) > 0)

    @property
    def st(self):
        g = self.p.d.setdefault('passes', {})
        s = g.get(self.name)
        if not s or s.get('period') != period():
            s = g[self.name] = dict(period=period(), points=0, vip=False, claimed={'n': [], 'v': []})
            self.p.dirty = True
        return s

    def level(self):
        pts = self.st['points']
        return sum(1 for t in self.D['levels'] if pts >= t)

    def add(self, points):
        """Adds points (with the VIP ratio) -> the amount added."""
        s = self.st
        n = int(points * (1 + (self.D.get('vip_points', 0) if self.is_vip() else 0)))
        with self.p.lock:
            s['points'] += n
            self.p.dirty = True
        return n

    def status(self, lvl, vip):
        s, cur = self.st, self.level()
        if lvl in s['claimed']['v' if vip else 'n']:
            return CLAIMED
        if lvl > cur:
            return BELOW_LEVEL
        if vip and not self.is_vip():
            return LOCK
        return CLAIMABLE

    def cmd(self, name, now=None):
        s, cur = self.st, self.level()
        th = self.D['levels']
        prev = th[cur - 1] if cur > 0 else 0
        nxt = th[cur] - prev if cur < len(th) else 0
        items = lambda rows, vip: [dict(_='PassItemModule', level=l, lootId=loot, amount=n, statusType=self.status(l, vip))
                                   for l, loot, n in rows]
        return (name, dict(isVip=self.is_vip(), normalItemList=items(self.D['free'], False), vipItemList=items(self.D['vip'], True),
                           currentLevel=cur, vipParams=list(self.D.get('vip_params', [])), remainSeconds=seconds_left(now),
                           nextLevelExp=nxt, currentExp=s['points'] - prev))

    def claim(self, lvl, vip, grant):
        """Claim the reward (grant: lootId, count -> messages) -> messages or None (cannot be claimed). lvl 0: all claimable rewards of both
        tracks (whichever reward is clicked, the client sends rewardLevel 0, isVip false; live 2026-10-27)."""
        if lvl == 0:
            out = [self.claim(r[0], v, grant) for v, rows in ((False, self.D['free']), (True, self.D['vip']))
                   for r in rows if self.status(r[0], v) == CLAIMABLE]
            return sum(out, []) if out else None
        if self.status(lvl, vip) != CLAIMABLE:
            return None
        row = next((r for r in self.D['vip' if vip else 'free'] if r[0] == lvl), None)
        if not row:
            return None
        with self.p.lock:
            self.st['claimed']['v' if vip else 'n'].append(lvl)
            self.p.dirty = True
        return grant(row[1], row[2])

    def buy_vip(self):
        with self.p.lock:
            self.st['vip'] = True
            self.p.dirty = True
