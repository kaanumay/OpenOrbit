"""Harita etkinlikleri (yol haritası Aşama 7; veri data/events.json "harita", uzaylılar npc.json etk_* <- tools/event_aliens.py).

Takvimde etkin bir etkinliğin harita bölümü bu haritanın sınıfını (X-2 … X-8, 4-4 …) kapsıyorsa:
  - etkinlik uzaylıları haritaya eklenir ('uzaylilar': tür ve adet; "{x}" harita sınıfının sürümü: etk_curcubitor_x5); ölünce yeniden
    doğarlar, etkinlik bitince doğmazlar
  - çağırma kotası ('kota'): bu kadar etkinlik uzaylısı ölünce patronlar ('patron': türler, adet, süre; 'sirayla': türler sırayla)
    doğar; süresinde öldürülmezse kaçarlar (istemcinin metni: msg_curcubitor_ran_away / npc_event_boss_ran_away)
  - gösterge ('bilgi'): NpcEventInfoCommand / AgatusEventInfoCommand {textKey (istemcinin metinleri: curcubitor, agatusbreach,
    npc_valentine, npc_chaos-protegit), npcID, bossInfo {bossCount, leftToKill}, timeInfo {timeToNextSpawn, timeToEndSpawn sn}}
  - düşmeler ('dusme': tür -> {lootId: [en az, en çok]}, harita sürümü etk_x_x5 varsa o, yoksa taban tür; etkinlik parası kaynak
    deposuna, ganimet günlüğünde) ve Curcubitor'un
    "Trick or Treat"i: ölünce ya Trick ('hile': olasılık; toplanamayan Curcubitor mayını, kurulunca yakındaysan canın %20'si) ya da
    Treat (kutu_dusme'deki sandık), ikisi birden değil. 2026-10-18'e dek ikisi bağımsızdı: mayın sandığın altında kalıyor, sandığı
    toplarken patlıyordu (kullanıcı bildirimi)
  - kargo kutusu olmayan uzaylılar ('kargo_yok': temel türler; Curcubitor ve Boss Curcubitor yalnız sandıklarını düşürür) -> no_cargo
  - kargo kutusunun görünümü ('kargo_tur': istemcinin kutu türü, içerik aynı; Thanksgiving'de TURKEY_CARGO) -> cargo_kind
  - çağıranlar ('cagir' ya da patronun 'cagir'ı): canlıyken aralıkla yanına uzaylı çağırır (Agatus -> Spinel, Ice Meteoroid -> Icy)
  - av kutuları ('kutular': istemcinin kutu türü, adet, içerik, yeniden doğma) ve uzaylının düşürdüğü kutular ('kutu_dusme': tür ->
    {kutu türü, olasılık, içerik}; etkinlik türleri ve haritanın sıradan uzaylıları, ör. Empyrian'da Luminium); anahtarsız, P.E.T. de
    toplar; içerik açılınca: 'kesin' satırların hepsi, 'icerik'ten 'biri' ağırlıkla bir ödül ya da 'hepsi' her biri kendi olasılığıyla
    ([lootId, adet ya da [en az, en çok], olasılık %]); NPC türünün kendi 'kutu'su da (etkinlik kapıları)
  - gezgin uzaylı (etkinliğin 'gezgin'i, tek ya da liste: Hitac 2.5 ve E8'den Hitac 2.0): rotadaki haritalarda sırayla sure_sn
    kalır, oyuncu o haritadaysa belirir, süresi dolunca sonraki haritaya geçer; öldürülünce bekleme_sn sonra rotanın başından
    (oturum boyunca)
  - grup ('grup': {turler [[tür, adet]], aralik_sn}): haritanın rastgele bir yerinde bir arada doğan grup; bir sonraki grup ancak
    hepsi yok edilince ve aralik_sn dolunca (Space Cup'ın 4-4'teki 11 Gezgin Futbol Korsanı, resmî Türk forumu 127757)
  - ölünce doğanlar ('olunce_dogur': tür -> [{tur, adet (ya da [en az, en çok]), olasilik}]): etkinlik sürerken o tür ölünce yanında
    doğarlar ve öldüreni hedeflerler (Hatching Out'un yumurtasından 2-5 I-Gygerthrall, Epidemi'de Plagued Kristallin'den Plagued
    Gygerthrall); kutu_dusme'nin 'adet'i: bir ölümde düşen kutu sayısı (Demaner Freighter: 10 Özel Demaner Kutusu); çağıranın
    'omur_sn'si: çağrılan bu kadar saniye sonra kaybolur (I-Hitac'ın 30 sn'de bir bıraktığı yumurta 90 sn)
"""
import math, random, time

import map_links as H
import event_calendar as CAL
import settings as SET
from legacy_protocol import legacy
from galaxy_gates import screen

TRICK_MINE = 'curcubitor_mayini'        # istemcinin curcubitorMine modeli (esyalar.json mayinlar)
TRICK_DELAY = 1.4                         # resmî sunucu kaydı 2026-10-27: mayın ölümden 1,4 sn sonra çıkar
BOSS_TEXT = {'curcubitor': ('curcubitor_boss_spawn', 'msg_curcubitor_ran_away'), 'agatusbreach': ('agatusbreach_boss_spawn', None),
             'npc_valentine': ('npc_valentine_boss_spawn', None), 'npc_hitacAssault': ('npc_hitacAssault_boss_spawn', None)}


def mod(name, **f):
    f['_'] = name
    return f


def specs(now=None):
    """Etkin etkinliklerin şu an açık harita bölümleri: [(etkinlik, bölüm)] (bölümün dönemleri ve doğuş saatleri: takvim.window;
    zorla açılan etkinlikte hepsi)."""
    out = []
    for k in sorted(CAL.active(now)):
        e = CAL.EVENTS[k]
        for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', []):
            if CAL.forced(k) or CAL.window(s, now):
                out.append((k, s))
    return out


PROXIUM = 'resource_collectable_proxium'


def roll(spec, mods=None):
    """Kutu içeriği -> [(lootId, adet)]: 'kesin' satırların hepsi, 'icerik'ten 'mod'a göre. mods: oyuncunun bonusları (profil.mods());
    kutu 'proxium' ise (Permafrost Fissure'ın UFO ve Ufonit kutuları) Proxium satırının olasılığı Proxium Drop Booster'ın puanı kadar
    (proxium_sans: %10 -> %35), adedi Proxium Doubler'ın oranı kadar (proxium: x2) artar."""
    rows = spec.get('contents', [])
    bonus = mods if spec.get('proxium') and mods else {}
    amount = lambda a, l=None: int((random.randint(*a) if isinstance(a, list) else a) * (1 + bonus.get('proxium', 0) if l == PROXIUM else 1))
    pct = lambda l, c: c + bonus.get('proxium_chance', 0) * 100 if l == PROXIUM else c
    out = [(l, amount(a, l)) for l, a, *c in spec.get('guaranteed', [])]
    out += [(l, amount(a, l)) for l, a, c in spec.get('additional', []) if random.random() * 100 < pct(l, c)]   # ayrı olasılıklı (Permafrost Proxium)
    if spec.get('mod', 'one_of') == 'hepsi':
        return out + [(l, amount(a, l)) for l, a, *c in rows if random.random() * 100 < pct(l, c[0] if c and c[0] is not None else 100)]
    weights = [pct(l, c[0] if c and c[0] is not None else 1) for l, a, *c in rows]
    if not rows or sum(weights) <= 0:
        return out
    l, a, *c = random.choices(rows, weights)[0]
    return out + [(l, amount(a, l))]


ROVER = {}                         # gezgin (rovers) -> rotasının başlangıcı (öldürülünce bekleme sonrası)
NO_CARGO = {b for e in CAL.EVENTS.values() for s in ([e['map']] if 'map' in e else []) + e.get('map_extra', [])
            for b in s.get('no_cargo', [])}          # etkinlik bitse de: o türün uzaylısı hiç kargo kutusu düşürmez


def no_cargo(n):
    """Bu uzaylı kargo kutusu düşürmez mi (etkinlik verisinin 'kargo_yok'u; Curcubitor yalnız sandığını düşürür)."""
    return base(n.tip) in NO_CARGO


def rovers(k):
    """Etkinliğin gezginleri [(ROVER anahtarı, gezgin)]: ilki etkinliğin adıyla, ötekiler 'ad#sıra'."""
    g = CAL.EVENTS[k].get('rover') or []
    return [(k if i == 0 else '%s#%d' % (k, i), x) for i, x in enumerate(g if isinstance(g, list) else [g])]


def route_at(k, g, now):
    """Gezginin şu an bulunduğu harita (bekleme sürerken None)."""
    start = ROVER.setdefault(k, now)
    if now < start:
        return None
    return g['route'][int((now - start) // g['sure_sn']) % len(g['route'])]


def route_leg(k, g, now):
    """Gezginin bu haritadaki ayağı: (önceki harita, sonraki harita, bu haritadan ayrılış anı)."""
    start = ROVER.setdefault(k, now)
    i = int((now - start) // g['sure_sn'])
    r = g['route']
    return r[(i - 1) % len(r)], r[(i + 1) % len(r)], start + (i + 1) * g['sure_sn']


def gate_to(w, name):
    """Bu haritada adı verilen haritaya giden portalın yeri ya da None."""
    g = next((g for g in w.gates if g.get('target') is not None and H.name(g['target']) == name), None)
    return (g['x'], g['y']) if g else None


def fmt(t, mc):
    return t.replace('{x}', mc.lower().replace('-', ''))


def base(tip):
    """etk_curcubitor_x5 -> etk_curcubitor."""
    head, _, tail = tip.rpartition('_')
    return head if tail[:1] == 'x' and tail[1:].isdigit() else tip


class MapEvents:
    def __init__(self, w):
        self.w = w
        self.mc = H.map_class(w.map_id)
        self.st = {}                   # etkinlik -> {sayac, patron [kimlik], bitis, sira}
        self.calls = {}                # çağıran uzaylı kimliği -> sonraki çağırma
        self.next_tick = 0.0

    def here(self, now=None):
        return [(k, s) for k, s in specs(now) if self.mc in s['maps']]

    def state(self, k):
        return self.st.setdefault(k, dict(counter=0, boss=[], end_time=None, order=0))

    def minion_types(self, s):
        return [fmt(u['type'], self.mc) for u in s.get('alien_spawns', [])]

    def cargo_kind(self, now=None):
        """Uzaylının kargo kutusunun etkinlik görünümü (bölümün 'kargo_tur'u: Thanksgiving'de TURKEY_CARGO; içerik aynı) ya da None."""
        return next((s['cargo_kind'] for k, s in self.here(now) if s.get('cargo_kind')), None)

    def active_type(self, tip, now=None):
        """Bu etkinlik türü şu an doğabilir mi (etkinlik sürüyor ve bu haritada)."""
        return any(tip in self.minion_types(s) for k, s in self.here(now))

    # ------------------------------------------------------------ kurulum ve gösterge
    def box_spec(self, tip, now=None):
        return next((b for k, s in self.here(now) for b in s.get('boxes', []) if b['type'] == tip), None)

    def spawn_box(self, tip):
        """Av kutusu: rastgele yerde, süresiz; toplanınca yeniden_sn sonra yenisi (etkinlik sürüyorsa)."""
        spec = self.box_spec(tip)
        if not spec:
            return None
        x, y = self.w.random_spot()
        h = self.w.drop_box(tip, x, y, None, None)
        self.w.boxes[h]['event'] = spec
        return h

    def setup(self):
        """Harita açılınca (ya da etkinlik başlayınca): eksik etkinlik uzaylıları ve av kutuları."""
        w = self.w
        for k, s in self.here():
            for b in s.get('boxes', []):
                have = sum(1 for x in w.boxes.values() if x['tip'] == b['type'] and x.get('event'))
                for _ in range(max(0, SET.count('box_abundance', b.get('count', 1), 'event') - have)):
                    self.spawn_box(b['type'])
            for u in s.get('alien_spawns', []):
                tip = fmt(u['type'], self.mc)
                if tip not in w.CFG_TYPES:
                    continue
                have = sum(1 for n in w.npcs.values() if n.alive and n.tip == tip)
                for _ in range(max(0, SET.count('npc_count', u['count'], 'event') - have)):
                    w.spawn_npc(tip, announce=True)

    def info_msgs(self, now=None):
        now = time.time() if now is None else now
        msgs = []
        for k, s in self.here(now):
            b = s.get('info')
            if not b:
                continue
            st = self.state(k)
            quota = s.get('quota', {}).get(self.mc, 0)
            alive = [i for i in st['boss'] if i in self.w.npcs and self.w.npcs[i].alive]
            agatus = b['command'] == 'AgatusEventInfoCommand'
            pre = 'AgatusEvent' if agatus else 'NpcEvent'
            msgs.append((b['command'], dict(
                textKey=b['text'], type=0, npcID=b['npc'],
                bossInfoCommand=mod(pre + 'BossInfoCommand', bossCount=len(alive), leftToKill=max(0, quota - st['counter']) if quota else 0),
                timeInfoCommand=mod(pre + 'TimeInfoCommand', timeToNextSpawn=0, timeToEndSpawn=CAL.time_left(k, now)))))
        # etkinliğin olmadığı haritada da gösterge (Ö1, canlı test): patron ve kalan öldürme 0 -> istemci "There are no %NPC% on this
        # map" yazar (NpcEventUIData.UpdateDescriptions); göndermeyince pencere boş açılıyordu
        sent = {(c, f['textKey']) for c, f in msgs}
        for k, s in specs(now):
            b = s.get('info')
            if not b or (b['command'], b['text']) in sent:
                continue
            sent.add((b['command'], b['text']))
            pre = 'AgatusEvent' if b['command'] == 'AgatusEventInfoCommand' else 'NpcEvent'
            msgs.append((b['command'], dict(textKey=b['text'], type=0, npcID=b['npc'],
                                          bossInfoCommand=mod(pre + 'BossInfoCommand', bossCount=0, leftToKill=0),
                                          timeInfoCommand=mod(pre + 'TimeInfoCommand', timeToNextSpawn=0,
                                                              timeToEndSpawn=CAL.time_left(k, now)))))
        return msgs

    # ------------------------------------------------------------ olaylar
    def on_kill(self, n, x, y, now=None, w=None, pay=None):
        """w: öldüren dünya (ortak haritada self.w lider; düşmeler ve ek ödüller öldürenin). pay: ödülü paylaşanların dünyaları
        (öldüren dahil; grup: dunya.paydaslar): düşen kutular ve ek ödüller her birine kendi şansıyla, grupta kutu sahibinin."""
        w = w or self.w
        pay = pay or [w]
        owner = lambda v: v.hid if len(pay) > 1 else None
        box = n.d.get('box')                   # türün kutusu (etkinlik kapıları: dalga kutusu, Plutus'un paketi, Synk'in kutusu)
        for v in pay:
            if box and random.random() < SET.chance('drop', box.get('probability', 1.0), 'event'):
                h = v.drop_box(box['type'], x, y, None, box.get('lifetime_sec', 300), owner(v))
                v.boxes[h]['event'] = box
        now = time.time() if now is None else now
        b, msgs = base(n.tip), []
        by_tip = lambda tab: tab.get(n.tip, tab.get(b))       # haritaya özgü sürüm (etk_chaos_protegit_x5) önce, yoksa taban tür
        trick = (n.tip.startswith('event_') and w.items is not None
                 and random.random() < max([s.get('trick', {}).get(b, 0) for k, s in self.here(now)] or [0]))
        if trick:                                                       # Trick: sandık yerine toplanamayan mayın
            w.later(TRICK_DELAY, lambda: w.items.alien_mine(TRICK_MINE, x, y, n.id, time.time()))
        for k, s in self.here(now):
            roster_row = by_tip(s.get('box_drop', {}))
            for v in pay if roster_row and not trick else ():
                if random.random() < SET.chance('drop', roster_row.get('probability', 1.0), 'event'):    # uzaylının kutusu (Treat …)
                    for j in range(roster_row.get('count', 1)):                   # Demaner Freighter: 10 kutu, yan yana
                        h = v.drop_box(roster_row['type'], x + 60 * (j % 5), y + 60 * (j // 5), None, roster_row.get('lifetime_sec', 300), owner(v))
                        v.boxes[h]['event'] = roster_row
            for sp in by_tip(s.get('spawn_on_death', {})) or []:            # etkinlikte ölünce doğanlar: öldüreni hedeflerler
                if random.random() >= sp.get('probability', 1.0) or sp['type'] not in w.CFG_TYPES:
                    continue
                cnt = random.randint(*sp['count']) if isinstance(sp.get('count'), list) else sp.get('count', 1)
                for j in range(cnt):
                    a = 2 * math.pi * j / max(1, cnt)
                    c = w.spawn_npc_at(sp['type'], x + math.cos(a) * 150, y + math.sin(a) * 150)
                    c.summoned = True
                    c.engaged = True
                    c.next_think = now
                w.log('   %s öldü: %d x %s doğdu (%s)' % (n.d['name'], cnt, sp['type'], k))
        for rocket, g in [r for k in sorted(CAL.active(now)) for r in rovers(k)]:
            if n.tip == g['type']:
                ROVER[rocket] = now + g.get('cooldown_sec', 1800)
                msgs.append(screen('key:msg_summoning_boss_killed', big=True, NPC_NAME=n.d['name']))      # "… Another will arrive soon!"
                w.log('   gezgin %s yok edildi (%s)' % (n.d['name'], rocket))
        if not n.tip.startswith('event_'):
            return msgs
        for k, s in self.here(now):
            st = self.state(k)
            drops = by_tip(s.get('drop', {}))
            if drops:
                msgs += w.extra_loot(n, drops)
                for v in pay:
                    if v is not w:
                        v.send(v.extra_loot(n, drops))
            if n.id in st['boss']:
                st['boss'].remove(n.id)
                if not st['boss']:
                    st['end_time'] = None
                    w.log('   etkinlik patronları yok edildi (%s)' % k)
                msgs += self.info_msgs(now)
            elif n.tip in self.minion_types(s) and s.get('quota', {}).get(self.mc) and not st['boss']:
                st['counter'] += 1
                if st['counter'] >= s['quota'][self.mc]:
                    msgs += self.summon(k, s, now)
                msgs += self.info_msgs(now)
        self.calls.pop(n.id, None)
        return msgs

    def rover(self, now):
        """Gezgin uzaylı bu haritada mı: gelince doğar, rotada ilerleyince ayrılır."""
        w, out = self.w, []
        name = H.name(w.map_id)
        for k, rocket, g in [(k, rocket, g) for k in sorted(CAL.EVENTS) for rocket, g in rovers(k)]:
            st = self.state(k).setdefault('rover', {})
            # haritaya yeniden girince harita durumundan gelen gezgin de sayılır (yoksa ikincisi doğuyordu: canlı deneme 2026-10-30)
            alive = [i for i, n in w.npcs.items() if n.alive and (i in st.get(rocket, []) or n.tip == g['type'])]
            at = route_at(rocket, g, now) if CAL.is_active(k, now) else None
            if at == name and not alive and g['type'] in w.CFG_TYPES:
                # darkorbitwiki (Hitac Mothership): "flies in a straight line between the ports and jumps to another map": önceki
                # haritanın portalından girer, sonrakinin portalına düz uçar (oyuncu bildirimi 2026-10-30: rastgele yerde doğup
                # süresi dolunca yok oluyordu). Varış: bu haritadaki süresinin sonu (sure_sn, uyarlama)
                prev, nxt, until = route_leg(rocket, g, now)
                x, y = gate_to(w, prev) or w.random_spot()
                n = w.spawn_npc_at(g['type'], x, y)
                n.summoned = True                        # dünya yeniden doğurmaz, etkinlik bitince kalkmaz (rota yönetir)
                tx, ty = gate_to(w, nxt) or w.random_spot()
                n.route = (tx, ty, until)
                w.npc_summon(n, now, hit=False)          # fandom (Hitac-Mothership): altı yardımcısıyla gelir
                for c in n.children:
                    w.npcs[c].engaged = False            # oyuncu yaklaşınca ya da vurunca saldırırlar (uzaktakini kovalamasınlar)
                alive = [n.id]
                out.append(screen('key:msg_npc_spawned_map', big=True, NPC_NAME=n.d['name'], MAP=name))
                w.log('   gezgin %s geldi (%s)' % (n.d['name'], name))
            elif alive and at != name:
                for i in alive:
                    n = w.npcs[i]
                    for c in [c for c in n.children if c in w.npcs]:
                        w.alien.expire(w.npcs[c])
                    w.alien.expire(n)
                    out.append(screen('%s jumped to %s.' % (n.d['name'], at or '?')))
                    w.log('   gezgin %s ayrıldı -> %s' % (n.d['name'], at))
                alive = []
            st[rocket] = alive
        return out

    def summon(self, k, s, now):
        w, st, p = self.w, self.state(k), s['boss']
        st['counter'] = 0
        kinds = [fmt(t, self.mc) for t in p['kinds']]
        if p.get('in_order'):
            kinds = [kinds[st['order'] % len(kinds)]]
            st['order'] += 1
        hx, hy = w.hero_pos(now)
        for i in range(p.get('count', 1)):
            tip = kinds[i % len(kinds)]
            if tip not in w.CFG_TYPES:
                continue
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(900, 1400)
            x = min(max(600, hx + math.cos(a) * r), w.map_w - 600)
            y = min(max(600, hy + math.sin(a) * r), w.map_h - 600)
            c = w.spawn_npc_at(tip, x, y)
            c.summoned = True
            st['boss'].append(c.id)
        st['end_time'] = now + p.get('sure_sn', 1800)
        w.log('   etkinlik patronu çağrıldı (%s): %s x%d' % (k, ', '.join(kinds), len(st['boss'])))
        first = w.npcs.get(st['boss'][0]) if st['boss'] else None
        if first:
            w.cinematic(*first.mover.pos(now))                       # sinematik giriş (Ö2; panelden kapatılabilir)
        text = BOSS_TEXT.get((s.get('info') or {}).get('text'), (None, None))[0]
        return [legacy('0|A|STM|%s' % text)] if text else []

    def group(self, k, g, now):
        """Grubu haritanın rastgele bir yerinde doğurur; sonraki grup ancak bu grup yok edilince ve aralik_sn dolunca."""
        w, st = self.w, self.state(k).setdefault('group', {'members': [], 'next': 0})
        st['members'] = [i for i in st['members'] if i in w.npcs and w.npcs[i].alive]
        if st['members'] or now < st['next']:
            return []
        x, y = w.random_spot()
        kinds = [fmt(t, self.mc) for t, c in g['kinds'] for _ in range(c)]
        for i, tip in enumerate(kinds):
            if tip not in w.CFG_TYPES:
                continue
            a = 2 * math.pi * i / len(kinds)
            c = w.spawn_npc_at(tip, x + math.cos(a) * 250, y + math.sin(a) * 250)
            c.summoned = True                            # dünya yeniden doğurmaz; grup yok edilince yenisi
            st['members'].append(c.id)
        st['next'] = now + g.get('interval_sec', 600)
        w.log('   etkinlik grubu doğdu (%s): %d uzaylı (%d,%d)' % (k, len(st['members']), x, y))
        return []

    def tick(self, now):
        if now < self.next_tick:
            return
        self.next_tick = now + 1.0
        w, msgs = self.w, []
        here = self.here(now)
        for k, s in here:
            st = self.state(k)
            if s.get('group'):
                msgs += self.group(k, s['group'], now)
            if st['boss'] and st['end_time'] and now >= st['end_time']:          # süre doldu: patronlar kaçar
                for i in st['boss']:
                    n = w.npcs.get(i)
                    if n and n.alive:
                        w.alien.expire(n)
                st['boss'], st['end_time'] = [], None
                ran = BOSS_TEXT.get((s.get('info') or {}).get('text'), (None, None))[1] or 'npc_event_boss_ran_away'
                msgs += [legacy('0|A|STM|%s' % ran)] + self.info_msgs(now)
                w.log('   etkinlik patronları kaçtı (%s)' % k)
            callers = {b: (c, False) for b, c in s.get('call', {}).items()}           # her zaman (Ice Meteoroid)
            if s.get('boss', {}).get('call'):
                for t in s['boss']['kinds']:                                       # patron: saldırı altındayken (Agatus)
                    callers[base(fmt(t, self.mc))] = (s['boss']['call'], True)
            for n in list(w.npcs.values()):
                c, need_fight = callers.get(base(n.tip), (None, False)) if n.alive and n.tip.startswith('event_') else (None, False)
                if not c or (need_fight and not n.engaged):
                    continue
                if now < self.calls.setdefault(n.id, now + c['interval_sec']):
                    continue
                self.calls[n.id] = now + c['interval_sec']
                kids = [i for i in n.children if i in w.npcs and w.npcs[i].alive]
                tip = fmt(c['type'], self.mc)
                if tip not in w.CFG_TYPES:
                    continue
                nx, ny = n.mover.pos(now)
                for j in range(min(c['count'], c['max_count'] - len(kids))):
                    a = random.uniform(0, 2 * math.pi)
                    ch = w.spawn_npc_at(tip, nx + math.cos(a) * 150, ny + math.sin(a) * 150)
                    ch.summoned = True
                    ch.engaged = n.engaged
                    if c.get('lifetime_sec'):                     # I-Hitac'ın yumurtası 90 sn sonra kaybolur (uzayli.tick 'omur')
                        ch.ab['lifetime'] = now + c['lifetime_sec']
                    n.children.add(ch.id)
        msgs += self.rover(now)
        if here != getattr(self, 'last_here', None):        # etkinlik başladı/bitti: uzaylılar ve gösterge
            self.last_here = here
            keep = {fmt(u['type'], self.mc) for k, s in here for u in s.get('alien_spawns', [])}
            for n in list(w.npcs.values()):                  # biten etkinliğin uzaylıları (saklanan harita durumundan) kalkar
                if n.alive and n.tip.startswith('event_') and not n.summoned and n.tip not in keep and not n.engaged:
                    w.alien.expire(n)
            boxes = {b['type'] for k, s in here for b in s.get('boxes', [])}
            for h, b in list(w.boxes.items()):                 # biten etkinliğin av kutuları
                if b.get('event') and b['event'].get('renew_sec') and b['tip'] not in boxes:
                    del w.boxes[h]
                    msgs.append(('RemoveCollectableCommand', {'collected': False, 'hash': h}))
            self.setup()
            msgs += self.info_msgs(now)
        if msgs:
            w.send(msgs)
