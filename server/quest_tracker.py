"""Görev koşullarının oyun olaylarıyla ilerlemesi: Season Pass, Battle Pass, etkinlik görevleri ve ana görevler için tek ölçüm noktası
(yol haritası Aşama 7, E6; ana görevler konumu ve kendine özgü türleri gorev.Gorevler.matches'te ekler).

Koşul türleri istemcinin ConditionType enum'u (derlenmiş koddan); eşleşmelerin anlamı istemcinin koşul sınıflarının ParseMatches'inden:
  1 TIMER (ms; dakika olayı 60.000)            3 ENDURANCE (haritada kalma, ms; dakika olayı)   6 KILL_NPC ([npcId]; boş liste
  istemcide çöker)                            7 DAMAGE (her hasar)                             9 TAKE_DAMAGE (alınan hasar: damage_taken)
  12 DISTANCE, 13 TRAVEL (mesafe)             20/22 AMMUNITION ([tür, derece]: 1 lazer, 2 roket, 3 mayın; 0 = hepsi)
  23 SALVAGE ([firma, gemi, uzaylı, ?, eski cevher kimliği]; yok edilen geminin kargo kutusundan cevher: loot olayı, kutu=True)
  27 KILL_NPCS ([npcId …]; listedeki uzaylıların toplamı)                     35 DIE (ölüm)  42 JUMP (portal)
  56 FINISH_QUEST ([görev]; biten görev)      29 DAMAGE_NPCS ([sayı, npcId …, 0])             30 DAMAGE_PLAYERS (bot oyuncularla)
  34 VISIT_MAP                                51 CARGO (kargo kutusu)                         52 SELL_ORE ([eski cevher kimliği])
  53 LEVEL (seviye)                           55 COLLECT_BONUS_BOX                            67 COLLECT_LOOT ([lootId …])
  66 IN_CLAN (klan olayı)                     68 FINISH_STARTER_GATE (gate olayı, tur=STARTER_GATE; Devolarium Attack kapısı)
  72 USE_ORE_UPDATE ([LASER|ROCKET|SPEED|SHIELD, CEVHER]; laboratuvarda yükseltme: ore_update olayı)
  80 FINISH_GALAXY_GATES ([sayı, ad …, harita …])   85 COLLECT_BUILT_RECIPE ([tarif]; Assembly)
  87 COMPLETED_OBJECTIVES (biten Battle Pass görevi)   89 SPEND_ITEM ([lootId])
  95 COMPLETE_SEASON_PASS_QUESTS ([2 sezonluk | 5 günlük | 6 haftalık])   96 LOGIN   100 RECHARGE_AMOUNT (tek oyunculu: Uridium Bank)
Alt koşul 77 ON_MAP: yalnız listedeki haritalarda. 97 DURING_EVENT: yalnız adı geçen etkinlik açıkken (takvimdeki etkinlik türü,
ör. NpcEvent, ya da EVENT_NAMES'teki takvim anahtarı; Season Pass'in "etkinlikte 15 Battle Pass görevi" görevleri).
Olaylar (oturum toplar): başarım olayları (kill, damage, distance, minute, gate, assembly_collect, level, ammo, spend, jump, death,
quest, clan), görev olayları (cargo, loot, sell, bonus, map, pos, ore_update) ve iç olaylar (login, recharge, sp_quest, objective). Sık gelen olayların
(hasar, mesafe, cephane) ara değeri saniyede bir gönderilir.
"""
import copy, time

import event_calendar as CAL
from quest import cap, conditions, evaluate, mod

ON_MAP = 77
DURING_EVENT = 97
EVENT_NAMES = {'HitacAssault2016': 'hitac'}       # alt koşul 97'nin adı -> takvim anahtarı (PVPSummerEvent: PvP, takvimde yok)
THROTTLE_SEC = 1.0                 # aynı koşulun ara değeri en çok saniyede bir (mesafe, cephane, hasar sık gelir; kayıt: saniyede bir)
FREQUENT = ('damage', 'damage_taken', 'damage_player', 'distance', 'ammo')
LAST_SENT = {}                    # koşul -> son gönderim
# cevher -> istemcinin eski cevher kimliği (GameDefineSystem.Init; SELL_ORE ve SALVAGE eşleşmeleri): 1 Prometium, 2 Endurium,
# 3 Terbium, 4 Xenomit, 11 Prometid, 12 Duranium, 13 Promerium, 14 Seprom, 15 Palladium, 42 Osmium
OLD_ORE = {'resource_ore_prometium': '1', 'resource_ore_endurium': '2', 'resource_ore_terbium': '3', 'resource_ore_xenomit': '4',
           'resource_ore_prometid': '11', 'resource_ore_duranium': '12', 'resource_ore_promerium': '13', 'resource_ore_seprom': '14',
           'resource_ore_palladium': '15', 'resource_ore_osmium': '42'}
ORE_LOOT = {0: 'resource_ore_prometium', 1: 'resource_ore_endurium', 2: 'resource_ore_terbium', 3: 'resource_ore_xenomit',
            4: 'resource_ore_prometid', 5: 'resource_ore_duranium', 6: 'resource_ore_promerium', 7: 'resource_ore_seprom',
            8: 'resource_ore_palladium', 28: 'resource_ore_osmium'}      # sunucunun cevher dizini (esyalar.json cevherler)
SP_CATEGORY = {3: '5', 6: '6', 9: '2'}           # QuestType -> COMPLETE_SEASON_PASS_QUESTS eşleşmesi (istemci: DAILIES, WEEKLIES, SEASON)


def ammo_kind(loot):
    """Cephane türü (istemcinin DamageType'ı): 1 lazer, 2 roket, 3 mayın, 4 ötekiler (özel cephane, CPU)."""
    if loot.startswith('ammunition_laser_'):
        return '1'
    if loot.startswith(('ammunition_rocket_', 'ammunition_rocketlauncher_')):
        return '2'
    return '3' if loot.startswith('ammunition_mine_') else '4'


def counted(m):
    """[sayı, öğe …, …] eşleşmesinden öğeler."""
    try:
        n = int(m[0]) if m else 0
    except ValueError:
        return list(m)
    return m[1:1 + n]


def measure(c, kind, kw, map_id=None):
    """Bu olay koşulu ne kadar ilerletir: sayı (eklenir), ('set', değer) ya da 0."""
    on_map = [s for s in c.get('subConditions', []) if s['type'] == ON_MAP]
    if on_map and str(kw.get('map', map_id)) not in [str(x) for x in on_map[0]['matches']]:
        return 0
    t, m = c['type'], [str(x) for x in c['matches']]
    if t == 1 and kind in ('minute', 'login'):
        return 60000 if kind == 'minute' else 1                     # giriş: "oyuna gir" görevleri (TIMER 1 ms; kayıt: girişte biter)
    if t == 3 and kind == 'minute':
        return 60000
    if t == 6 and kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC':
        return 1 if not m or str(kw.get('npc')) in m else 0
    if t == 7 and kind == 'damage':
        return int(kw.get('adet', 0))
    if t == 9 and kind == 'damage_taken':
        return int(kw.get('adet', 0))
    if t in (12, 13) and kind == 'distance':
        return int(kw.get('adet', 0))
    if t in (20, 22) and kind == 'ammo':
        return int(kw.get('adet', 0)) if not m or m[0] in ('0', ammo_kind(kw.get('loot', ''))) else 0
    if t == 23 and kind == 'loot' and kw.get('kutu'):         # [firma, gemi, uzaylı, ?, cevher]: süzgeçler kutunun kaynağını bilmez
        ore = m[4] if len(m) > 4 else '0'
        return int(kw.get('amount', 0)) if not any(x not in ('', '0') for x in m[:3]) and ore in ('', '0', OLD_ORE.get(kw.get('loot'))) else 0
    if t == 27 and kind == 'kill' and kw.get('avatar', 'NPC') == 'NPC':
        return 1 if not m or str(kw.get('npc')) in m else 0
    if t == 29 and kind == 'damage':
        ids = counted(m)
        return int(kw.get('adet', 0)) if not ids or str(kw.get('npc')) in ids else 0
    if t == 30 and kind == 'damage_player':
        return int(kw.get('adet', 0))
    if t == 34 and kind == 'map':
        return 1 if not m or str(kw.get('map')) in m else 0
    if t == 35 and kind == 'death':
        return 1
    if t == 42 and kind == 'jump':
        return 1
    if t == 51 and kind == 'cargo':
        return 1
    if t == 52 and kind == 'sell':
        return int(kw.get('amount', 0)) if not m or OLD_ORE.get(ORE_LOOT.get(kw.get('ore', -1))) in m else 0
    if t == 53 and kind == 'level':
        return ('set', int(kw.get('deger', 0)))
    if t == 55 and kind == 'bonus':
        return 1
    if t == 56 and kind == 'quest':
        return 1 if not m or str(kw.get('id')) in m else 0
    if t == 66 and kind == 'clan':
        return 1
    if t == 67 and kind == 'loot':
        return int(kw.get('amount', 0)) if not m or kw.get('loot') in m else 0
    if t == 68 and kind == 'gate':
        return 1 if kw.get('tur') == 'STARTER_GATE' else 0
    if t == 72 and kind == 'ore_update':
        return 1 if len(m) > 1 and m[0] == kw.get('tur') and kw.get('ore') == 'resource_ore_' + m[1].lower() else 0
    if t == 80 and kind == 'gate':
        names = counted(m)
        return 1 if not names or str(kw.get('tur', '')).replace('_GATE', '') in names else 0
    if t == 85 and kind == 'assembly_collect':
        return int(kw.get('adet', 1)) if not m or kw.get('tarif') in m else 0
    if t == 87 and kind == 'objective':
        return 1
    if t == 89 and kind in ('spend', 'ammo'):       # cephane harcamak ('ammo' olayı; Pass görevleri onu 'spend'e çevirir: savas_bileti.measure)
        return int(kw.get('adet', 0)) if not m or kw.get('loot') in m else 0
    if t == 95 and kind == 'sp_quest':
        return 1 if not m or str(kw.get('kategori')) == m[0] else 0
    if t == 96 and kind == 'login':
        return 1
    if t == 100 and kind == 'recharge':
        return 1
    return 0


def during_event(c, now=None):
    """Alt koşul 97 (DURING_EVENT) varsa adı geçen etkinlik şu an açık mı; yoksa True."""
    during = [s for s in c.get('subConditions', []) if s['type'] == DURING_EVENT]
    return not during or any(EVENT_NAMES.get(n) in CAL.active(now) or CAL.has_type(n, now) for n in during[0]['matches'])


def cond_update(cid, value, active, completed):
    return ('QuestConditionUpdateCommand', {'questConditionId': cid, 'state': mod(
        'QuestConditionStateModule', currentValue=value, active=active, completed=completed)})


def advance(p, root, vals, kind, kw, map_id=None, notify=True, fn=measure):
    """Bir görevin koşullarını olayla ilerletir (değerler vals'ta, kilit altında; fn: ölçüm, ana görevlerde Gorevler.matches)
    -> (mesajlar, tamamlandı mı)."""
    before = evaluate(root, vals)[0]
    changed = []
    for c in conditions(root):
        if not before[c['id']][0]:
            continue
        inc = fn(c, kind, kw, map_id)
        if not inc or not during_event(c):
            continue
        key = str(c['id'])
        with p.lock:
            old = vals.get(key, 0)
            new = cap(c, inc[1] if isinstance(inc, tuple) else old + inc)
            if new == old:
                continue
            vals[key] = new
            p.dirty = True
        changed.append(c)
    if not changed:
        return [], False
    after, done = evaluate(root, vals)
    msgs = []
    if notify:
        ids = {c['id'] for c in changed}
        now = time.time()
        for c in conditions(root):
            v = cap(c, vals.get(str(c['id']), 0))
            moved = after[c['id']] != before[c['id']]
            if c['id'] in ids and (moved or kind not in FREQUENT or now - LAST_SENT.get(c['id'], 0) >= THROTTLE_SEC):
                LAST_SENT[c['id']] = now
                msgs.append(cond_update(c['id'], v, True, False))
            if moved:
                msgs.append(cond_update(c['id'], v, *after[c['id']]))
    return msgs, done


def with_state(definition, vals, completed=False):
    """Görev tanımının kopyası, koşul durumları değerlerle (tamamlanmışsa hepsi tamam)."""
    d = copy.deepcopy(definition)
    root = d['rootCase']
    flags = evaluate(root, vals)[0]
    for c in conditions(root):
        active, comp = flags[c['id']]
        v = cap(c, vals.get(str(c['id']), 0))
        if completed:
            active, comp, v = False, True, c['targetValue']
        c['state'].update(currentValue=v, active=active, completed=comp)
    return d
