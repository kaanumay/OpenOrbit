"""Mod geçişleri (yol haritası Aşama 8): Voyagers' Ascent ve Trinity Trials'ın puanlı ödül sıraları (istemcinin
porting.passevent.PassEventCommand'ı: VoyagersPassCommand, TrinityTrialsPassCommand).

Bir geçiş: seviyeler (her seviyenin puan eşiği), ücretsiz ve VIP sıranın ödülleri (seviye başına bir eşya). Puan modun
bitişlerinden gelir; seviyeye ulaşılınca ödül alınabilir (PassItemModule.statusType: 0 LOCK, 1 CLAIMED, 2 CLAIMABLE,
3 BELOW_LEVEL; istemcinin PassItemStatusType'ı). VIP geçiş mağazadan uridyumla (tek oyunculu kural); VIP sırası açılır, puanlar
'vip_puan' oranında artar. The mode's VIP badge (Trinity / Voyagers VIP Badge) in the inventory also opens the VIP track. Dönem takvim ayı: ay değişince puan, seviye ve alınanlar sıfırlanır (VIP de).
Profilde: gecisler {ad: {donem, puan, vip, alinan: {"n": [seviye], "v": [seviye]}}}.
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
    """data: {seviyeler: [eşik puan …] (seviye i+1 için toplam puan), ucretsiz: [[seviye, lootId, adet]], vip: [[…]],
    vip_puan: oran, vip_parametreler: [...]}."""

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
        if not s or s.get('donem') != period():
            s = g[self.name] = dict(donem=period(), puan=0, vip=False, claimed={'n': [], 'v': []})
            self.p.dirty = True
        return s

    def level(self):
        pts = self.st['puan']
        return sum(1 for t in self.D['seviyeler'] if pts >= t)

    def add(self, points):
        """Puan ekler (VIP oranıyla) -> eklenen."""
        s = self.st
        n = int(points * (1 + (self.D.get('vip_points', 0) if self.is_vip() else 0)))
        with self.p.lock:
            s['puan'] += n
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
        th = self.D['seviyeler']
        prev = th[cur - 1] if cur > 0 else 0
        nxt = th[cur] - prev if cur < len(th) else 0
        items = lambda rows, vip: [dict(_='PassItemModule', level=l, lootId=loot, amount=n, statusType=self.status(l, vip))
                                   for l, loot, n in rows]
        return (name, dict(isVip=self.is_vip(), normalItemList=items(self.D['free'], False), vipItemList=items(self.D['vip'], True),
                           currentLevel=cur, vipParams=list(self.D.get('vip_params', [])), remainSeconds=seconds_left(now),
                           nextLevelExp=nxt, currentExp=s['puan'] - prev))

    def claim(self, lvl, vip, grant):
        """Ödülü al (grant: lootId, adet -> mesajlar) -> mesajlar ya da None (alınamaz). lvl 0: iki sıranın alınabilir bütün
        ödülleri (istemci hangi ödüle tıklanırsa tıklansın rewardLevel 0, isVip false gönderir; canlı 2026-10-27)."""
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
