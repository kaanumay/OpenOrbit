"""Harita bağlantıları: istemcinin kendi spacemap-config.xml dosyasındaki portallar (data/spacemap-config.xml).

Her portal: bulunduğu harita (ref), gittiği harita (leadsToMap) ve 315×210'luk ipucu haritasındaki konumu.
Oyun içi konum, standart harita boyutuna (21000×13100) ölçeklenip DarkOrbit'in portal ızgarasına oturtulur;
kayıtla doğrulandı: 2-1 (2000,11500) -> 2-2, 2-2 (18500,2000) -> 2-1, (2000,11500) -> 2-3, (18500,11500) -> 2-4.
Portal kimliği = 150000167 + key (kayıttaki 150000182/183/177/184 ile birebir).
"""
import math, os, random, re

import map_layout as ML

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, 'data', 'spacemap-config.xml')
GATE_ID_BASE = 150000167
MAP_W, MAP_H = 21000, 13100
JUMP_RADIUS = 600          # kayıt: (2514,11402) yakın, (2504,11050) değil -> ~520–670 arası
JUMP_DELAY_SEC = 3.05       # kayıt: JumpInitiatedCommand -> JumpToServerCommand 3,05 sn
GATE_PEACE_RADIUS = 1000   # kayıt: 2-1 portalına 818 birimde BeaconCommand.inPeaceArea true, 1171'de false (GG kapıları hariç)
# istemcinin yardımı (dmz_position_p, dmz_warning_p): portal DMZ'si yalnız kendi firmanın haritalarında; savaş haritalarında (4-1..4-4)
# yok, 4-5'te portaldan geçtikten sonra 15 sn
NO_DMZ_MAPS = {'4-1', '4-2', '4-3', '4-4'}
DMZ_AFTER_JUMP_SEC = {'4-5': 15}
# Demilitarized zone around the pilot's own company Mission Control (quest giver). Matters for the stand-alone X-5 beacons; the X-1 and
# X-8 ones already sit inside the station's zone (peaceRadius 1800, giver 1080 units from the centre). The wikis give no radius and no
# recording covers X-5, so it uses the measured portal DMZ (GATE_PEACE_RADIUS). A foreign Mission Control is not usable (dunya.start)
# and gives no protection, like a foreign station. Black Light Mission Controls have none: "All BL maps feature Demilitarised zones on
# the portals but not on the mission control centre" (darkorbit.fandom.com/wiki/Demilitarized_zone); 4-X battle maps have none either.
GIVER_PEACE_RADIUS = GATE_PEACE_RADIUS


def giver_dmz(map_id):
    """Does a quest giver on this map have a demilitarized zone?"""
    n = name(map_id)
    return n not in NO_DMZ_MAPS and n not in DMZ_AFTER_JUMP_SEC and not n.startswith('BL-')
NAMES = {}
LEVELS = {}                # istemcinin maps-config.xml'i: harita -> (habitant, foreign) gereken seviye (kendi / başka firma)
SCALE = {}                 # istemcinin maps-config.xml'i: scaleFactor 2 olan haritalar (4-4, 4-5, 5-1, 5-3) iki kat büyük


def _snap_x(x):
    if x < 80:
        return 2000
    if x > 235:
        return 18500
    return int(round(x * MAP_W / 315 / 100.0)) * 100


def _snap_y(y):
    if y < 60:
        return 2000
    if y > 150:
        return 11500
    return int(round(y * MAP_H / 210 / 100.0)) * 100


def _load():
    gates = {}
    mc = os.path.join(HERE, 'data', 'maps-config.xml')
    if os.path.exists(mc):
        # yorumdaki tanımlar istemcide yok (istemci gerçek XML ayrıştırıcıyla okuyor): eski Frozen Labyrinth bloğu (430-445,
        # scaleFactor 2) yorum içinde, etkin tanımlar Escort ve Eternal Gate (21000x13100). Yorum okununca 430-445 iki kat
        # büyük sanılıyordu (Ö4 araştırması, belgeler/wiki/etkinlikler/mimesis_mutiny.json)
        text = re.sub(r'<!--.*?-->', '', open(mc, encoding='utf8').read(), flags=re.S)
        for mid, scale_factor in re.findall(r'<map id="(\d+)"[^>]*scaleFactor="([\d.]+)"', text):
            SCALE[int(mid)] = float(scale_factor)
        for mid, body in re.findall(r'<map id="(\d+)"[^>]*>(.*?)</map>', text, re.S):
            lv = re.search(r'<level [^>]*habitant="(\d+)"[^>]*foreign="(\d+)"', body)
            if lv:
                LEVELS[int(mid)] = (int(lv.group(1)), int(lv.group(2)))
    if not os.path.exists(SRC):
        return gates
    text = open(SRC, encoding='utf8').read()
    for m in re.finditer(r'<jumpgate key="(\d+)" ref="(\d+)">(.*?)</jumpgate>', text, re.S):
        key, ref, body = int(m.group(1)), int(m.group(2)), m.group(3)
        pos = re.search(r'<position x="(\d+)" y="(\d+)"', body)
        to = re.search(r'<leadsToMap>(\d+)</leadsToMap>', body)
        if not pos or not to:
            continue
        scale_factor = SCALE.get(ref, 1.0) if SCALE.get(ref, 1.0) > 1 else 1.0
        g = dict(gateId=GATE_ID_BASE + key, key=key, x=int(_snap_x(int(pos.group(1))) * scale_factor), y=int(_snap_y(int(pos.group(2))) * scale_factor),
                 hedef=int(to.group(1)))
        fac, own = re.search(r'<faction>(\w+)</faction>', body), re.search(r'<visibleOwnFaction>(\w+)</visibleOwnFaction>', body)
        if fac:
            g['firma'] = FACTIONS.get(fac.group(1))
        if fac and own and own.group(1) == 'true':
            g['yalniz_firma'] = FACTIONS.get(fac.group(1))       # 5-X'te her firmanın kendi portalı (yalnız o firmaya görünür)
        gates.setdefault(ref, []).append(g)
    for m in re.finditer(r'^\s*(\d+)\s+(\d-\d|\d-BL|BL-\d)\s*$', text, re.M):
        NAMES[int(m.group(1))] = m.group(2)
    return gates


FACTIONS = {'mmo': 1, 'eic': 2, 'vru': 3}
PLAYER_FACTION = None        # oyuncunun firması (game.py girişte): yalnız-firma portallarının süzgeci
GATES = _load()
# istemcinin maps-config.xml'inde olup spacemap-config.xml'de olmayan haritalar (yol haritası Aşama 4): 5-4 (Darksilver korsanları),
# Cubikon Mezarlığı ("???"), LoW (Lord of War)
EXTRA_NAMES = {94: '5-4', 42: '???', 200: 'LoW'}
for _m, _n in EXTRA_NAMES.items():
    NAMES.setdefault(_m, _n)
SPECIAL = {42, 200}              # Cubikon Mezarlığı, LoW: atlama CPU'su listesinde yok; mezarlıktan çıkış atlama CPU'suyla
# kayıttaki 2-1'in eğitim portalı (designId 55; istemcinin ipucu "This Jump Gate takes you to Tutorial."): sunucuda eğitim haritası
# yok, atlama "Jump not possible" diyordu. 10. seviyeden sonra gönderilmez (kullanıcı bildirimi 2026-10-24)
TUTORIAL_GATE, TUTORIAL_MAX_LEVEL = 150000774, 10
# sunucunun eklediği portallar (wiki): 5-4'ün portalı 5-2'de (giriş bir Gümüş Booty Key; istemcinin metni
# msg_hidden_pirate_map_no_silverkey; resmî sunucu kaydı: 5-X'teki gibi her firmanın bir portalı), 5-4'ten 5-2'ye dönüş; LoW'un
# portalı X-3'te (low.py).
# (harita, anahtar, x, y, hedef, ek alanlar); portal kimliği GATE_ID_BASE + anahtar (istemcinin anahtarları 920042'ye kadar)
_SILVER = {'ucret': 'gumus_anahtar', 'ipucu': 'ttip_jumpgate_hiddenPirateMap'}
# LoW portalı: resmî sunucu kaydı 2026-10-27, 1-3 ve 2-3'te (2000, 2000), 3-3'te (18500, 2000); tasarım 34
LOW_DESIGN = 34
LOW_START = (1000, 11800)       # LoW'a girişin varış yeri: haritanın sol alt köşesi (wiki "lower left corner"; emu-dark LowPortal.cs)
EXTRA_GATES = [(92, 990006, 18500, 11500, 94, dict(_SILVER, firma=1, yalniz_firma=1)),
               (92, 990001, 18500, 11500, 94, dict(_SILVER, firma=2, yalniz_firma=2)),
               (92, 990007, 18500, 11500, 94, dict(_SILVER, firma=3, yalniz_firma=3)),
               (94, 990002, 4000, 13000, 92, {}),
               (3, 990003, 2000, 2000, 200, {'low': True, 'varis': LOW_START, 'tasarim': LOW_DESIGN}),
               (7, 990004, 2000, 2000, 200, {'low': True, 'varis': LOW_START, 'tasarim': LOW_DESIGN}),
               (11, 990005, 18500, 2000, 200, {'low': True, 'varis': LOW_START, 'tasarim': LOW_DESIGN})]
for _m, _k, _x, _y, _to, _extra in EXTRA_GATES:
    GATES.setdefault(_m, []).append(dict(gateId=GATE_ID_BASE + _k, key=_k, x=_x, y=_y, hedef=_to, **_extra))
# korsan ve Black Light haritalarının portalları düzendeki yerlerinde (ipucu ızgarasına oturtulan yer kabaca); varış yeri portala
# bağlı (5-X: hedefte kırık portalın yanı; 5-3'ten 4-4'e rastgele): harita_duzeni.json
for _m, _gs in GATES.items():
    for _g in _gs:
        _p, _v = ML.gate_pos(_m, _g['key']), ML.arrival(_m, _g['key'])
        if _p:
            _g['x'], _g['y'] = _p
        if _v:
            _g['varis'] = _v
# korsan haritalarının portalları (resmî sunucu kaydı 2026-10-25): 4-5'ten 5-1'e ve 5-X'te her firmanın portalı tasarım 51, firması süs
# (decoratorAssetTypes); 5-X'te başka firmanınki mini haritada ve balonsuz görünmez, atlanamaz (gates). Varış hedefte aynı firmanın tek
# yönlü portalı (tasarım 52, hep görünmez; harita_duzeni.json varis_portallari). 'tasarim': 'designId' yalnız sonradan eklenenlerde
# (dunya.resend onları yeniden bildirir)
PIRATE_MAPS = {91, 92, 93}
ENTRY_DESIGN, ONE_WAY_DESIGN = 51, 52
ONE_WAY_GATE_BASE = GATE_ID_BASE + 991000        # tek yönlü portalların kimliği: + harita x 10 + firma
for _m, _gs in GATES.items():
    for _g in _gs:
        if _g.get('firma') and (_m in PIRATE_MAPS or _g['hedef'] in PIRATE_MAPS):
            _g.update(tasarim=ENTRY_DESIGN, decorations=[_g['firma']])
# maps-config 5-X için 1 yazıyor; wiki seviye 12 (belgeler/wiki/maps.md)
for _m, _n in NAMES.items():
    if _n.startswith('5-'):
        LEVELS[_m] = (12, 12)


# istasyonlu haritalar -> firma: X-1 (istemcinin maps-config.xml'inde home="n") ve X-8 (wiki: Home Base)
STATION_MAPS = {1: 1, 5: 2, 9: 3, 20: 1, 24: 2, 28: 3}
FACTION_NAME = {1: 'MMO', 2: 'EIC', 3: 'VRU'}
# istasyonsuz haritada ölünce doğulan yer: seviye 12+ ve üst haritalarda (X-5 … X-8, 4-4, 4-5) firmanın X-8'i (VRU için 3-8), yoksa X-1
# (fandom 4-4, Base, Uppers: "level 12 or higher ... respawn on X-8"; 5-2'nin korsan üssüne hiç doğulmaz)
X8_HOME = {1: 20, 2: 24, 3: 28}
UPPERS = ('X-5', 'X-6', 'X-7', 'X-8', '4-4', '4-5')
# X-8'in üssü ön karakol: istemcinin AssetType'ı COMPANY_HQ_OUTPOST 47, HANGAR_OUTPOST 49, ORE_TRADE_OUTPOST 51, INSTANT_REPAIR_OUTPOST
# 54, STATION_TURRET_*_OUTPOST 56/58 (lib_assets *_outpost_<firma>, metinler "Corporate Outpost", "Outpost Hangar" …; kayıtta X-8 yok)
OUTPOST = {46: 47, 48: 49, 50: 51, 53: 54, 55: 56, 57: 58}
OUTPOST_MAPS = {20, 24, 28}
TPL_CENTER = (19000, 2000)          # kayıttaki 2-1 istasyonunun merkezi (SpaceStationCommand)
CORNERS = [(19000, 2000), (2000, 2000), (19000, 11100), (2000, 11100)]
# istasyonun ve yapının oyundaki yeri (merkez); yazılmayan haritada portallardan en uzak köşe. 2-8: üst orta (resmî sunucu kaydı
# 2026-10-25); 1-8 sol, 3-8 sağ kenarın ortası (fandom 1-8/3-8; Kalaazu ve 2009 emülatörü y 6000); 5-2 pazarı ortada (fandom 5-2,
# darkorbitwiki harita görseli). 5-2'nin korsan istasyonu ve X-BL'nin görev vericisi harita_duzeni.json'da (yapi)
STATION_POS = {24: (10500, 2000), 20: (2000, 6750), 28: (19000, 6750), 9: (19000, 11500)}
# üs düzeninin 2-1'inkine göre dönüşü (derece; X-8'de ön karakolun dönüşüne eklenir). Resmî sunucu kaydı 2026-10-27: 1-1'de hangar
# merkezin doğusunda, görev verici güneyinde; 3-1'de görev verici kuzeyinde; 1-8, 3-8 de 270 / 90 derece; 2-1, 2-8 kayıttaki gibi
STATION_TURN = {1: 270, 9: 90, 20: 270, 28: 90}
# ön karakolun düzeni ana üssünkinin -45 derece dönmüşü (resmî sunucu kaydı: 2-8'in binaları merkezden 763 birim çaprazda, 16 küçük
# taret 1.800 birimlik çemberde (1800, 0)'dan başlayarak; 2-1'de binalar 1.080 birim dikte). 1-8 ve 3-8 ölçülmedi: aynı
OUTPOST_TURN = -math.pi / 4


def map_world(map_id, tpl):
    """Kayıtta olmayan haritanın dünya mesajları {'giris', 'hazir'} ('_m' anahtarlı): portallar istemcinin spacemap-config.xml'inden.
    İstasyonlu haritalarda kayıttaki 2-1 istasyonu (tpl) oyundaki yerine (STATION_POS), yoksa portallardan en uzak köşeye
    taşınır (X-8'in ön karakolu dönerek: OUTPOST_TURN); firma, nesne kimlikleri ve bölge adları haritaya göre değişir. Görev verici de
    taşınır (tasarımı ve adı haritanın firmasına göre: quest_giver; firması kayıttaki gibi 0). 5-X'te bütün firmaların portalları gider
    (başkasınınki görünmez) ve tek yönlü varış portalları."""
    gs = gates(map_id)
    gate_msgs = [dict(jumpgate_create(g, PLAYER_FACTION)[1], _m='JumpgateCreateCommand') for g in GATES.get(int(map_id), [])] + \
                [dict(jumpgate_create(dict(gateId=ONE_WAY_GATE_BASE + int(map_id) * 10 + f, x=x, y=y, designId=ONE_WAY_DESIGN,
                                           decorations=[f], invisible=True))[1], _m='JumpgateCreateCommand')
                 for x, y, f in ML.one_way_gates(map_id)]
    fac = STATION_MAPS.get(int(map_id))
    if not fac or not tpl:
        entry, ready = structure(map_id, tpl, gs) if tpl else ([], [])
        if int(map_id) in LOW_STATION:
            w, h = map_size(map_id)
            ready.append({'_m': 'SpaceStationCommand', 'posX': w // 2, 'posY': h // 2, 'peaceRadius': 0, 'id': 0,
                          'type': LOW_STATION[int(map_id)]})
        return {'giris': entry, 'hazir': ready + gate_msgs + ML.poi_msgs(map_id)}
    cx, cy = STATION_POS.get(int(map_id)) or max(CORNERS, key=lambda c: min((math.hypot(c[0] - g['x'], c[1] - g['y']) for g in gs),
                                                                            default=0))
    turn = (OUTPOST_TURN if int(map_id) in OUTPOST_MAPS else 0) + math.radians(STATION_TURN.get(int(map_id), 0))
    cos, sin = math.cos(turn), math.sin(turn)

    def place(x, y):
        ox, oy = x - TPL_CENTER[0], y - TPL_CENTER[1]
        return int(round(cx + ox * cos - oy * sin)), int(round(cy + ox * sin + oy * cos))

    base = 151000000 + int(map_id) * 100
    ids, entry, ready = {}, [], []
    for m in tpl.get('giris', []):
        if m['_m'] == 'AssetCreateCommand':                    # görev verici (34) dahil: görevlere dönüş her ana istasyonda
            ids[m['assetId']] = base + len(ids)
            x, y = place(m['posX'], m['posY'])
            a = quest_giver(dict(m, posX=x, posY=y, factionId=m['factionId'] if m['type']['typeValue'] == QUEST_GIVER else fac,
                                 assetId=ids[m['assetId']]), map_id)
            if int(map_id) in OUTPOST_MAPS and a['type']['typeValue'] in OUTPOST:
                a['type'] = dict(a['type'], typeValue=OUTPOST[a['type']['typeValue']])
            entry.append(a)
    for m in tpl.get('giris', []):
        if m['_m'] == 'MapAssetActionAvailableCommand' and m['mapAssetId'] in ids:
            entry.append(dict(m, mapAssetId=ids[m['mapAssetId']]))
    for m in tpl.get('hazir', []):
        if m['_m'] == 'SpaceStationCommand':
            ready.append(dict(m, posX=cx, posY=cy, type=fac))
        elif m['_m'] == 'MapAddPOICommand':
            pid = m['poiId']
            if pid.startswith(('mapAssetRangeZone-', 'questGiver_')):       # nesnenin yaklaşma bölgesi
                old = int(re.split('[-_]', pid)[-1])
                if old not in ids:
                    continue
                pid = pid[:-len(str(old))] + str(ids[old])
            else:
                pid = pid.replace('EIC', FACTION_NAME[fac])
            sc = list(m['shapeCoordinates'])
            sc[0], sc[1] = place(sc[0], sc[1])
            ready.append(dict(m, poiId=pid, shapeCoordinates=sc))
    return {'giris': entry, 'hazir': ready + gate_msgs}


# istasyon dışı yapılar (wiki haritalar: X-5 ve X-BL'de Mission Control, 5-2'de Trader); kayıttaki 2-1 istasyonunun görev vericisi
# (AssetCreateCommand türü 34) ya da rafinerisi (50) kopyalanır, portallardan en uzak köşeye. Clan Battle Station'lar (klan yok) yok.
# X-4 (1-4, 2-4, 3-4): oyuncu bildirimi 2026-10-27, gerçek oyunda Mission Control var (yeri kaynakta yok: portallardan uzak nokta,
# uyarlama; model X-5'in işareti)
STRUCTURES = {4: 34, 8: 34, 12: 34, 17: 34, 21: 34, 25: 34, 306: 34, 307: 34, 308: 34, 92: 50}
# yapının görünümü: rafineri (50) istemcide "refinery_home_<firma>" modeliyle çizilir, firmasız (5-2) hiç görünmüyordu (canlı deneme
# 2026-10-17). 5-2'nin Trader'ı istemcinin "station_6" korsan istasyonu (lib_assets: "big sausage pirate station", mini haritada
# minimap_piratestation): SpaceStationCommand type 6 (güvenli bölgesi harita_duzeni.json'da); ticaret noktası ORE_TRADE_INVISIBLE (52,
# "refinery_invisible_0": modeli yok, tıklama simgesi ve mini harita simgesi var). Süs istasyonu: tamir/doğma yeri değil
# (game.Sablonlar.station bunu atlar).
STRUCTURE_STATION = {92: 6}
STRUCTURE_ASSET_TYPE = {92: 52}
# LoW'un ortasındaki korsan HQ'su (low.json: ilk röleden sonra çevresinde iyileştirme bölgesi, boss burada doğar): istemcinin "station_4" LoW istasyonu
# (SpaceStationCommand type 4, mini haritada healthStation). Süs istasyonu: güvenli bölgesi yok, tamir/doğma yeri değil.
LOW_STATION = {200: 4}
DECOR_STATION_TYPES = set(STRUCTURE_STATION.values()) | set(LOW_STATION.values())


def structure(map_id, tpl, gs):
    """İstasyonsuz haritanın tek yapısı -> (giriş mesajları, hazır mesajları)."""
    kind = STRUCTURES.get(int(map_id))
    src = next((m for m in tpl.get('giris', []) if m['_m'] == 'AssetCreateCommand' and m['type']['typeValue'] == kind), None)
    if not kind or not src:
        return [], []
    spots = CORNERS + [(10500, 6550), (10500, 2000), (10500, 11100), (2000, 6550), (19000, 6550)]   # köşeler, kenar ortaları, merkez
    cx, cy = ML.structure_pos(map_id) or STATION_POS.get(int(map_id)) or max(spots, key=lambda c: min((math.hypot(c[0] - g['x'], c[1] - g['y']) for g in gs),
                                                                          default=0))
    aid = 151000000 + int(map_id) * 100 + 90
    pos, radius = ML.structure_asset(map_id)      # 5-2: ticaret noktası istasyonun yanında
    ax, ay = pos or (cx, cy)
    entry = [quest_giver(dict(src, assetId=aid, posX=ax, posY=ay, factionId=src['factionId'] if kind == QUEST_GIVER else company(map_id) or 0),
                         map_id)]
    if int(map_id) in STRUCTURE_ASSET_TYPE:
        entry[0]['type'] = dict(src['type'], typeValue=STRUCTURE_ASSET_TYPE[int(map_id)])
    ready = []
    if int(map_id) in STRUCTURE_STATION:          # 5-2 korsan üssünün güvenli bölgesi (harita_duzeni.json guvenli; dunya.in_peace)
        peace = next((r for x, y, r in ML.safe_zones(map_id) if (x, y) == (cx, cy)), 0)
        ready.append({'_m': 'SpaceStationCommand', 'posX': cx, 'posY': cy, 'peaceRadius': peace, 'id': 0,
                      'type': STRUCTURE_STATION[int(map_id)]})
    for m in tpl.get('hazir', []):                # yaklaşma bölgesi (görev vericininki questGiver_<kimlik>)
        if m['_m'] == 'MapAddPOICommand' and m['poiId'] in ('mapAssetRangeZone-%d' % src['assetId'], 'questGiver_%d' % src['assetId']):
            sc = list(m['shapeCoordinates'])
            sc[0], sc[1], sc[2] = ax, ay, radius or sc[2]
            ready.append(dict(m, poiId=m['poiId'].replace(str(src['assetId']), str(aid)), shapeCoordinates=sc))
    return entry, ready


def quest_giver(m, map_id):
    """Görev vericinin modeli ve adı haritanın firmasına ve üs türüne göre (kayıtta yalnız 2-1'inki var: designId 6, Reginald
    Crowley). İstemcinin lib_assets'i: questgiver_3/6/9 MMO/EIC/VRU ana üs (X-1), 4/7/10 outpost (X-8), 5/8/11 beacon (X-5),
    12 Black Light; adlar eh_character_descr_*."""
    fac, n = company(map_id), name(map_id)
    if m['type']['typeValue'] != QUEST_GIVER or not fac:
        return m
    design = 12 if n.startswith('BL-') else QUEST_GIVER_DESIGN[n[2:]] + 3 * (fac - 1)
    return dict(m, designId=design, userName=BL_QUEST_GIVER_NAME if n.startswith('BL-') else QUEST_GIVER_NAME[fac])


def gates(map_id, faction=None):
    """faction: oyuncunun firması (arkadaş sunucusunda her oyuncunun kendisi; verilmezse PLAYER_FACTION): kendi firmasının portalları önde."""
    fac = faction if faction is not None else PLAYER_FACTION
    # başka firmanın portalı görünmez ama çalışır (oyuncu bildirimi 2026-10-27: gerçek oyunda korsan haritalarında hepsi atlanıyor);
    # kendi firmanınki önce gelir: arrival() geri dönüş portalını ilk eşleşmeden alır
    return sorted(GATES.get(int(map_id), []), key=lambda g: bool(g.get('yalniz_firma')) and fac not in (None, g['yalniz_firma']))


def arrival(src_map, dst_map, faction=None):
    """Hedef haritada, kaynak haritaya geri götüren portalın konumu (gemi oraya iner). faction: oyuncunun firması (gates)."""
    back = next((g for g in gates(dst_map, faction) if g['hedef'] == int(src_map)), None)
    if back:
        return back['x'], back['y']
    w, h = map_size(dst_map)          # tek yönlü giriş (5-1, 5-3, 4-4): haritanın gerçek ortası (büyük haritalar)
    return center(dst_map) if ML.of(dst_map).get('center') else (w // 2, h // 2)


def random_arrival(map_id):
    """Rastgele varış yeri (5-3'ün çıkışları 4-4'e; emu-dark Vector.Random): kenarlardan uzak, engellerin dışında."""
    w, h = map_size(map_id)
    return ML.free_spot(map_id, (2000, 2000, w - 2000, h - 2000)) or (w // 2, h // 2)


def name(map_id):
    return NAMES.get(int(map_id), str(map_id))


def company(map_id):
    """Haritanın firması (1 MMO, 2 EIC, 3 VRU: X-n ve n-BL) ya da None (4-X, 5-X, kapılar: ortak)."""
    n = name(map_id)
    if n.startswith('BL-') and n[3:] in ('1', '2', '3'):         # istemcinin adı BL-1 (1-BL)
        return int(n[3:])
    return int(n[0]) if len(n) >= 3 and n[0] in '123' and n[1] == '-' else None


def level_required(map_id, faction):
    """Haritaya girmek için gereken seviye: kendi firmanın ya da ortak harita habitant, başka firmanınki foreign (maps-config;
    wiki ile aynı: X-1/X-2 1, X-3 2, 4-X 8-10, X-5 10, X-8 12; başka firmanın X-1'i 16)."""
    import settings as SET
    if SET.get('seviye_kisiti_yok'):
        return 0                          # panel: seviye kısıtları kapalı
    hab, foreign = LEVELS.get(int(map_id), (0, 0))
    c = company(map_id)
    return foreign if c and c != faction else hab


def map_size(map_id):
    """Haritanın boyu: standart boy x istemcinin maps-config.xml scaleFactor'ı (4-4, 4-5, 5-x 2; GG Hades 0.5)."""
    scale_factor = SCALE.get(int(map_id), 1.0)
    return int(MAP_W * scale_factor), int(MAP_H * scale_factor)


def map_class(map_id):
    """Şirket haritaları için X-n (1-3 ve 2-3 -> X-3), diğerleri kendi adı."""
    n = name(map_id)
    return 'X-' + n[2:] if len(n) == 3 and n[0] in '123' and n[1] == '-' and n[2].isdigit() else n


def x8_home(faction, level, map_id):
    """Ölünen harita istasyonsuzsa doğulacak firmanın X-8 haritası; seviye 12'nin altında ya da üst harita değilse None (X-1)."""
    return X8_HOME.get(faction) if level >= 12 and map_class(map_id) in UPPERS else None


# istasyon nesneleri: yaklaşınca tıklanabilir olur (kayıt: ~500 birimde MapAssetActionAvailableCommand state 0, uzaklaşınca 1)
STATION_ASSETS = {46: 'ttip_company_hq', 48: 'ttip_hangar', 50: 'ttip_ore_trade', 52: 'ttip_ore_trade',   # HQ, hangar, rafineri (52: görünmez)
                  53: 'ttip_instant_repair', 54: 'ttip_instant_repair',     # tamir istasyonu (ana üs / karakol; Ö1)
                  47: 'ttip_company_hq', 49: 'ttip_hangar', 51: 'ttip_ore_trade'}     # X-8 ön karakolu (OUTPOST)
REPAIR_ASSETS = (53, 54)         # InstantRepairRequest: onarım kuponuyla anında onarım (dunya.instant_repair)
ASSET_RANGE = 500
QUEST_GIVER = 34                 # AssetCreateCommand.type: görev verici (kayıt: Reginald Crowley, 2-1)
QUEST_GIVER_DESIGN = {'1': 3, '8': 4, '5': 5, '4': 5}                  # X-1, X-8, X-5: MMO'nunki; EIC +3, VRU +6 (quest_giver)
QUEST_GIVER_NAME = {1: 'Morgus Petterson', 2: 'Reginald Crowley', 3: 'Vanessa Arkadium'}
BL_QUEST_GIVER_NAME = 'Mysterious Outpost'        # resmî sunucu kaydı 2026-10-27 (2-BL)


def asset_available(asset_id, tip, near, wild=()):
    """İstasyon nesnesi (kayıttaki biçim): yakınken state 0, etkin, ipucuyla; uzakken state 1, ipucu boş. wild: [(%ALAN%, metin)]
    (tamir istasyonunun kupon sayıları)."""
    reps = [{'_': 'MessageWildcardReplacementModule', 'wildcard': k, 'replacement': str(v),
             'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}} for k, v in wild]
    lines = [{'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': reps, 'baseKey': tip,
              'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}] if near else []
    return ('MapAssetActionAvailableCommand', dict(mapAssetId=asset_id, state=0 if near else 1, activatable=near,
                                                   toolTip={'_': 'MessageKeyListWildcardCommand', 'commandList': lines},
                                                   additionalInformation={'_': 'AssetInformationModule'}))


def jumpgate_create(g, faction=None):
    """faction: oyuncunun firması; 5-X'te başka firmanın portalı görünmez gider (resmî sunucu kaydı: mini haritada yok, balonsuz)."""
    hidden = g.get('invisible') or (g.get('yalniz_firma') and faction not in (None, g['yalniz_firma']))
    return ('JumpgateCreateCommand', dict(gateId=g['gateId'], factionId=0, designId=g.get('designId', g.get('tasarim', 1)), x=g['x'],
                                          y=g['y'], isVisibleOnMinimap=not (hidden or g.get('gizli')),   # 4-5'teki gizli solucan deliği
                                          showBubble=not hidden, decoratorAssetTypes=g.get('decorations', [])))


# Kapı ipuçları (istemcinin flashres anahtarları). Hedefi 0 olan (pencere açan) kapılarda "%MAP%" boş kalıyordu, labirent
# haritalarının istemcideki adı "Escort VRU 1" (canlı test 2026-10-18). Moda giren kapı: modun kendi cümlesi; yoksa
# ttip_jumpgate + %MAP% = adın anahtarı (tür 5) ya da hedef haritanın istemcideki adı (tür 6; maps-config.xml name).
MODE_TIPS = {'voyagers': 'ttip_jumpgate_voyagersascentrial', 'trinity': 'ttip_jumpgate_trinitytrials',
             'astral': 'ttip_jumpgate_astralascension', 'ebl': 'ttip_jumpgate_eternal_blacklight',
             'labirent': 'ttip_jumpgate_frozenLabyrinth'}
DESIGN_TIPS = {87: 'ttip_jumpgate_astralascension_weapon_1', 88: 'ttip_jumpgate_astralascension_weapon_2',          # Astral riftleri
               89: 'ttip_jumpgate_astralascension_generator_1', 90: 'ttip_jumpgate_astralascension_generator_2',
               91: 'ttip_jumpgate_astralascension_ammo_1', 92: 'ttip_jumpgate_astralascension_ammo_2',
               93: 'ttip_jumpgate_astralascension_booster_1', 94: 'ttip_jumpgate_astralascension_booster_1',
               95: 'ttip_jumpgate_astralascension_upgrademodule_1', 96: 'ttip_jumpgate_astralascension_upgrademodule_2',
               97: 'ttip_jumpgate_astralascension_resource_1', 98: 'ttip_jumpgate_astralascension_resource_2',
               99: 'ttip_jumpgate_astralascension_hp_1', 100: 'ttip_jumpgate_astralascension_finalboss'}
MODE_NAMES = {'echoes': 'window_dse_title', 'plutus': 'title_plutus', 'plutus_kolay': 'title_plutus', 'istila': 'title_invasion'}
_CLIENT_MAPS = {}


def client_map_name(map_id):
    """İstemcinin maps-config.xml'indeki harita adı (ipucunun tür 6 değeri buradan) ya da None."""
    if not _CLIENT_MAPS:
        p = os.path.join(HERE, 'data', 'maps-config.xml')
        t = open(p, encoding='utf8').read() if os.path.exists(p) else ''
        _CLIENT_MAPS.update({int(i): n for i, n in re.findall(r'<map id="(\d+)"[^>]*?\bname="([^"]*)"', t)} or {0: None})
    return _CLIENT_MAPS.get(int(map_id or 0))


def gate_tip(g):
    """Portalın ipucu -> (anahtar, [(yer tutucu değeri, tür)]): tür 5 flashres anahtarı, 6 harita kimliği, 0 düz metin."""
    if g.get('ipucu'):
        return g['ipucu'], ([(str(g['hint_target']), 6)] if g.get('hint_target') else [])
    dest = int(g.get('hint_target') or g.get('hedef') or 0)
    if not g.get('cikis') and dest not in NAMES:                       # galaksi dışına (moda, kapıya) giden kapı
        key = DESIGN_TIPS.get(g.get('designId')) or MODE_TIPS.get(g.get('kapi'))
        if key:
            return key, []
        if MODE_NAMES.get(g.get('kapi')):
            return 'ttip_jumpgate', [(MODE_NAMES[g['kapi']], 5)]
    if dest and client_map_name(dest):
        return 'ttip_jumpgate', [(str(dest), 6)]
    if g.get('ad'):
        return 'ttip_jumpgate', [(g['ad'], 0)]
    return 'faq_jumpgate', []                                           # "Atlama kapısı"


def gate_available(g, near):
    """Portala yaklaşınca/uzaklaşınca (kayıttaki biçim): state 0 + etkin, ya da state 1 + etkin değil. İpucu "This Jump Gate takes
    you to %MAP%.": kayıtta %MAP% = hedef haritanın kimliği, tür 6 (istemci haritanın adını yazar); öteki kapılar gate_tip."""
    key, vals = gate_tip(g)
    reps = [{'_': 'MessageWildcardReplacementModule', 'wildcard': '%MAP%', 'replacement': v,
             'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': t}} for v, t in vals]
    tip = {'_': 'MessageKeyListWildcardCommand', 'commandList': [
        {'_': 'MessageKeyListWildcardModule', 'wildCardReplacements': reps, 'baseKey': key,
         'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': 5}, 'textStyle': 0}]}
    return ('MapAssetActionAvailableCommand', dict(mapAssetId=g['gateId'], state=0 if near else 1, activatable=near, toolTip=tip,
                                                   additionalInformation={'_': 'AssetInformationModule'}))


def parked(map_id):
    """Gemi bu haritada bırakılabilir mi (hangarda değişince orada bekler): bilinen, özel (mezarlık, LoW) olmayan harita."""
    return map_id in NAMES and map_id not in SPECIAL


def center(map_id):
    """Haritanın ortası; ortası engelliyse düzenin 'merkez'i (DSE 3: iniş, dost gemi, salona dönüş portalı)."""
    w, h = map_size(map_id)
    return tuple(ML.of(map_id).get('center') or (w // 2, h // 2))
