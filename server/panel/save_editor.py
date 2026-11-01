"""Kayıt editörü (karakter editörü; panel ayrı süreçte çalıştırır, sunucu modüllerini panelin sürecine yüklememek için).

Editör kaydın taslağında çalışır (saves.py: <yuva>/duzenleme.json); takma, çıkarma, gemi etkinleştirme, tasarım, config temizleme
ve aktarma oyunun kendi hangar kodundan geçer (magaza.Magaza.handle: istemcinin istekleriyle aynı kurallar), eşya ve gemi vermek
oyunun ödül yolundan (magaza.reward). Adetler (cephane, cevher, kaynak, booster), seviyeler (pilot, dron, P.E.T., eşya yükseltmesi)
doğrudan profilde değişir.

  python -I save_editor.py oku <profil.json> [<asıl profil.json>]
      editörün görünümü; asıl profil verilirse ondan farkların özeti
  python -I save_editor.py uygula <profil.json> <işlemler JSON> [<asıl profil.json>]
      işlemleri sırayla uygula, kaydet -> görünüm (işlemler: ISLEMLER)
  python -I save_editor.py bilgi
      her eşyanın ipucu satırları (değerler, bonuslar, gemiler, yükseltme, satış; bilgi())
  python -I save_editor.py katalog
      eklenebilecek eşyalar: [lootId, kategori, gemi yuvası, P.E.T. yuvası, drona takılır mı]
Çıktı: son satırda JSON {'ok': true, ...} ya da {'ok': false, 'hata': '...', 'kalip': ..., 'arg': [...]} (profile_tool.py gibi).
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.dirname(HERE)
sys.path.insert(0, SERVER)
sys.path.insert(0, HERE)
import profile_tool as PA        # noqa: E402


def _(s):
    """Çevrilecek metin işareti: panel iletiyi kendi dilinde kurar (kayitlar.run_tool, lang.py; test_panel_lang.py toplar)."""
    return s


COMPANIES = (1, 2, 3)
# oyunun ret nedenleri (BaseKey adı ya da magaza.NEDENLER anahtarı) -> panelin iletisi
REJECTS = {
    'error_can_not_equip_to_slot': _('Bu eşya bu yuvaya takılamaz: oyunun kuralları izin vermiyor (gemiye uygunluk, yuva türü ya da config sınırı).'),
    'special_generic_hint': _("Bu ekstradan bu config'te zaten var."),
    'drone_slotCPUinUse': _("Yuva CPU'su kullanımda: önce ekstra yuvalarını boşalt."),
    'pet_gear_requirement': _("P.E.T.'in seviyesi bu eşya için yetmiyor."),
    'dse_ship_not_exist': _('Gemi bulunamadı.'),
    'pet_already': _("Bu eşya P.E.T.'te zaten takılı."),
    'pet_full': _("P.E.T.'te bu eşya için boş yuva yok."),
    'other_ship': _('Bu eşya başka bir gemide takılı: önce oradan çıkar.'),
    'same_cannon': _('Gemide bu türden bir top zaten takılı.'),
    'qfc_ship': _('Bu Quantum Fluid Core başka bir gemiye bağlı.'),
    'same_qfc': _('Gemide bu türden bir Quantum Fluid Core zaten takılı.'),
    'single_slot_cpu': _("Bir config'e yalnız bir Slot CPU takılabilir."),
    'same_module': _('Bir gemiye her türden (hasar, can, kalkan, özel) yalnız bir modül takılabilir.'),
}
HOME_MAP = PA.HOME_MAP
AMMO = (('ammunition_laser_', 'lazer'), ('ammunition_rocketlauncher_', 'rocket_launcher'), ('ammunition_rocket_', 'roket'),
           ('ammunition_mine_', 'mayin'), ('ammunition_specialammo_', 'ozel'), ('ammunition_', 'other'))
# katalog kategorileri: (kimlik, istemcinin eşya sınıfları, lootId önekleri); sıra seçim penceresindeki sıra
CATEGORIES = (
    ('gemi', ('ShipType',), ()), ('tasarim', ('ShipDesignType',), ()), ('lazer', ('LaserType',), ('equipment_weapon_laser_',)),
    ('rocket_launcher', ('HellstormLauncherType',), ('equipment_weapon_rocketlauncher_',)),
    ('generator', ('ShieldType', 'EngineType'), ('equipment_generator_',)),
    ('ekstra', ('CPUType', 'ExtraType', 'HardwareType', 'RobotType', 'TechType'), ('equipment_extra_',)),
    ('modul', ('ShipUpgradeType', 'QuantumFluidCoreType'), ('equipment_shipupgrade_', 'equipment_core_')),
    ('heavy', ('CannonType', 'CannonShieldType', 'DriveType', 'LensType'), ('equipment_cannon', 'equipment_lens_', 'equipment_drive')),
    ('drone', ('DroneType', 'DroneFormationType', 'DroneDesignType', 'DroneCustomizationType'), ('drone_',)),
    ('pet', ('PetGearType', 'AIProtocolType', 'PetCustomizationType', 'PetType'), ('equipment_petgear_', 'equipment_aiprotocol_', 'pet_')),
    ('ammunition', ('AmmunitionType',), ('ammunition_',)), ('booster', (), ('booster_',)),
    ('kaynak', ('OreType', 'ItemType', 'SynthesisResourceType'), ('resource_',)), ('paket', (), ('package_', 'deal_')),
)


def _ist():
    return PA._load('client_items.json').get('esyalar') or {}


def category(loot, ist=None):
    ist = _ist() if ist is None else ist
    klass = (ist.get(loot) or {}).get('class_name')
    if loot.startswith('booster_'):                    # istemcide ExtraType
        return 'booster'
    for k, classes, prefixes in CATEGORIES:
        if klass in classes or loot.startswith(prefixes):
            return k
    return 'other'


def catalog():
    import shop as SHP
    import pet as PETM
    ist = _ist()
    return {'esyalar': sorted([l, category(l, ist), SHP.slot_of(l), PETM.slot_for(l), bool(SHP.drone_ok(l) or l in SHP.DESIGNS)]
                              for l in PA.known_loots()),
            'categories': [k for k, _s, _o in CATEGORIES] + ['other']}


# ------------------------------------------------------------------ eşya bilgisi (panelin ipucu)
# sunucunun bonus anahtarı -> istemcinin nitelik adı (metinler_<dil>.json "n": panel o dilde yazar)
ATTRIBUTE_NAME = {'lazer': 'dmg_laser', 'roket': 'dmg_rockets', 'can': 'hitpoints', 'kalkan': 'shield', 'hiz': 'speed', 'ep': 'experience',
               'onur': 'honour', 'evasion': 'evasion', 'npc': 'dmg_npc', 'pvp': 'dmg_pvp', 'laser_hit_chance': 'hitchance_laser',
               'rocket_hit_chance': 'hitchance_rocket', 'shield_penetration': 'shield_penetration'}
BOOSTER_NAME = {'DAMAGE': 'damage', 'HITPOINTS': 'hitpoints', 'SHIELD': 'shield', 'EXPERIENCE_POINTS': 'experience', 'HONOUR_POINTS': 'honour'}


def info():
    """Her eşyanın ipucu satırları (istemcinin ve sunucunun eşya verisinden). lootId -> {
      dg: [[etiket, değer, biçim]]   biçim: n sayı, p yüzde (kesir), x kat, sn saniye, dk dakika, sa saat; etiket panelin metni
      m: [[nitelik, kesir]]          istemcinin nitelik adıyla bonus (modül, tasarım, gemi, formasyon, booster)
      gm: [gemi lootId]              modülün geçtiği gemiler (kararsızda öncelikli gemiler)
      up: [yüzde, azami, tür]        yükseltme (Assembly): seviye başına bonus
      sat: kredi                     satış değeri
      yv: {yuva: sayı}               geminin ve dronun yuvaları
      ph: {yer tutucu: değer}        açıklamadaki %HOURS%, %BOOSTERVALUE% …
      tk: [SHIP, PET, DRONE]         takılabildiği yerler}"""
    import shop as SHP
    import ship_module as GM
    import particle as PC
    import qfc as QF
    import pet as PETM
    import upgrades as UPG
    import booster as BOOSTER
    E, ist, out = SHP.ITEMS, _ist(), {}

    def row(l):
        return out.setdefault(l, {})

    def stats(l, tag, v, style='n'):
        if v is not None:
            row(l).setdefault('stats', []).append([tag, v, style])

    def bonus(l, b):
        for k, v in (b or {}).items():
            if k in ATTRIBUTE_NAME and v:
                row(l).setdefault('m', []).append([ATTRIBUTE_NAME[k], v])
    for l, v in ist.items():
        if l.startswith(('shipId_', 'paymentItem_')):
            continue
        if v.get('selling'):
            row(l)['sell'] = int(v['selling'])
        if v.get('equippable'):
            row(l)['tk'] = v['equippable']
        up = [u for u in v.get('upgrade', []) if u.get('yuzde')]
        if up and UPG.max_level(l):
            row(l)['up'] = [[u['yuzde'] / 100.0, UPG.max_level(l), u['tur']] for u in up]
        if v.get('class_name') in ('ShipType', 'ShipDesignType'):
            gr = E['ships'].get(l) or E['ships'].get(l.split('_design_')[0]) or {}
            stats(l, 'can', v.get('can') or gr.get('hp'))
            stats(l, 'hiz', v.get('hiz') or gr.get('base_speed'))
            stats(l, 'kargo', v.get('kargo') or gr.get('kargo'))
            row(l)['slot_info'] = {k: n for k, n in (v.get('slots') or {}).items() if n}
            bonus(l, gr.get('bonus'))
            bonus(l, (E.get('designs', {}).get(l) or {}).get('bonus'))
        if l in E['drones']:
            row(l)['slot_info'] = {'default': E['drones'][l]['yuva']}
    for l, v in E['lasers'].items():
        stats(l, 'hasar', v.get('hasar'))
        stats(l, 'pvp_damage', v.get('pvp_damage'))
    for l, v in E['shield_generators'].items():
        stats(l, 'kalkan', v.get('kalkan'))
        stats(l, 'absorb', v.get('absorb'), 'p')
    for l, v in E['speed_generators'].items():
        stats(l, 'hiz', v.get('hiz'))
    for l, v in E['laser_ammo'].items():
        stats(l, 'laser_multiplier', v.get('carpan'), 'x')
    for l, v in E['rockets'].items():
        if isinstance(v, dict):
            stats(l, 'hasar', v.get('hasar'))
            stats(l, 'hit', v.get('hit'), 'p')
    for l, v in E['repair_robots'].items():
        stats(l, 'full_repair', v.get('full_repair_sec'), 'sn')
        stats(l, 'hp_per_minute', v.get('hp_per_minute'))
    for l, v in E['extras'].items():
        if not isinstance(v, dict):
            continue
        stats(l, 'right', v.get('right'))
        stats(l, 'extra_slot', v.get('extra_slot'))
        stats(l, 'cooldown', v.get('bekleme_sn'), 'sn')
        stats(l, 'cargo_multiplier', v.get('cargo_multiplier'), 'x')
    for l, v in E['formations'].items():
        bonus(l, {k: x for k, x in v.items() if k != 'id'})
    for l, v in E['drone_designs'].items():
        if isinstance(v, dict):
            bonus(l, v.get('set_bonus'))
            stats(l, 'drone_shield', v.get('drone_shield'), 'p')
            stats(l, 'drone_laser', (v.get('set_bonus') or {}).get('drone_laser'), 'p')
    hour = E['boosters'].get('saat', {})
    for l in list(E['boosters']['kinds']) + list(BOOSTER.ALIAS):
        effect = BOOSTER.B['kinds'].get(l) or {}
        for k, x in effect.items():
            if k in BOOSTER_NAME:
                row(l).setdefault('m', []).append([BOOSTER_NAME[k], x / 100.0])
            else:
                stats(l, 'booster_' + k.lower(), x / 100.0, 'p')
        h = hour.get(l) or BOOSTER.B['sure_sn'] / 3600          # mağaza boosterının süresi (booster.add)
        stats(l, 'sure', h, 'sa')
        if effect:
            row(l)['ph'] = {'HOURS': '%g' % h, 'BOOSTERVALUE': next(iter(effect.values()))}
    for l, v in GM.M.items():
        if 'unstable' in v:
            unstable = v['unstable']
            row(l)['gm'] = unstable.get('preference', [])
            stats(l, 'en_az', unstable.get('en_az'), 'p')
            a = unstable['interval']
            stats(l, 'value_range', '%d-%d%%' % tuple(a['buyuk']) + (' / %d-%d%%' % tuple(a['lowercase']) if a.get('lowercase') else ''), 't')
            stats(l, 'reroll', unstable['restabilize']['right'])
        else:
            row(l)['gm'] = v.get('ships', [])
            bonus(l, v.get('effects'))
    for l, v in PC.CANNONS.items():
        stats(l, 'base_damage', v.get('base'))
        stats(l, 'element', v.get('element'), 'e')
        stats(l, 'extra_attribute', v.get('ek'))
        stats(l, 'reroll', PC.rerolls(l))
    for l, v in PC.SHIELDS.items():
        stats(l, 'savunma', v.get('savunma'))
        stats(l, 'element', v.get('element'), 'e')
        stats(l, 'extra_attribute', v.get('ek'))
        stats(l, 'reroll', PC.rerolls(l))
    for l, v in PC.DRIVES.items():
        stats(l, 'hasar', v.get('hasar'))
        stats(l, 'shot', v.get('shot'))
    for l, v in PC.LENSES.items():
        stats(l, 'savunma', v.get('savunma'))
    for l, v in QF.TYPES.items():
        stats(l, 'quality', v.get('quality'))
        stats(l, 'value_range', '%g-%g%%' % tuple(v['interval']), 't')
        stats(l, 'max_level', QF.MAX_LV)
    for l, v in PETM.GEARS.items():
        for k, label in (('menzil', 'menzil'), ('sure_sn', 'sure_sn'), ('bekleme_sn', 'cooldown')):
            if isinstance(v.get(k), list):
                stats(l, label, ' / '.join(str(x) for x in v[k]), 't')
    for l, v in PETM.PROTOCOLS.items():
        for k, x in v.items():
            if isinstance(x, list) and k != 'price' and all(isinstance(y, (int, float)) for y in x):
                stats(l, 'level_bonus', ' / '.join('%g%%' % (y * 100) for y in x), 't')
                row(l)['ph'] = {'amount': '%g' % (x[0] * 100)}
    return {'esyalar': out}


# ------------------------------------------------------------------ profil ve mağaza
def open_save(path):
    """Profil ve oyunun mağazası (hangar kuralları, ödül yolu; profil_araci.ver gibi)."""
    import galaxy_gates as KAPI
    import new_systems as NS
    from player_profile import Profile
    from shop import Shop
    notes = []
    pr = Profile(PA._load('login.json').get('seed'), path)
    m = Shop(pr, PA._load('responses.json'), notes.append)
    m.gates = KAPI.Gates(pr, notes.append)
    m.new_ = NS.NewSystems(pr, m, notes.append)
    return pr, m


def levels():
    return PA._load('levels.json').get('seviyeler') or [[1, 0]]


def level_of(ep):
    lv = 1
    for level, need in levels():
        if ep >= need:
            lv = level
    return lv


def _item(p, i):
    """Takılı ya da envanterdeki eşyanın kısa kaydı: kimlik, lootId, P.E.T. seviyesi (seviyeli dişli ve protokolde), yükseltme seviyesi."""
    import pet as PETM
    l = p.d['esyalar'].get(str(i))
    if not l:
        return None
    out = {'id': int(i), 'lootId': l}
    up = p.d.get('upgrade_level', {}).get(str(i))
    if PETM.has_levels(l):
        out['seviye'] = p.item_level(i)
    if up:
        out['upgrade'] = int(up)
    r = rng_record(p, i, l)
    if r:
        out['rng'] = r
    return out


# ------------------------------------------------------------------ rastgele nitelikli eşyalar
def rng_kind(l):
    """Eşyanın rastgele nitelik türü: modul (kararsız modül), pc (parçacık topu, kırıcı, sürücü, mercek), qfc ya da None."""
    import ship_module as GM
    import particle as PC
    import qfc as QF
    return 'modul' if GM.unstable(l) else 'pc' if PC.is_item(l) else 'qfc' if l in QF.TYPES else None


def rng_pool(l):
    """Düzenleme penceresinin seçenekleri: nitelik adları, birim (kesir ya da yüzde), değer sınırı, hak sınırı, yıldız sınırı."""
    import ship_module as GM
    import particle as PC
    import qfc as QF
    t = rng_kind(l)
    if t == 'modul':
        a = GM.M[l]['unstable']['interval']
        return {'nitelik': list(GM.SECONDARY), 'unit': 'fraction', 'max_attributes': 3, 'right': GM.restab(l)['right'],
                'interval': [a['buyuk'][0], (a.get('lowercase') or a['buyuk'])[1]], 'preference': GM.M[l]['unstable'].get('preference', [])}
    if t == 'pc':
        if l in PC.DRIVES or l in PC.LENSES:
            pool = {k: v for k, v in PC.D['attributes']['drive'].items() if not k.startswith('_')}
            return {'nitelik': sorted(pool), 'unit': 'yuzde', 'max_attributes': len(PC.D['lock']['seviyeler']), 'right': 0,
                    'interval': [min(v[0] for v in pool.values()), max(v[1] for v in pool.values())]}
        pool, tier = PC.pool(l), PC.tier(l)
        return {'nitelik': sorted(pool), 'unit': 'yuzde', 'max_attributes': len(pool), 'right': PC.rerolls(l),
                'interval': [min(v[tier][0] for v in pool.values()), max(v[tier][1] for v in pool.values())],
                'star': len(PC.C['star']) - 1 if l in PC.CANNONS else 0}
    if t == 'qfc':
        k = QF.kind(l)
        (lo, hi), _, top = QF.ranges(l)
        return {'nitelik': sorted(set(QF.D['initial_attributes'][k]) | set(QF.D['extra_attribute'][k])), 'unit': 'yuzde', 'interval': [lo, round(top, 2)],
                'max_attributes': QF.D['max_attributes'], 'max_level': QF.MAX_LV}
    return None


def rng_record(p, i, l):
    """Örneğin rastgele nitelikleri (henüz çekilmediyse yalnız tür: düzenleyince çekilir)."""
    t = rng_kind(l)
    if not t:
        return None
    key = {'modul': 'unstable', 'pc': 'particle', 'qfc': 'qfc'}[t]
    rec = p.d.get(key, {}).get(str(i))
    out = {'tur': t}
    if rec:
        out.update(nitelik=rec.get('nitelik') or rec.get('attributes') or [], right=rec.get('right'), ships=rec.get('ships'),
                   gemi=rec.get('gemi'), seviye=rec.get('seviye'), star=rec.get('star'))
    return {k: v for k, v in out.items() if v is not None}


def stats(pr):
    """İstatistik sekmesi (salt okunur; oyuncu isteği 2026-10-30): rütbe puanının parçaları, uzaylı ve oyuncu öldürmeleri, ölümler,
    kapılar (tamamlama ve süreler: kapi.sure_yaz), modların en iyileri."""
    import ranks as RT
    import galaxy_gates as GT
    c = RT.counters(pr)
    npc = sorted(([RT.R['npc_points'].get(k, {}).get('ad', '#' + k).strip(), int(n), RT.R['npc_points'].get(k, {}).get('puan', 0)]
                  for k, n in c['npc'].items() if n), key=lambda x: -x[1])
    player = sorted(([RT.R['ship_points'].get(k, {}).get('ad', k.replace('ship_', '')), int(n)] for k, n in c['player'].items() if n),
                    key=lambda x: -x[1])
    roster_row = (pr.d.get('kapilar') or {}).get('kapilar') or {}
    duration = pr.d.get('gate_times') or {}
    gates = [{'anahtar': k, 'ad': GT.KAPI[k]['ad'], 'tamam': int((roster_row.get(k) or {}).get('tamam', 0)), **(duration.get(k) or {})}
               for k in GT.KAPI if (roster_row.get(k) or {}).get('tamam') or k in duration]
    pve = pr.d.get('pve') or {}
    return {'puan': RT.breakdown(pr), 'npc': npc, 'player': player,
            'olum': {'enemy': c['death_by_enemy'], 'radiation': c['death_by_radiation'], 'other': c['death_other']},
            'gorev': c['gorev'], 'friendly': c['friendly'], 'kapilar': gates,
            'modes': {'ebl': int((pve.get('ebl') or {}).get('best', 0)), 'labyrinth': int((pr.d.get('labyrinth') or {}).get('hunts', 0)),
                       'mimesis': int(max((pr.d.get('mimesis') or {}).get('trips') or [0]))},
            'play_sec': int(pr.d.get('play_sec') or 0)}


def appearance(pr, m, original=None):
    import shop as SHP
    import pet as PETM
    import upgrades as UPG
    import map_links as H
    p, pl = pr, pr.d['pilot']
    lv_tab = levels()
    lv = pl.get('level', 1)
    next_ = next((need for l, need in lv_tab if l == lv + 1), None)
    base = next((need for l, need in lv_tab if l == lv), 0)
    places = p.item_places()
    max_upgrade = {}

    def maximum(l):
        if l not in max_upgrade:
            max_upgrade[l] = UPG.max_level(l)
        return max_upgrade[l]

    ships = []
    for sid, g in p.d['ships'].items():
        slots = [y for _p, y in SHP.SLOTS if m.capacity(y, sid) > 0]
        configs, drones, pet = {}, {}, {}
        for cid in sorted(g['configs']):
            cfg = p.config(cid, sid)
            configs[cid] = {y: {'capacity': m.capacity(y, sid, cid), 'esyalar': [e for e in (_item(p, i) for i in cfg.get(y, [])) if e]}
                              for y in slots}
            dcfg = p.drone_config(cid, sid)
            drones[cid] = {str(x['kimlik']): {'esyalar': [e for e in (_item(p, i) for i in dcfg.get(str(x['kimlik']), [])) if e],
                                               'tasarim': _item(p, p.drone_design_id(x, 'design', cid, sid)),
                                               'appearance': _item(p, p.drone_design_id(x, 'visual', cid, sid))}
                            for x in p.d['drones']}
            if m.pet.owned:
                pc = m.pet.config(cid, sid)
                pet[cid] = {y: {'capacity': m.pet.open_slots(y), 'esyalar': [e for e in (_item(p, i) for i in pc.get(y, [])) if e]}
                            for y in PETM.ALL_SLOTS}
        row = p.ship_row(sid)
        st = m.stats(sid)
        damage = sum(SHP.ITEMS['lasers'].get(l, {}).get('hasar', 0) for l in p.loadout(sid).get('laser', []))
        ships.append({'id': sid, 'lootId': g['lootId'], 'tasarim': g.get('tasarim'), 'appearance': p.ship_look(sid), 'active': sid == p.d['active_ship'],
                        'favorite': bool(g.get('favorite')), 'active_config': str(g['active_config']), 'slots': slots, 'configs': configs,
                        'drones': drones, 'pet': pet or None, 'designs': m.designs(sid),
                        'position': g.get('position'), 'registered': bool(g.get('saved_config')),
                        'value': {'can': st.get('hp_max') or row.get('hp'), 'kalkan': st.get('shield_max'), 'hiz': st.get('display'),
                                  'kargo': row.get('kargo'), 'hasar': damage, 'lazer': st.get('lasers')}})
    ships.sort(key=lambda x: (not x['active'], not x['favorite'], int(x['id'])))

    def targets(l):
        h = (['ship'] if SHP.slot_of(l) else []) + (['drone'] if SHP.drone_ok(l) or l in SHP.DESIGNS else [])
        return h + (['pet'] if PETM.slot_for(l) else [])
    inventory = []
    for i, l in p.d['esyalar'].items():
        if l.startswith(('drone_', 'ship_')):
            continue
        place = places.get(int(i))                       # equipped items stay listed with their ship and configs (other config can use them)
        if place and not targets(l):
            continue
        e = _item(p, i)
        e.update(targets=targets(l), yuva=SHP.slot_of(l) or PETM.slot_for(l) or ('tasarim' if l in SHP.DESIGNS else 'other'),
                 pet_yuva=PETM.slot_for(l), heat=bool(PETM.heat_slot_ok(l)), azami=maximum(l),
                 gemi=place[0] if place else None, configs=sorted(place[1]) if place else [])
        inventory.append(e)
    for g in ships:                                  # takılı eşyaların yükseltme sınırı (seviye penceresi)
        for c in list(g['configs'].values()) + [d for per in g['drones'].values() for d in per.values()] + list((g['pet'] or {}).values()):
            for e in c['esyalar'] if 'esyalar' in c else []:
                e['azami'] = maximum(e['lootId'])
    drone_list = []
    for x in p.d['drones']:
        info = SHP.DRONES.get(x['lootId'], {})
        drone_list.append({'id': x['kimlik'], 'lootId': x['lootId'], 'seviye': x.get('seviye', 1), 'puan': x.get('puan', 0),
                   'upgrade': int(x.get('upgrade', 0)), 'max_upgrade': UPG.max_level(x['lootId']) or 16,
                   'capacity': info.get('yuva', 1), 'tek': bool(info.get('tek'))})
    petd = m.pet.d if m.pet.owned else None
    pet = None
    if petd:
        pet = {'ad': petd.get('ad'), 'seviye': petd.get('seviye', 0), 'ep': petd.get('ep', 0), 'fuel': int(petd.get('fuel', 0)),
               'max_fuel': PETM.PET['max_fuel'], 'max_level': len(PETM.PET['seviyeler']) - 1, 'destroyed': bool(petd.get('destroyed')),
               'yuva': {y: m.pet.open_slots(y) for y in PETM.SLOTS}, 'max_slots': dict(PETM.PET['max_slots']),
               'heat': m.pet.heat_lv()}
    ammo = [[l, int(n), next((t for pre, t in AMMO if l.startswith(pre)), 'other')] for l, n in sorted(p.d.get('ammunition', {}).items())]
    minerals = {m_['oreType']['typeValue']: m_['count'] for m_ in p.d.get('ores', [])}
    ores = [[int(t), loot, int(minerals.get(int(t), 0))] for t, loot in sorted(SHP.ITEMS['ores']['kinds'].items(), key=lambda kv: int(kv[0]))]
    now = time.time()
    boosters = [[l, int(max(0, (b.get('bitis') or 0) - now) + (b.get('kalan') or 0))] for l, b in sorted(p.d.get('boosters', {}).items())]
    k = p.d.get('position', {})
    quests = p.d.get('quests', {})
    out = {
        'pilot': {'ad': pl.get('userName'), 'firma': pl.get('factionId'), 'seviye': lv, 'ep': pl.get('ep', 0), 'level_base': base,
                  'next_level': next_, 'max_level': lv_tab[-1][0], 'onur': pl.get('honourPoints', 0), 'kredi': pl.get('credits', 0),
                  'uridyum': pl.get('uridium', 0), 'premium': bool(pl.get('premium')), 'klan': pl.get('clanTag') or '',
                  'rutbe': (p.d.get('rutbe') or {}).get('rutbe'), 'bank': p.d.get('bank', 0), 'play_sec': int(p.d.get('play_sec') or 0),
                  'created': p.d.get('created'), 'skill_points': (p.d.get('skills') or {}).get('puan', 0)},
        'durum': {'can': int(p.d['gemi'].get('hitPoints', 0)), 'max_hp': p.d['gemi'].get('hitMax', 0),
                  'kalkan': int(p.d['gemi'].get('shield', 0)), 'shield_max': p.d['gemi'].get('shieldMax', 0),
                  'harita': k.get('mapId'), 'map_name': H.name(k.get('mapId', 0)), 'main_map': H.name(HOME_MAP.get(pl.get('factionId'), 5)),
                  'kargo': p.cargo_used(), 'cargo_max': p.d['gemi'].get('cargoSpaceMax', 0)},
        'ships': ships, 'active_ship': p.d['active_ship'], 'drones': drone_list, 'max_drones': SHP.ITEMS['max_drones'],
        'drone_levels': [x['puan'] for x in SHP.LEVELS], 'pet': pet, 'pet_slots': list(PETM.ALL_SLOTS),
        'inventory': inventory, 'ammunition': ammo, 'ores': ores,
        'sources': [[l, int(n)] for l, n in sorted(p.d.get('other_items', {}).items()) if isinstance(n, (int, float))],
        'boosters': boosters,
        'quests': {'active': len(quests.get('active', {})), 'tamam': len(quests.get('tamam', []))},
        # hakla çalışan CPU'lar (Jump CPU, Cloak …): lootId -> [kalan, bir dolumun hakkı]; hak lootId başına (ekstra.py)
        'haklar': {l: [int(p.d.get('extra_uses', {}).get(l, SHP.EX.X[l]['right'])), SHP.EX.X[l]['right']]
                   for l in sorted(set(p.d['esyalar'].values())) if 'right' in SHP.EX.X.get(l, {})},
        'pools': {l: rng_pool(l) for l in sorted(set(p.d['esyalar'].values())) if rng_kind(l)},
        'all_ships': sorted(SHP.ITEMS['ships']),
        'stats': stats(p),
    }
    if original:
        out['diff'] = diff(original, p.d)
    return out


# ------------------------------------------------------------------ fark özeti (taslak ile asıl kayıt)
def _layout(d):
    """Takılı eşyaların yeri: (gemi, config, bölüm, eşya) kümesi."""
    out = set()
    for sid, s in d.get('ships', {}).items():
        for key in ('configs', 'drone_config', 'pet_config'):
            for cid, cfg in s.get(key, {}).items():
                for slot, ids in cfg.items():
                    out |= {(sid, cid, key, slot, i) for i in ids}
        for cid, cfg in s.get('drone_design', {}).items():
            for did, per in cfg.items():
                out |= {(sid, cid, 'tasarim', did, i) for i in per.values() if i}
    return out


def diff(a, b):
    """Asıl kayıttan (a) taslağa (b) değişenler: alanlar [ad, eski, yeni], eklenen/çıkan eşya (lootId -> adet), adet farkları
    [lootId, eski, yeni], donanım (yeri değişen eşya sayısı), gemiler, dronlar."""
    pa, pb = a.get('pilot', {}), b.get('pilot', {})
    fields = [[k, pa.get(f), pb.get(f)] for k, f in (('ad', 'userName'), ('firma', 'factionId'), ('seviye', 'level'), ('ep', 'ep'),
                                                     ('kredi', 'credits'), ('uridyum', 'uridium'), ('onur', 'honourPoints'),
                                                     ('premium', 'premium')) if pa.get(f) != pb.get(f)]
    if a.get('active_ship') != b.get('active_ship'):
        fields.append(['active_ship', a['ships'].get(a.get('active_ship'), {}).get('lootId'),
                        b['ships'].get(b.get('active_ship'), {}).get('lootId')])
    if a.get('position', {}).get('mapId') != b.get('position', {}).get('mapId'):
        import map_links as H
        fields.append(['harita', H.name(a.get('position', {}).get('mapId', 0)), H.name(b.get('position', {}).get('mapId', 0))])
    if int(a.get('gemi', {}).get('hitPoints', 0)) != int(b.get('gemi', {}).get('hitPoints', 0)):
        fields.append(['can', int(a['gemi'].get('hitPoints', 0)), int(b['gemi'].get('hitPoints', 0))])
    say = lambda d: {l: sum(1 for x in d.values() if x == l) for l in set(d.values())}
    items_a, items_b = say(a.get('esyalar', {})), say(b.get('esyalar', {}))
    ga = say({k: s['lootId'] for k, s in a.get('ships', {}).items()})
    gb = say({k: s['lootId'] for k, s in b.get('ships', {}).items()})
    da = say({str(x['kimlik']): x['lootId'] for x in a.get('drones', [])})
    db = say({str(x['kimlik']): x['lootId'] for x in b.get('drones', [])})
    added, leaving = {}, {}
    for x, y in ((items_a, items_b), (ga, gb), (da, db)):
        for l in set(x) | set(y):
            n = y.get(l, 0) - x.get(l, 0)
            if n > 0:
                added[l] = added.get(l, 0) + n
            elif n < 0:
                leaving[l] = leaving.get(l, 0) - n
    counts = []
    for key in ('ammunition', 'other_items'):
        counts_a, counts_b = a.get(key, {}), b.get(key, {})
        counts += [[l, int(counts_a.get(l, 0)), int(counts_b.get(l, 0))] for l in sorted(set(counts_a) | set(counts_b))
                    if isinstance(counts_a.get(l, 0), (int, float)) and isinstance(counts_b.get(l, 0), (int, float)) and int(counts_a.get(l, 0)) != int(counts_b.get(l, 0))]
    import shop as SHP
    ma = {m['oreType']['typeValue']: m['count'] for m in a.get('ores', [])}
    mb = {m['oreType']['typeValue']: m['count'] for m in b.get('ores', [])}
    counts += [[SHP.ORES.get(t, str(t)), int(ma.get(t, 0)), int(mb.get(t, 0))] for t in sorted(set(ma) | set(mb)) if ma.get(t, 0) != mb.get(t, 0)]
    ba, bb = a.get('boosters', {}), b.get('boosters', {})
    boost = sorted(l for l in set(ba) | set(bb) if ba.get(l) != bb.get(l))
    level = []
    counts_a = {x['kimlik']: x for x in a.get('drones', [])}
    for x in b.get('drones', []):
        y = counts_a.get(x['kimlik'])
        if y and (y.get('seviye'), y.get('upgrade', 0)) != (x.get('seviye'), x.get('upgrade', 0)):
            level.append(x['lootId'])
    upgrades_a, upgrades_b = a.get('upgrade_level', {}), b.get('upgrade_level', {})
    level += [b['esyalar'][i] for i in set(upgrades_a) | set(upgrades_b) if upgrades_a.get(i, 0) != upgrades_b.get(i, 0) and i in b.get('esyalar', {})]
    for key in ('unstable', 'particle', 'qfc'):                    # rastgele nitelikler (düzenleme penceresi)
        ra, rb = a.get(key, {}), b.get(key, {})
        level += [b['esyalar'][i] for i in rb if ra.get(i) and ra[i] != rb[i] and i in b.get('esyalar', {})]
    charges_a, hb = a.get('extra_uses', {}), b.get('extra_uses', {})
    counts += [[l, int(charges_a.get(l, 0)), int(hb[l])] for l in sorted(hb) if charges_a.get(l) != hb[l]]
    pet_of = lambda d:{k: (d.get('pet') or {}).get(k) for k in ('ad', 'seviye', 'ep', 'fuel', 'destroyed', 'yuva')}
    if pet_of(a) != pet_of(b):
        level.append('pet')
    layout_a, layout_b = _layout(a), _layout(b)
    hardware = len({t[-1] for t in layout_a ^ layout_b})
    return {'fields': fields, 'added': added, 'leaving': leaving, 'counts': counts, 'boosters': boost, 'seviyeler': level,
            'hardware': hardware,
            'sayi': len(fields) + len(added) + len(leaving) + len(counts) + len(boost) + len(level) + (1 if hardware else 0)}


# ------------------------------------------------------------------ işlemler
def _int(v, lo, hi):
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Sayı bekleniyordu: %s', str(v))


def _result(msgs, name):
    """Oyunun yanıt komutundan başarı ya da ret nedeni (BaseKey adı)."""
    import shop as SHP
    cmd = next((x[1] for x in msgs or [] if isinstance(x, tuple) and x[0] == name), None) or {}
    ok = (cmd.get('resultId') if 'resultId' in cmd else cmd.get('result')) == 1
    if not ok:
        e = cmd.get('errorMessage') or cmd.get('description') or {}
        if e.get('type') == 1:                         # ham metin: magaza.neden (istemcinin dili yok: İngilizcesi)
            key = next((k for k, (en, _tr) in SHP.REASONS.items() if en == e.get('stringBasekey')), e.get('stringBasekey'))
        else:
            key = {v: k for k, v in SHP.BASEKEY.items()}.get(e.get('enumBaseKey'))
        if key in REJECTS:
            raise ValueError(REJECTS[key])
        raise ValueError('Oyun bu işleme izin vermedi: %s', key or '?')


def op_pilot(pr, m, o):
    pl = pr.d['pilot']
    if 'ad' in o:
        import re
        name = str(o['ad']).strip()
        if not re.fullmatch(r'[\w\-\.\[\]\(\) ]{3,20}', name, re.UNICODE):
            raise ValueError('Pilot adı 3-20 karakter olmalı.')
        pl['userName'] = name
    for key, field, lo, hi in (('kredi', 'credits', 0, 10 ** 12), ('uridyum', 'uridium', 0, 10 ** 12),
                               ('onur', 'honourPoints', -10 ** 12, 10 ** 12)):
        if key in o:
            pl[field] = _int(o[key], lo, hi)
    if 'seviye' in o:                                  # seviye: EP o seviyenin eşiği (oyun da seviyeyi EP'den hesaplar)
        pl['level'], pl['ep'] = PA.level_ep(_int(o['seviye'], 1, 10 ** 3))
    if 'ep' in o:
        pl['ep'] = _int(o['ep'], 0, 2 ** 62)
        pl['level'] = level_of(pl['ep'])
    if 'premium' in o:
        pl['premium'] = bool(o['premium'])
    if 'firma' in o and int(o['firma']) != pl.get('factionId'):
        f = int(o['firma'])
        if f not in COMPANIES:
            raise ValueError('Firma seçin (MMO, EIC ya da VRU).')
        pl['factionId'] = f
        home_base(pr)                                     # öbür firmanın haritasında kalmasın
    pr.dirty = True


def home_base(pr):
    mid = HOME_MAP.get(pr.d['pilot'].get('factionId'), 5)
    pos = PA.station_pos(mid)
    if not pos:
        raise ValueError('Ana istasyonun konumu bulunamadı.')
    pr.d['position'] = {'mapId': mid, 'x': pos[0], 'y': pos[1]}
    for s in pr.d['ships'].values():                 # gemilerin bekledikleri yer de (etkinleştirince oraya gidilirdi)
        s.pop('position', None)
    pr.dirty = True


def op_give(pr, m, o):
    """Eşya ver (oyunun ödül yolu); tak verilirse ({gemi, konfig, hedef, dron, kume}) yeni eşyalar oraya takılır (ödül yolu boş yuvası
    olan etkin gemiye takmış olabilir: önce oradan iner). Hedefin yuvası dolunca kalanlar envanterde kalır."""
    known = PA.known_loots()
    equip = o.get('equip')
    for loot, n in o.get('esyalar') or []:
        loot = str(loot)
        if loot not in known and not loot.startswith(('ammunition_', 'resource_', 'ship_', 'drone_', 'booster_')):
            raise ValueError('Bilinmeyen eşya: %s', loot)
        if '_design_' not in loot and any(s['lootId'] == loot for s in pr.d['ships'].values()):
            raise ValueError('Bu gemi zaten hangarda: %s', loot)        # oyunda her gemiden bir tane (ödül yolu atlar)
        before = set(pr.d['esyalar'])
        m.reward(loot, _int(n, 1, 10 ** 9))
        if not equip:
            continue
        new_ = [int(i) for i, l in pr.d['esyalar'].items() if i not in before and l == loot]
        busy, active = pr.equipped_ids(), pr.ship()
        for k, i in enumerate(new_):
            if i in busy:
                m.handle('HangarShipMoveItemsRequest', {'items': [i], 'source': 'ship', 'destination': 'inventory', 'droneId': 0, 'slotSet': '',
                                                        'configId': int(active['active_config']), 'hangarId': active['hangarId']})
            try:
                op_move(pr, m, dict(equip, direction='equip', esya=i))
            except ValueError:
                if not k:                              # hiçbiri takılamadıysa oyunun nedeni
                    raise
                break


def op_move(pr, m, o):
    sid = str(o.get('gemi'))
    if sid not in pr.d['ships']:
        raise ValueError('Gemi bulunamadı.')
    equip, target = o.get('direction') == 'equip', o.get('hedef') if o.get('hedef') in ('ship', 'drone', 'pet') else 'ship'
    f = {'items': [int(i) for i in (o.get('esyalar') or [o.get('esya')])], 'source': 'inventory' if equip else target,
         'destination': target if equip else 'inventory', 'configId': int(o.get('config') or 1), 'hangarId': pr.ship(sid)['hangarId'],
         'droneId': int(o.get('drone') or 0), 'slotSet': 'default' if target == 'drone' else 'heat' if o.get('set') == 'heat' else ''}
    _result(m.handle('HangarShipMoveItemsRequest', f), 'HangarShipMoveItemsCommand')


def op_delete(pr, m, o):
    """Takılı olmayan eşyaları sil (satmadan)."""
    busy = pr.equipped_ids()
    for i in o.get('esyalar') or []:
        i = int(i)
        if i in busy:
            raise ValueError('Takılı eşya silinemez: önce çıkar.')
        pr.d['esyalar'].pop(str(i), None)
        for k in ('item_level', 'upgrade_level'):
            pr.d.get(k, {}).pop(str(i), None)
    pr.dirty = True


def op_active_ship(pr, m, o):
    msgs, _changed = m.activate({'shipId': str(o.get('gemi'))}, in_station=True, travel=True)
    _result(msgs, 'HangarShipActivateShipCommand')


def op_config(pr, m, o):
    sid = str(o.get('gemi') or pr.d['active_ship'])
    ship = pr.ship(sid)
    n = str(_int(o.get('config'), 1, 2))
    if n in ship['configs']:
        ship['active_config'] = int(n)
        pr.sync_equipment()
        m.apply_stats()
        pr.dirty = True


def op_design(pr, m, o):
    msgs, _reload = m.change_model({'shipId': str(o.get('gemi')), 'lootId': str(o.get('lootId') or '')})
    _result(msgs, 'HangarShipChangeShipModelCommand')


def op_favorite(pr, m, o):
    _result(m.handle('HangarShipFavouriteRequest', {'shipId': str(o.get('gemi')), 'favourite': bool(o.get('favorite'))}),
           'HangarShipFavouriteCommand')


def op_clear(pr, m, o):
    _result(m.handle('HangarShipClearConfigRequest', {'wipe': 0, 'configId': int(o.get('config') or 1), 'shipId': str(o.get('gemi'))}),
           'HangarShipClearConfigCommand')


def op_import(pr, m, o):
    _result(m.handle('HangarShipImportConfigRequest', {'originShipId': str(o.get('gemi')), 'targetShipId': str(o.get('hedef'))}),
           'HangarShipImportConfigCommand')


def op_delete_ship(pr, m, o):
    """Gemiyi hangardan kaldır; üstündeki donanım envantere iner (takılılık gemilerin config'lerinden hesaplanır)."""
    sid = str(o.get('gemi'))
    if sid not in pr.d['ships']:
        raise ValueError('Gemi bulunamadı.')
    if sid == pr.d['active_ship']:
        raise ValueError('Etkin gemi kaldırılamaz: önce başka bir gemiyi etkin yap.')
    del pr.d['ships'][sid]
    pr.dirty = True


def op_drone(pr, m, o):
    import shop as SHP
    x = pr.drone(o.get('drone') or 0)
    if not x:
        raise ValueError('Dron bulunamadı.')
    if 'seviye' in o:                                  # seviye ve puanı: seviyenin eşiği
        x['seviye'] = _int(o['seviye'], 1, len(SHP.LEVELS))
        x['puan'] = max(SHP.LEVELS[x['seviye'] - 1]['puan'], min(int(x.get('puan', 0)),
                        SHP.LEVELS[x['seviye']]['puan'] - 1 if x['seviye'] < len(SHP.LEVELS) else 10 ** 9))
    if 'upgrade' in o:
        import upgrades as UPG
        x['upgrade'] = _int(o['upgrade'], 0, UPG.max_level(x['lootId']) or 16)
    pr.sync_equipment()
    pr.dirty = True


def op_delete_drone(pr, m, o):
    """Dronu kaldır (satmadan): her gemide üstündeki eşyalar ve tasarımları envantere iner."""
    x = pr.drone(o.get('drone') or 0)
    if not x:
        raise ValueError('Dron bulunamadı.')
    for s in pr.d['ships'].values():
        for c in s.get('drone_config', {}).values():
            c.pop(str(x['kimlik']), None)
        for c in s.get('drone_design', {}).values():
            c.pop(str(x['kimlik']), None)
    pr.d['drones'].remove(x)
    pr.sync_equipment()
    pr.dirty = True


def op_item_level(pr, m, o):
    """Eşyanın yükseltme seviyesi (Assembly: 0 = yükseltilmemiş) ya da P.E.T. dişlisinin / protokolünün seviyesi (1-4)."""
    import upgrades as UPG
    import pet as PETM
    i = str(int(o.get('esya') or 0))
    loot = pr.d['esyalar'].get(i)
    if not loot:
        raise ValueError('Eşya bulunamadı.')
    if 'upgrade' in o:
        n = _int(o['upgrade'], 0, UPG.max_level(loot))
        lv = pr.d.setdefault('upgrade_level', {})
        if n:
            lv[i] = n
        else:
            lv.pop(i, None)
    if 'seviye' in o and PETM.has_levels(loot):
        n = _int(o['seviye'], 1, 4)
        lv = pr.d.setdefault('item_level', {})
        if n > 1:
            lv[i] = n
        else:
            lv.pop(i, None)
    pr.sync_equipment()
    m.apply_stats()
    pr.dirty = True


def op_ammo(pr, m, o):
    c = pr.d.setdefault('ammunition', {})
    for loot, n in (o.get('counts') or {}).items():
        if not str(loot).startswith('ammunition_'):
            raise ValueError('Bilinmeyen eşya: %s', loot)
        c[loot] = _int(n, 0, 10 ** 12)
        pr.item_id(loot)                              # istemcinin sayaç kimliği (yeni cephane türü)
    pr.dirty = True


def op_ore(pr, m, o):
    cur = {mm['oreType']['typeValue']: mm['count'] for mm in pr.d.get('ores', [])}
    for t, n in (o.get('counts') or {}).items():
        cur[int(t)] = _int(n, 0, 10 ** 9)
    pr.d['ores'] = [{'_': 'OreCountModule', 'oreType': {'_': 'OreTypeModule', 'typeValue': t}, 'count': n}
                        for t, n in sorted(cur.items()) if n > 0]
    pr.sync_cargo()
    pr.dirty = True


def op_resource(pr, m, o):
    d = pr.d.setdefault('other_items', {})
    for loot, n in (o.get('counts') or {}).items():
        if not str(loot).startswith('resource_'):
            raise ValueError('Bilinmeyen eşya: %s', loot)
        n = _int(n, 0, 10 ** 12)
        if n:
            d[loot] = n
        else:
            d.pop(loot, None)
    pr.dirty = True


def op_booster(pr, m, o):
    """Booster süresi (saniye): uzaylıdan düşen booster gibi saklanır (çevrimdışı durur); 0 kaldırır."""
    import booster as BOOSTER
    b = pr.d.setdefault('boosters', {})
    for loot, sec in (o.get('durations') or {}).items():
        if not BOOSTER.is_booster(loot):
            raise ValueError('Bilinmeyen eşya: %s', loot)
        sec = _int(sec, 0, 10 ** 8)
        if sec:
            b[loot] = {'bitis': 0, 'kalan': float(sec)}
        else:
            b.pop(loot, None)
    m.apply_stats()
    pr.dirty = True


def op_pet(pr, m, o):
    import pet as PETM
    if o.get('give') and not m.pet.owned:
        m.grant_pet(str(o.get('ad') or ''))
    d = pr.d.get('pet')
    if not d:
        raise ValueError('Bu kayıtta P.E.T. yok.')
    if 'ad' in o and str(o['ad']).strip():
        d['ad'] = str(o['ad']).strip()[:24]
    if 'seviye' in o:
        d['seviye'] = _int(o['seviye'], 0, len(PETM.PET['seviyeler']) - 1)
        d['ep'] = PETM.PET['seviyeler'][d['seviye']]['ep']
    if 'fuel' in o:
        d['fuel'] = _int(o['fuel'], 0, PETM.PET['max_fuel'])
    for y, n in (o.get('yuva') or {}).items():
        if y in PETM.SLOTS:
            d.setdefault('yuva', {})[y] = _int(n, 0, PETM.PET['max_slots'].get(y, 0))
    if o.get('repair'):
        d['destroyed'] = False
        d['can'] = m.pet.hp_max()
    pr.dirty = True


def op_rng(pr, m, o):
    """Rastgele nitelikli eşyanın kaydı: nitelikler [[ad, değer]] (havuzdan, tekrarsız; modülde kesir, ötekilerde yüzde), modülün
    gemileri, QFC'nin bağlı gemisi ve seviyesi, yeniden çekme hakkı, topun yıldızı. Kayıt yoksa önce oyundaki gibi çekilir."""
    import ship_module as GM
    import particle as PC
    i = str(int(o.get('esya') or 0))
    loot = pr.d['esyalar'].get(i)
    t = loot and rng_kind(loot)
    if not t:
        raise ValueError('Bu eşyanın düzenlenecek rastgele niteliği yok.')
    pool = rng_pool(loot)
    if t == 'modul':
        rec = GM.state(pr, i)
    elif t == 'pc':
        rec = PC.ensure(pr, i)
    else:
        rec = pr.d.setdefault('qfc', {}).setdefault(i, {'gemi': pr.ship()['lootId'], 'seviye': 1, 'attributes': []})
    if 'nitelik' in o:
        ns = [[str(a), v] for a, v in o['nitelik'] or []]
        names = [a for a, _v in ns]
        if not ns or len(ns) > pool['max_attributes'] or len(set(names)) != len(names) or any(a not in pool['nitelik'] for a in names):
            raise ValueError('Nitelikler geçersiz: havuzdan, tekrarsız ve en çok %s tane.', str(pool['max_attributes']))
        try:
            vals = [max(0.0, min(1.0 if pool['unit'] == 'fraction' else 1000.0, float(v))) for _a, v in ns]
        except (TypeError, ValueError):
            raise ValueError('Sayı bekleniyordu: %s', str([v for _a, v in ns]))
        rec['attributes' if t == 'qfc' else 'nitelik'] = [[a, round(v, 4)] for a, v in zip(names, vals)]
    if 'ships' in o and t == 'modul':
        gs = sorted({str(g) for g in o['ships'] or []})
        if not gs or any(g not in GM.all_ships() for g in gs):
            raise ValueError('Gemi seçin.')
        rec['ships'] = gs
    if 'gemi' in o and t == 'qfc':
        if str(o['gemi']) not in GM.all_ships():
            raise ValueError('Gemi seçin.')
        rec['gemi'] = str(o['gemi'])
    if 'seviye' in o and t == 'qfc':
        rec['seviye'] = _int(o['seviye'], 1, pool['max_level'])
    if 'right' in o and pool.get('right') is not None and t != 'qfc':
        rec['right'] = _int(o['right'], 0, pool['right'])
    if 'star' in o and pool.get('star'):
        rec['star'] = _int(o['star'], 0, pool['star'])
    pr.sync_equipment()
    m.apply_stats()
    pr.dirty = True


def op_cpu_charges(pr, m, o):
    """Hakla çalışan CPU'nun kalan hakkı (ekstra_haklari; lootId başına, oyunda yeniden doldurulur)."""
    import shop as SHP
    loot = str(o.get('lootId') or '')
    if 'right' not in SHP.EX.X.get(loot, {}):
        raise ValueError('Bilinmeyen eşya: %s', loot)
    pr.d.setdefault('extra_uses', {})[loot] = _int(o.get('right'), 0, 10 ** 6)
    pr.dirty = True


def op_repair(pr, m, o):
    g = pr.d['gemi']
    g['hitPoints'], g['shield'] = g.get('hitMax', g.get('hitPoints', 1)), g.get('shieldMax', g.get('shield', 0))
    g['nanoHull'] = 0
    pr.dirty = True


def op_home_base(pr, m, o):
    home_base(pr)


def op_reset(pr, m, o):
    PA.reset_d(pr.d, [x for x in o.get('sections') or [] if x])
    pr.dirty = True


def op_keybinds(pr, m, o):
    import saves as SAV
    pr.d['key_bindings'] = SAV.default_key_bindings()
    pr.dirty = True


OPS = {'pilot': op_pilot, 'give': op_give, 'carry': op_move, 'delete': op_delete, 'active_ship': op_active_ship, 'config': op_config,
            'tasarim': op_design, 'favorite': op_favorite, 'clean_up': op_clear, 'import_action': op_import, 'delete_ship': op_delete_ship, 'drone': op_drone,
            'drone_delete': op_delete_drone, 'item_level': op_item_level, 'ammunition': op_ammo, 'cevher': op_ore, 'kaynak': op_resource,
            'booster': op_booster, 'pet': op_pet, 'repair': op_repair, 'home_base': op_home_base, 'keybinds': op_keybinds, 'reset': op_reset,
            'rng': op_rng, 'cpu_charges': op_cpu_charges}


def apply(path, ops, original=None):
    pr, m = open_save(path)
    for o in ops:
        fn = OPS.get(o.get('islem'))
        if not fn:
            raise ValueError('Bilinmeyen işlem: %s', str(o.get('islem')))
        fn(pr, m, o)
    pr.sync_equipment()
    pr.save(force=True)
    return appearance(*open_save(path), original=_read(original))


def _read(path):
    if not path:
        return None
    with open(path, encoding='utf8') as fh:
        return json.load(fh)


def main(argv):
    if argv[:1] == ['read'] and len(argv) in (2, 3):
        return appearance(*open_save(argv[1]), original=_read(argv[2] if len(argv) > 2 else None))
    if argv[:1] == ['apply'] and len(argv) in (3, 4):
        return apply(argv[1], json.loads(argv[2]), argv[3] if len(argv) > 3 else None)
    if argv[:1] == ['catalog'] and len(argv) == 1:
        return catalog()
    if argv[:1] == ['info'] and len(argv) == 1:
        return info()
    raise ValueError('kullanım: save_editor.py oku <yol> [asıl] | uygula <yol> <json> [asıl] | katalog')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf8')
    try:
        out = main(sys.argv[1:])
        print(json.dumps(dict(out, ok=True), ensure_ascii=False))
    except Exception as e:
        template = e.args[0] if isinstance(e, ValueError) and e.args and isinstance(e.args[0], str) else None
        msg = (template % e.args[1:] if len(e.args) > 1 else template) if template else str(e)
        print(json.dumps({'ok': False, 'hata': '%s: %s' % (type(e).__name__, msg), 'template': template, 'arg': [str(a) for a in e.args[1:]]},
                         ensure_ascii=False))
