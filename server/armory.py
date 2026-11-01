"""Armory Unlock (yol haritası Aşama 9; veri data/new_systems.json 'armory' <- tools/new_systems.py; havuzlar ve birikimli
ödüller kayıttaki ArmoryUnlockInfoCommand'dan, kurallar resmî forumun SSS'inden).

İstemcinin penceresi (UIArmoryUnlockSystem; istekler istemcinin kodundan):
  ArmoryUnlockInfoRequest                   -> ArmoryUnlockInfoCommand {normal, specials (3 gemi), claimInfoGroupCommands,
                                               selectedClaimInfoGroupCommand, selectedGroup, canReset, eventRemainSeconds}
  ArmoryUnlockDrawRequest {count, type}     type 1 Lucky Draw (Armory Token), 2 Limited Time Mega Draw (Mega Armory Token); çekiliş
                                               başına bir jeton -> ArmoryUnlockDrawCommand {count, type, rewardModuleList} + bilgi
  ArmoryUnlockSelectGroupRequest {group}    Mega Draw'da gemi kilitlenir ("Lock Ship to Draw"); birikimli ödüllerin hepsi alınmadan
                                               değişmez
  ArmoryUnlockClaimRequest {index}          birikimli ödül (Mega Draw sayısıyla) -> ArmoryUnlockClaimCommand {claimed, index}
Mega Draw dönemi 3 gün: listede üç gemi (istemcinin UL toplarının gemileri, sırayla), havuz dönemden döneme Helios ya da Nidhogg.
1.200 çekilişe ulaşıp ödülü alınmamış basamak varken çekiliş olmaz ("Claim your Cumulative Rewards first!").
Profilde: armory {kilit: {gemi, top, cekilis, alinan: [index]} | None, lucky: toplam, mega: toplam}.
"""
import json, os, random, time

import inventory as INV

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['armory']
TOKEN, MEGA = D['jeton'], D['mega_jeton']
LUCKY, SPECIAL = 1, 2
PERIOD = D['donem_gun'] * 86400
EPOCH = 1767225600                       # 2026-01-01 00:00 UTC: dönemlerin başlangıcı (uyarlama)
REQUESTS = {'ArmoryUnlockInfoRequest', 'ArmoryUnlockDrawRequest', 'ArmoryUnlockSelectGroupRequest', 'ArmoryUnlockClaimRequest'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def period(now=None):
    """-> (dönem no, bitişe kalan sn)."""
    t = (now or time.time()) - EPOCH
    n = int(t // PERIOD)
    return n, int(PERIOD - (t - n * PERIOD))


def rotation(now=None):
    """Bu dönemin üç gemisi ve topu (çift dönem Helios, tek Nidhogg)."""
    n, _ = period(now)
    ships = D['gemiler']
    return [ships[(n * 3 + i) % len(ships)] for i in range(3)], 'helios' if n % 2 == 0 else 'nidhogg'


def fill(loot, ship, ball):
    """Şablondaki gemiye özgü satır ve havuzun topu: ul-{top}-{gemi}; Nidhogg döneminde Helios eşyaları Nidhogg karşılıklarıyla."""
    s = loot.replace('{top}', ball).replace('{gemi}', ship)
    if ball == 'nidhogg':
        for a, b in D['cevir_nidhogg']:
            s = s.replace(a, b)
    return s


class Armory:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                              # mağaza (ödüller, para); oturum bağlar
        with profile.lock:
            self.d = profile.d.setdefault('armory', {'kilit': None, 'lucky': 0, 'mega': 0})

    # ------------------------------------------------------------ durum
    def groups(self, now=None):
        """Mega Draw'daki üç gemi -> [(gemi, top)]: kilitli gemi dönemde yoksa ilk sıraya o (dönem bitince de kilit kalır)."""
        ships, ball = rotation(now)
        out = [(s, ball) for s in ships]
        k = self.d['kilit']
        if k and (k['gemi'], k['top']) not in out:
            out = [(k['gemi'], k['top'])] + out[:2]
        return out

    def selected(self, now=None):
        k = self.d['kilit']
        if not k:
            return 0
        return next((i + 1 for i, g in enumerate(self.groups(now)) if g == (k['gemi'], k['top'])), 0)

    def claims(self, ship, ball):
        k = self.d['kilit']
        mine = bool(k) and (k['gemi'], k['top']) == (ship, ball)
        n = min(k['cekilis'], D['birikimli'][-1][1]) if mine else 0
        out = []
        for idx, need, loot, amount, special in D['birikimli']:
            got = mine and idx in k['alinan']
            out.append(mod('ArmoryUnlockClaimInfoCommand', claimed=got, special=special, index=idx, canClaim=mine and not got and n >= need,
                           currentProgress=n, desc='', lootId=fill(loot, ship, ball), progressQuantity=need, lootAmount=amount))
        return out

    def all_claimed(self):
        k = self.d['kilit']
        return not k or all(row[0] in k['alinan'] for row in D['birikimli'])

    def show_list(self, rows, group, ship='', ball='helios', res=TOKEN):
        show = [mod('ArmoryUnlockLootShowCommand', lootAmount=a, bg=bg, lootId=fill(l, ship, ball), showShipIcon=icon, line=line)
                for l, a, bg, line, icon in rows['goster']]
        prob = [mod('LootProbabilityModule', maxLootAmount=hi, minLootAmount=lo, probabilityPercentage=float(pc), lootId=fill(l, ship, ball))
                for l, lo, hi, pc in rows['olasilik']]
        return mod('ArmoryUnlockLootShowListCommand', showLootCommandList=show, group=group, claimInfoCommandList=[],
                   shipLootId='ship_' + ship if ship else '', probabilityModuleList=prob, resourceLootId=res,
                   resourceAmount=INV.count(self.p, res))

    def info_cmd(self, now=None):
        groups = self.groups(now)
        sel = self.selected(now)
        return 'ArmoryUnlockInfoCommand', dict(
            normal=self.show_list(D['normal'], 1),
            specials=[self.show_list(D['mega'], i + 1, s, t, MEGA) for i, (s, t) in enumerate(groups)],
            claimInfoGroupCommands=[mod('ArmoryUnlockClaimInfoGroupCommand', claimInfoCommandList=self.claims(s, t), group=i + 1)
                                    for i, (s, t) in enumerate(groups)],
            selectedClaimInfoGroupCommand=self.claims(*groups[sel - 1]) if sel else [],
            canReset=self.all_claimed(), eventRemainSeconds=period(now)[1], selectedGroup=sel)

    # ------------------------------------------------------------ istekler
    def handle(self, name, f):
        if name == 'ArmoryUnlockInfoRequest':
            return [self.info_cmd()]
        if name == 'ArmoryUnlockSelectGroupRequest':
            return self.select(int(f.get('group') or 0))
        if name == 'ArmoryUnlockDrawRequest':
            return self.draw(int(f.get('count') or 1), int(f.get('type') or LUCKY))
        if name == 'ArmoryUnlockClaimRequest':
            return self.claim(int(f.get('index') or 0))
        return []

    def select(self, group, now=None):
        from legacy_protocol import legacy
        groups = self.groups(now)
        if not 1 <= group <= len(groups):
            return [self.info_cmd(now)]
        ship, ball = groups[group - 1]
        k = self.d['kilit']
        if k and (k['gemi'], k['top']) != (ship, ball) and not self.all_claimed():
            self.log('   Armory: gemi değişmez, birikimli ödüller alınmadı (%s)' % k['gemi'])
            return [legacy('0|A|STM|armoryunlock_draw_prompt'), self.info_cmd(now)]
        if not k or (k['gemi'], k['top']) != (ship, ball):
            with self.p.lock:
                self.d['kilit'] = {'gemi': ship, 'top': ball, 'cekilis': 0, 'alinan': []}
                self.p.dirty = True
            self.log('   Armory: Mega Draw gemisi %s (%s)' % (ship, ball))
        return [self.info_cmd(now)]

    def pick(self, rows, ship, ball, rng):
        loot, lo, hi, _ = rng.choices(rows, [r[3] for r in rows])[0]
        return fill(loot, ship, ball), rng.randint(int(lo), int(hi))

    def draw(self, count, kind, now=None, rng=random):
        from legacy_protocol import legacy
        count = 10 if count >= 10 else 1
        res = MEGA if kind == SPECIAL else TOKEN
        k = self.d['kilit']
        if kind == SPECIAL:
            if not k:
                self.log('   Armory: Mega Draw için gemi kilitlenmedi')
                return [self.info_cmd(now)]
            top_n = D['birikimli'][-1][1]
            if k['cekilis'] >= top_n and not self.all_claimed():
                return [legacy('0|A|STM|armoryunlock_draw_prompt'), self.info_cmd(now)]
        if INV.count(self.p, res) < count:
            self.log('   Armory: jeton yetmiyor (%s %d < %d)' % (res, INV.count(self.p, res), count))
            return [legacy('0|A|STM|ttip_not_enough_resources'), self.info_cmd(now)]
        INV.spend(self.p, {res: count}, 'armory_unlock_draw')
        rows = D['mega']['olasilik'] if kind == SPECIAL else D['normal']['olasilik']
        ship, ball = (k['gemi'], k['top']) if kind == SPECIAL else ('', 'helios')
        got = [self.pick(rows, ship, ball, rng) for _ in range(count)]
        with self.p.lock:
            if kind == SPECIAL:
                k['cekilis'] += count
                self.d['mega'] += count
            else:
                self.d['lucky'] += count
            self.p.dirty = True
        total = {}
        for loot, n in got:
            total[loot] = total.get(loot, 0) + n
        msgs = [('ArmoryUnlockDrawCommand', dict(count=count, type=kind,
                                                 rewardModuleList=[mod('RewardModule', lootId=l, amount=n) for l, n in got]))]
        for loot, n in total.items():
            msgs += self.m.reward(loot, n) if self.m else []
            if not self.m:
                self.p.add_resource(loot, n)
        self.log('   Armory %s x%d: %s' % ('Mega Draw' if kind == SPECIAL else 'Lucky Draw', count,
                                          ', '.join('%s x%d' % (l.rsplit('_', 1)[-1], n) for l, n in total.items())))
        return msgs + [self.info_cmd(now)]

    def claim(self, index, now=None):
        k = self.d['kilit']
        row = next((r for r in D['birikimli'] if r[0] == index), None)
        if not k or not row or index in k['alinan'] or k['cekilis'] < row[1]:
            return [('ArmoryUnlockClaimCommand', dict(claimed=False, index=index)), self.info_cmd(now)]
        loot = fill(row[2], k['gemi'], k['top'])
        with self.p.lock:
            k['alinan'].append(index)
            self.p.dirty = True
        msgs = [('ArmoryUnlockClaimCommand', dict(claimed=True, index=index))]
        msgs += self.m.reward(loot, row[3]) if self.m else []
        self.log('   Armory birikimli ödül %d (%d çekiliş): %s x%d' % (index, row[1], loot, row[3]))
        return msgs + [self.info_cmd(now)]
