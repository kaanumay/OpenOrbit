"""Savaş eşyaları ve etkin CPU'lar: mayınlar, Smart Bomb, Insta-Shield, EMP-01, atlama/gizlenme/nişan CPU'ları, otomatik roket ve
fırlatıcı CPU'ları, roket fırlatıcısı, özel roketler. Veri esyalar.json "savas_esyalari", "roketler" ve "ekstralar" (araştırma:
istemcinin kodu, belgeler/wiki/rockets.md, belgeler/wiki/extras_cpu_tech.md). Dünya başına bir Esyalar (dunya.items); kısayol çubuğu
dunya.menu_action'dan, roket AttackRocketRequest'ten gelir.

İstemci (1.1.114) ikili MapEvent* ve JumpCPU* komutlarını işlemez; etkiler eski metin protokolüyle gösterilir:
  AddMineCommand / RemoveMineCommand        mayın koyma / sessiz kaldırma (ömür bitince)
  0|n|MIN|hash                              mayın patlar ve haritadan kalkar
  0|n|SMB|uid  0|n|ISH|uid  0|n|EMP|uid     Smart Bomb, Insta-Shield, EMP görseli
  0|n|INV|uid|1 ya da 0                     gizlenme
  0|A|JCPU|S|sn|harita                      CPU atlamasının geri sayımı (-1|0 iptal); sonra portal atlamasındaki harita değişimi
  0|A|JCPU|I|…  0|A|JCPU|C|…  0|A|JV|n      gelişmiş atlama (AJP-01): harita listesi, seçim yanıtı, kupon sayısı
  0|RL|S|tür|roket|dolu                     fırlatıcı doldukça (ses); HellstormAttackCommand: fırlatıcı atışı
  0|v|saldıran|hedef|H|roket|iz|güdüm       roket (roket = görsel kimliği; iz ve güdüm dunya.rocket_look)
  0|n|fx|start ya da end|ICY_CUBE|uid       donma, SABOTEUR_DEBUFF yavaşlama görseli
Beklemeler MenuItemCooldownGroupTimerCommand ile (grup: istemcinin CooldownType'ı); bitişler profilde (harita değişince de sürer).
"""
import itertools, json, math, os, random, time
import veri as VERI

import ekstra as EK
import harita as H
import harita_duzeni as HD
import ayar as AY
import takvim as TKV
import yetenek as YT
from eski_protokol import legacy

HERE = os.path.dirname(os.path.abspath(__file__))
_E = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
_N = VERI.yukle('npc.json')
S = _E['savas_esyalari']
O6 = json.load(open(os.path.join(HERE, 'data', 'esyalar_o6.json'), encoding='utf8'))       # Ö6: ifadeler (tools/esyalar_o6.py)
EMOTE_PREFIX = 'ammunition_specialammo_emote_'
ROCKETS = _E['roketler']
MINES = S['mayinlar']
# Curcubitor'un Trick mayını etkinlik uzaylısının ölümünde doğar; oyuncu satın almaz ya da koymaz: hasar ve görsel için MINES'ta kalır,
# envanter ve menü işlemlerinden çıkarılır
EVENT_MINES = frozenset({'curcubitor_mayini'})
PLAYER_MINES = frozenset(MINES) - EVENT_MINES
LAUNCHERS = S['fircatici']['turler']
LAUNCHER_AMMO = S['fircatici_cephane']
# Fırlatıcı öğesinin nokta rengi (istemcinin CounterStyle'ı: 0 DEFAULT, 1 RED, 2 GREEN, 3 YELLOW, 4 BLUE, 5 CYAN, 6 ORANGE). Gerçek
# kayıt (20261027_235305): ECO-10 4, HSTRM-01 3, UBR-100 1, BDR1212 5, SAR-02 5. Kayıtta olmayanlar istemcinin simge rengiyle
# (atlas_assets_all): SAR-01 ve PIR-100 camgöbeği, CBR mavi-gri, OBR-100 mor-beyaz (enum'da mor yok: DEFAULT)
LAUNCHER_COLOR = {'ammunition_rocketlauncher_eco-10': 4, 'ammunition_rocketlauncher_hstrm-01': 3,
                  'ammunition_rocketlauncher_ubr-100': 1, 'ammunition_rocketlauncher_bdr1212': 5,
                  'ammunition_rocketlauncher_sar-01': 5, 'ammunition_rocketlauncher_sar-02': 5,
                  'ammunition_rocketlauncher_pir-100': 5, 'ammunition_rocketlauncher_cbr': 4,
                  'ammunition_rocketlauncher_obr-100': 0}
TOGGLES = S['acik_kapa']                      # menü öğesi -> ekstra özelliği (nisan, oto_roket, oto_fircatici)
ALIEN_CPUS = S['uzayli_cpu']                  # Chaos Alien CPU'ları, Cubi Portal -> harita sınıfları, doğan türler
ALIEN_CPUS.update(json.load(open(os.path.join(HERE, 'data', 'etkinlik_kapilari.json'), encoding='utf8')).get('cpu', {}))   # Bountiful (Gauntlet of Plutus; tools/etkinlik_kapilari.py)
FORMATIONS = _E['formasyonlar']               # drone formation menu items: one shared wait between two changes (S['formasyon'])
TOGGLE_DEFAULT = {'nisan': False}             # Xenomit harcar: kendiliğinden açılmaz; ötekiler takılınca açık
XENOMIT = 3
REPBOT_MENU = 'equipment_extra_repbot_rep'
HM7 = 'equipment_extra_hmd-07'                # ticaret dronu: kısayol çubuğu simgesi ticaret penceresini açar (dunya.menu_action)
TIMERS = 'bekleme_gruplari'                   # profilde: {grup: [bitiş, azami ms]}
# havai fişek (K6): istemcinin fireworkDescriptor kimlikleri 31-35 (canlıda istemcinin sözlüğünden okundu; başkası FireWorkInfo.Init'te
# NullReference), sıra istemcinin Ammunition'ı gibi (FIREWORK_1-3, COM, RZ); ateşleme öğesi sayaçsız
FIREWORKS = {'ammunition_firework_fwx-s': 31, 'ammunition_firework_fwx-m': 32, 'ammunition_firework_fwx-l': 33,
             'ammunition_firework_fwx-com': 34, 'ammunition_firework_fwx-rz': 35}
IGNITE = 'ammunition_firework_ignite'
# sprey (K6): istemcide AssetCreateCommand türü SPRAY (69), designId lib_assets.xml'in spray_<n> deseni (sıra oradaki gibi). Bekleme
# grubu istemcinin menüsünden (57); resmî Mimesis Mutiny SSS'si (2020): "last for 30 seconds and have a 45 second cooldown which
# applies to all sprays". İstemci konuma
# (+200, +130) ekleyip resmi 330 birim derine koyuyor: geminin konumu gönderilince resim ekranın altında kalıyordu (canlı K6), SPRAY_KAYMA
# onu geminin altına getirir
SPRAY_KAYMA = (-200, -400)
SPRAY_PREFIX = 'ammunition_specialammo_spray_'
SPRAYS = ['cross', 'hearts', 'ko', 'like', 'skull', 'eggle', 'space-bunny', 'eggtopia', 'easter-eggs', 'shoot', 'heartbreak',
          'watchingyou', 'strong', 'biohazard', 'healing', 'wash-hands', 'celebrate', 'peace', 'question', 'crown', 'fist-bump',
          'hand-shake', 'batman', 'hand', 'turkeydinner', 'frozen-hand', 'snowflake', 'yeti']
SPRAY_ASSET, SPRAY_GROUP, SPRAY_CD, SPRAY_SN = 69, 57, 45, 30
SPRAY_SIRA = itertools.count(1)        # sprey kimlikleri sunucuda tek (ortak haritada öteki oyuncuların spreyleri de görünür)
FIREWORK_LIMIT = 5                            # aynı anda kurulu kutu (fandom Fireworks: "You can only put down 5 fireworks"); bekleme
                                              # yok (istemcinin menüsünde bekleme grubu 0)
ROCKET_FLIGHT = _N['savas']['roket_ucus_sn']
ATTACK_MINE = 2                               # istemcinin AttackType'ı: MINE


def mod(name, **f):
    f['_'] = name
    return f


def attack_type(v):
    return mod('AttackTypeModule', attackTypeValue=v)


def stm(key):
    return legacy('0|A|STM|%s' % key)


# ------------------------------------------------------------ eşya sınıfları
def ammo_kind(loot):
    """Seçilen cephanenin türü: lazer, roket (özel roketler dahil), fircatici ya da None (tek atımlık eşyalar)."""
    if loot.startswith('ammunition_laser_'):
        return 'lazer'
    if loot.startswith('ammunition_rocketlauncher_'):
        return 'fircatici'
    if loot.startswith('ammunition_rocket_') or loot in ROCKETS:
        return 'roket'
    if loot.startswith('ammunition_slug_'):
        return 'slug'                                   # parçacık topu (parcacik.py)
    if loot.startswith('ammunition_spool_'):
        return 'gsp'                                    # Singularity Drive (parcacik.py)
    return None


def special(rocket):
    return bool(ROCKETS.get(rocket, {}).get('ozel'))


def item_cooldown(loot):
    """Kısayol öğesinin bekleme grubu ve süresi (sn, çarpanlardan önce) ya da None."""
    if loot.startswith(EMOTE_PREFIX):
        return O6['ifadeler']['bekleme_grubu'], O6['ifadeler']['bekleme_sn']
    if loot.startswith(SPRAY_PREFIX):
        return SPRAY_GROUP, SPRAY_CD
    if loot in MINES:
        m = MINES[loot]
        return m.get('bekleme_grubu', S['mayin']['bekleme_grubu']), m.get('bekleme_sn', S['mayin']['bekleme_sn'])
    if loot in ALIEN_CPUS:
        return ALIEN_CPUS[loot]['bekleme_grubu'], ALIEN_CPUS[loot]['bekleme_sn']
    if loot in FORMATIONS:
        return S['formasyon']['bekleme_grubu'], S['formasyon']['bekleme_sn']
    for key in ('akilli_bomba', 'aninda_kalkan', 'emp', 'hayalet'):
        if loot == S[key]['menu']:
            return S[key]['bekleme_grubu'], S[key]['bekleme_sn']
    r = ROCKETS.get(loot, {})
    if r.get('ozel'):
        return r['bekleme_grubu'], r['bekleme_sn']
    return None


def mine_based(loot):
    """Mayın ve mayından yapılanlar: Turbo Mine CPU'su (MIN-T01/02) beklemeyi kısaltır."""
    return loot in MINES or loot in (S['akilli_bomba']['menu'], S['aninda_kalkan']['menu'])


FIRCATICI_BEKLEME = 3.0           # roket fırlatıcısı atış beklemesi (sn)
FIRCATICI_ILK = (0.75, 1.9)       # salvodan ilk roketin hasarına (sn)
FIRCATICI_ARALIK = 2.2            # ardışık roketlerin hasarı arası (sn)


def timer_msg(group, ms, cooling=True):
    return ('MenuItemCooldownGroupTimerCommand', dict(timerState=mod('TimerStateModule', timerStateValue=2 if cooling else 0),
                                                      cooldownType=mod('CooldownTypeModule', typeValue=group), maxTime=ms,
                                                      time=ms if cooling else 0))


def ready_at(p, group):
    return (p.d.get(TIMERS, {}).get(str(group)) or [0, 0])[0]


def timer_fields(p, loot, now=None):
    """Girişte ve harita değişiminde kısayol öğesinin süren beklemesi (profil.patch_template) ya da None."""
    c = item_cooldown(loot)
    if not c:
        return None
    now = now or time.time()
    until, mx = p.d.get(TIMERS, {}).get(str(c[0])) or [0, 0]
    if until <= now:
        return None
    return dict(activatable=False, timerState=2, maxTime=mx, time=int((until - now) * 1000))


# ------------------------------------------------------------ takılı CPU'lar
def _first(p, key):
    return next((l for l, v in EK.props(p, key)), None)


def jump_loot(p):
    return next((l for l, v in EK.props(p, 'atlama') if 'hak' in EK.X[l]), None)


def has_ajp(p):
    return EK.has(p, 'gelismis_atlama')


def cloak_loot(p):
    return _first(p, 'gizlenme')


def toggled(p, item):
    key = TOGGLES.get(item)
    if not key or not EK.has(p, key):
        return False
    return p.d.get('cpu_acik', {}).get(item, TOGGLE_DEFAULT.get(key, True))


def home_map(p):
    return S['atlama_cpu']['ana_harita'].get(str(p.d['pilot'].get('factionId')), 1)


def jump_allowed(loot, map_id):
    """CPU'nun bu haritadan çalışıp çalışmadığı: JP-01 yalnız X-1..X-4; JP-02 ve AJP-01 5-X, BL ve kapı haritaları dışında.
    Cubikon Mezarlığı'ndan her atlama CPU'su çıkar (wiki: tek çıkış atlama CPU'su ya da ölüm); LoW'dan çalışmaz."""
    if int(map_id) == 42:
        return True
    if int(map_id) not in H.NAMES or int(map_id) in H.SPECIAL:
        return False                                  # Galaksi Kapısı haritaları, LoW
    cfg = EK.X.get(loot, {}).get('atlama', {})
    if 'haritalar' in cfg:
        return H.map_class(map_id) in cfg['haritalar']
    return not any(H.name(map_id).startswith(s) for s in cfg.get('yasak', []))


def gate_map(map_id):
    """Galaksi Kapısı haritası (üreticideki kapılar): Smart Bomb atılmaz (istemci ttip_inactive_smb_galaxy_gate "You can't drop
    Smartbombs in a Galaxy Gate!"). Mayının kapı kuralı çelişkili (N.O.V.A. Explosive Firepower A/B/G'de mayını güçlendiriyor)."""
    import kapi
    return int(map_id) in kapi.BY_MAP


def launchers(p):
    return [l for l in p.d.get('ekipman', {}).get('rocket', []) if l in LAUNCHERS]


def launcher_upgrade(p):
    """Fırlatıcının roket hasarı çarpanı: yükseltme (yukseltme.py; istemcinin oranı). Plus fırlatıcının roket_bonus'u bilgi: 20. seviye
    toplamı 1 + seviye x oran (resmî forum 161353: Neptune %28,5, Triskelion %47,5); birden çok fırlatıcıda en yükseği."""
    import yukseltme as YK
    eq, lv = p.d.get('ekipman', {}).get('rocket', []), p.d.get('ekipman_seviye', {}).get('rocket', [])
    return max([YK.factor(l, lv[i] if i < len(lv) else 0, YK.ROCKET) for i, l in enumerate(eq) if l in LAUNCHERS] or [1.0])


def capacity(p):
    return sum(LAUNCHERS[l]['kapasite'] for l in launchers(p))


def salvo(attacker, target, hit, cnt, tur):
    """Bir HellstormAttackCommand bütün salvoyu taşır. İstemci currentLoad > 1 olduğunda
    roketleri kendi aralığıyla eğri yörüngede uçurur (1.1.115 AttackRocketRun.Run).
    Her roketi currentLoad=1 olarak yollamak Hellstorm yörüngesini düzleştirir."""
    return ('HellstormAttackCommand', dict(attackerId=attacker, targetId=target, hit=hit, currentLoad=cnt,
                                          rocketType=mod('AmmunitionTypeModule', typeValue=tur)))


def salvo_time(dist, cnt):
    """Son roketin istemcideki varışı (sn): AttackRocketRun.Run roketi i*0,5/adet sonra
    başlatır; InitRocketCurve uçuşu max(1, mesafe/500) + (eğriyse 0,3) sn yapar."""
    return max(1.0, dist / 500.0) + (0.3 + (cnt - 1) * 0.5 / cnt if cnt > 1 else 0.0)


def launcher_type(p):
    return max((LAUNCHERS[l]['tur'] for l in launchers(p)), default=0)


def loaded(p):
    """Fırlatıcıdaki roketler: [cephane, adet]."""
    return p.d.get('fircatici_dolu') or [None, 0]


def mine_uses(p, cfg):
    """Smart Bomb / Insta-Shield: eldeki mayın ve Xenomit'le kaç kez."""
    return min(p.ammo(cfg['mayin']) // cfg['mayin_adet'], p.ore_count(XENOMIT) // cfg['xenomit'])


# ------------------------------------------------------------ kısayol çubuğu durumu (profil.menu_status)
def _line(key, reps=(), ktype=5):
    return {'_': 'MessageKeyListWildcardModule', 'baseKey': key, 'baseKeyType': {'_': 'ReplacementTypeModule', 'typeValue': ktype},
            'textStyle': 0, 'wildCardReplacements': [
                {'_': 'MessageWildcardReplacementModule', 'wildcard': w, 'replacement': str(r),
                 'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': t}} for w, r, t in reps]}


def _tips(st, lines):
    for k in ('toolTipSlotBar', 'toolTipItemBar'):
        st[k] = {'_': 'MessageKeyListWildcardCommand', 'commandList': json.loads(json.dumps(lines))}


def _explosive(st, loot, n):
    _tips(st, [_line('ttip_explosive', [('%TYPE%', loot, 1)]), _line('ttip_count', [('%COUNT%', n, 0)]), _line(loot, ktype=7)])


def menu_status(p, menu_id, st):
    """Bu modülün öğelerinin durumu (st: kayıttaki şablonun kopyası) ya da None (başka öğe)."""
    start_map = H.map_class(p.d['konum'].get('mapId', 0)) == 'X-1'
    if menu_id in PLAYER_MINES:
        n = p.ammo(menu_id)
        st.update(counterValue=n, counterStyle=4 if n > 0 else 1, visible=st.get('visible') or n > 0, available=n > 0 and not start_map,
                  activatable=n > 0 and not start_map)
        if not start_map:                      # kayıt (başlangıç haritası): ttip_inactive_mine_start_map
            _explosive(st, menu_id, n)
        return st
    if menu_id in (S['akilli_bomba']['menu'], S['aninda_kalkan']['menu']):
        smb = menu_id == S['akilli_bomba']['menu']
        cfg = S['akilli_bomba' if smb else 'aninda_kalkan']
        owned = EK.has(p, 'akilli_bomba' if smb else 'aninda_kalkan')
        n = mine_uses(p, cfg) if owned else 0
        in_gate = smb and gate_map(p.d['konum'].get('mapId', 0))
        blocked = smb and (start_map or in_gate)   # kayıt: ttip_inactive_smb_start_map
        st.update(visible=owned, counterValue=n, available=owned and n > 0 and not blocked, activatable=owned and n > 0 and not blocked)
        if owned and not blocked:
            _explosive(st, menu_id, n)
        elif owned and in_gate:
            _tips(st, [_line('ttip_inactive_smb_galaxy_gate')])
        return st
    if menu_id == S['atlama_cpu']['menu']:
        loot = jump_loot(p)
        if not loot:
            st.update(visible=False, available=False, activatable=False, counterValue=0)
            return st
        n = EK.uses(p, loot)
        here = p.d['konum'].get('mapId', 0)
        if here == home_map(p):
            lines, ok = [_line('ttip_inactive_jump_already_on_map')], False       # kayıt
        elif not jump_allowed(loot, here):
            lines, ok = [_line('ttip_inactive_jump_map_range_exceeded')], False
        else:
            lines = [_line('ttip_jump_cpu', [('%TYPE%', loot, 1)]), _line('ttip_cpu_jump_count', [('%COUNT%', n, 0)]),
                     _line('ttip_cpu_jump_desc')]
            ok = n > 0
        _tips(st, lines)
        st.update(visible=True, available=True, activatable=ok, counterValue=n, iconLootId=loot)
        return st
    if menu_id == S['gelismis_atlama']['menu']:
        owned = has_ajp(p)
        st.update(visible=owned, available=owned, activatable=owned)
        if owned:
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == S['gizlenme_cpu']['menu']:
        loot = cloak_loot(p)
        if not loot:
            st.update(visible=False, available=False, activatable=False, selected=False, counterValue=0)
            return st
        n = EK.uses(p, loot)
        on = bool(p.d.get('cpu_gizli'))
        _tips(st, [_line('ttip_cloak_cpu', [('%TYPE%', loot, 1)]), _line('ttip_cpu_cloak_count', [('%COUNT%', n, 0)])])
        st.update(visible=True, available=True, activatable=n > 0 and not on, selected=on, counterValue=n, iconLootId=loot)
        return st
    if menu_id == HM7:                             # envanterde/takılıysa ve hakkı varsa kullanılabilir (resmî oyun: satın alınca çubukta, takmaya gerek yok)
        owned = EK.owned(p, HM7)
        ok = owned and EK.uses(p, HM7) > 0
        st.update(visible=owned, available=ok, activatable=ok)
        if owned and not EK.unlimited(p, HM7):         # kalan satış hakkı: simgenin sol altında (resmî oyun)
            n = EK.uses(p, HM7)
            st.update(counterValue=n, counterStyle=4 if n > 0 else 1)
        if owned:
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == REPBOT_MENU:                     # onarım robotu: şablon hep REP-2; takılı robota göre, takılı değilse devre dışı
        loot = next((e for e in EK.equipped(p) if e in _E['onarim_robotlari']), None)
        if loot:
            _tips(st, [_line('ttip_robot_cpu', [('%TYPE%', loot, 1)])])
            st.update(visible=True, available=True, activatable=True, iconLootId=loot)
        else:
            _tips(st, [_line('ttip_cpu_not_equipped')])
            st.update(visible=True, available=False, activatable=False, selected=False)
        return st
    if menu_id in TOGGLES:
        key = TOGGLES[menu_id]
        loot = _first(p, key)
        st.update(visible=bool(loot), available=bool(loot), activatable=bool(loot), selected=toggled(p, menu_id))
        if loot:
            if menu_id == S['nisan_cpu']['menu']:
                _tips(st, [_line('ttip_aim_cpu_category'), _line(loot, ktype=7)])
                n = p.ore_count(XENOMIT) // S['nisan_cpu']['xenomit']      # kalan salvo (oyuncu bildirimi 2026-10-27: 0 görünüyordu)
                st.update(iconLootId=loot, counterValue=n, counterStyle=4 if n > 0 else 1)
            for tip in ('toolTipSlotBar', 'toolTipItemBar'):
                lines = (st.get(tip) or {}).get('commandList')
                if lines:
                    lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_cpu_not_equipped']
        return st
    if menu_id == S['fircatici']['menu']:
        lns = launchers(p)
        if not lns:
            return st                           # kayıttaki "fırlatıcı yok" durumu
        ammo, n = loaded(p)
        cap = capacity(p)
        sel = p.d.get('secili', {}).get('fircatici')
        # boş fırlatıcıda da yüklü roket sayısı (0): ttip_rocketlauncher_unloaded "Attention: No launcher installed" fırlatıcısız
        # hesabın metni (kayıt); takılı ama boş fırlatıcıda da gidiyordu (kullanıcı bildirimi 2026-10-25: "Hellstorm takılı ama
        # kurulmamış diyor")
        lines = [_line('ttip_rocketlauncher', [('%TYPE%', menu_id, 5)])]          # kayıt: öğenin adı (tür 5), fırlatıcınınki değil
        rocket = ammo if n else sel
        if rocket:
            lines.append(_line('ttip_rocketlauncher_loadcount', [('%COUNT%', n, 0), ('%TYPE%', rocket, 1)]))
        _tips(st, lines)
        # kayıt: simge ve nokta rengi yüklü (yoksa seçili) cephanenin; fırlatıcının adı ve varsayılan stil her roketi kırmızı gösteriyordu
        st.update(visible=True, available=n > 0, activatable=n > 0, counterValue=n, maxCounterValue=cap,
                  iconLootId=rocket or lns[0], counterStyle=LAUNCHER_COLOR.get(rocket, 1), selected=False)
        if sel is None:
            st['available'] = st['activatable'] = False
        return st
    return None


# ------------------------------------------------------------ gelişmiş atlama (AJP-01) listesi
def ajp_price(p, dest, here=None):
    """Kuponsuz AJP-01 atlamasının bedeli: kaynak ve hedef haritaya göre (forum 127075 tablosu, gerçek kayıtla aynı); kuponla 0."""
    c = S['gelismis_atlama']
    if p.resource(c['kupon']):
        return 0
    src = H.name(here if here is not None else p.d['konum'].get('mapId', 0))
    return c.get('fiyat_tablosu', {}).get(src, {}).get(H.name(dest), c['fiyat'])


def ajp_locked(p, m):
    """Hedefe seviye yetmiyor ya da düşman şirketin X-1'i (forum 127075: seviyeden bağımsız kilitli)."""
    fac = p.d['pilot'].get('factionId')
    homes = S['atlama_cpu']['ana_harita']
    return (m in homes.values() and m != homes.get(str(fac))) or p.d['pilot'].get('level', 1) < H.level_required(m, fac)


def random_maps(p, here):
    """Rastgele atlama hedefleri (4-5'in solucan deliği): AJP-01 listesinin seçilebilir haritaları, seviye ve düşman X-1 kilidi
    dışında."""
    return [m for m in sorted(H.NAMES) if m != here and m not in H.SPECIAL and not ajp_locked(p, m)
            and not any(H.name(m).startswith(s) for s in ('5-', 'BL-'))]


def jcpu_list(p):
    """0|A|JCPU|I|anahtar|harita;…;|… : -1 kilitli (seviye ya da düşman X-1), -2 uridyum yetmiyor, fiyat: seçilebilir."""
    here = p.d['konum'].get('mapId', 0)
    groups = {-1: [], -2: []}
    for m in sorted(H.NAMES):
        if m == here or m in H.SPECIAL or any(H.name(m).startswith(s) for s in ('5-', 'BL-')):
            continue
        price = ajp_price(p, m, here)
        if ajp_locked(p, m):
            groups[-1].append(m)
        elif price and p.d['pilot'].get('uridium', 0) < price:
            groups[-2].append(m)
        else:
            groups.setdefault(price, []).append(m)
    parts = ['0', 'A', 'JCPU', 'I']
    for k, maps in groups.items():
        if maps:
            parts += [str(k), ''.join('%d;' % m for m in maps)]
    return legacy('|'.join(parts))


def vouchers_msg(p):
    return legacy('0|A|JV|%d' % p.resource(S['gelismis_atlama']['kupon']))


# ------------------------------------------------------------ dünyadaki eşyalar
class Esyalar:
    def __init__(self, world):
        self.w, self.p = world, world.p
        self.mine_visuals = {}     # tür -> istemciye son gönderilen bitiş; profil okumaları etkileri erken ayıklayabilir
        self.mines = {}            # hash -> {loot, x, y, sahip, kurulma, bitis}
        self.fireworks = []        # kurulu havai fişek kutularının karmaları (ateşlenince istemci kaldırır)
        self.seq = 0
        self.jump = None           # CPU atlaması: {hedef, zaman, cpu, basla}
        self.ajp_target = None     # gelişmiş atlamada seçilen harita
        self.next_load = 0.0       # fırlatıcının bir sonraki dolumu
        self.launcher_cd = 0.0     # fırlatıcının ateş beklemesi (resmî kayıt: her atıştan sonra 3 sn, MenuItemTimerCommand)
        self.next_lure = 0.0
        self.waiting = {}          # grup -> bitiş: bitince READY bildirimi
        self.ghost_end = 0.0       # Ghostifier görünümünün bitişi
        self.serum_next = 0.0      # Serum CPU'su bir sonraki iyileştirmeye hazır
        self.next_dep = 0.0        # Smart Bomb / Insta-Shield sayacının denetimi (dependent_tick)
        self.aim_warned = False    # nişan CPU'sunun Xenomit uyarısı gitti (Xenomit gelince yeniden)
        self.born = time.time()    # bu harita yüklemesi (giriş, atlama, portal): atlama CPU'su 10 sn sonra (jump_cpu_failed_time)
        now = time.time()
        for g, (until, mx) in self.p.d.get(TIMERS, {}).items():
            if until > now:
                self.waiting[int(g)] = until

    # ------------------------------------------------------------ yardımcılar
    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def log(self, s):
        self.w.log(s)

    def status(self, *loots):
        out = [st for st in (self.p.menu_status(l) for l in loots) if st]
        for st in out:
            self.p.menu_mark(st)
        return [('MenuItemStatusCommand', st) for st in out]

    def dependent_tick(self, now):
        """Smart Bomb ve Insta-Shield'in sayacı ACM-01 ve Xenomit'e bağlı: bunlar her yerden değişebilir (mağaza, toplama,
        satış, takma/çıkarma). Durum değişince istemciye bildirilir (canlı test H20: mayın alınca sayaç 0'da kalıyordu)."""
        if now < self.next_dep:
            return
        self.next_dep = now + 1.0
        self.send(self.p.menu_changes([S['akilli_bomba']['menu'], S['aninda_kalkan']['menu'], S['nisan_cpu']['menu']]))

    def start_map(self):
        return H.map_class(self.w.map_id) == 'X-1'

    def ready(self, group, now):
        return now >= ready_at(self.p, group)

    def cooldown(self, loot, now):
        """Öğenin bekleme grubunu başlat -> zamanlayıcı mesajı. Turbo Mine CPU'su ve formasyon/tasarım çarpanları burada."""
        group, sec = item_cooldown(loot)
        if mine_based(loot):
            sec *= EK.mine_factor(self.p) * max(0.0, 1 + self.p.mods().get('mayin_bekleme', 0))
        sec *= AY.carpan('yetenek_bekleme', 'esya')                    # panel: yetenek ve eşya beklemeleri
        ms = int(sec * 1000)
        with self.p.lock:
            self.p.d.setdefault(TIMERS, {})[str(group)] = [now + sec, ms]
            self.p.dirty = True
        self.waiting[group] = now + sec
        return timer_msg(group, ms)

    def ore_msgs(self):
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.d['madenler']})]
        if self.w.ore_pack:
            msgs.append(self.w.ore_pack([XENOMIT]))
        return msgs

    def pay_mines(self, cfg):
        """Smart Bomb / Insta-Shield bedeli: 10 ACM-01 + 100 Xenomit -> mesajlar ya da None (yetmiyor)."""
        p = self.p
        if mine_uses(p, cfg) < 1:
            return None
        p.use_ammo(cfg['mayin'], cfg['mayin_adet'])
        p.remove_ores({XENOMIT: cfg['xenomit']})
        return self.w.ammo_msgs(cfg['mayin']) + self.ore_msgs()

    def tick(self, now):
        for g, until in list(self.waiting.items()):
            if now >= until:
                del self.waiting[g]
                mx = (self.p.d.get(TIMERS, {}).get(str(g)) or [0, 0])[1]
                self.send([timer_msg(g, mx, cooling=False)])
        self.mine_tick(now)
        self.dependent_tick(now)
        self.lure_tick(now)
        self.jump_tick(now)
        self.launcher_tick(now)
        if self.ghost_end and now >= self.ghost_end:
            self.ghost_end = 0.0
            self.send([self.ghost_msg(False)])

    # ------------------------------------------------------------ kısayol çubuğu (dunya.menu_action)
    def menu(self, item, now=None):
        """Tek atımlık ve aç-kapa öğeleri -> True: bu modülün öğesi (aç-kapa öğelerinde istemci actionType 0 gönderir)."""
        now = now or time.time()
        if item in PLAYER_MINES:
            self.place_mine(item, now)
        elif item in FIREWORKS:
            self.place_firework(item, now)
        elif item == IGNITE:
            self.ignite()
        elif item.startswith(SPRAY_PREFIX):
            self.spray(item, now)
        elif item == S['akilli_bomba']['menu']:
            self.smart_bomb(now)
        elif item == S['aninda_kalkan']['menu']:
            self.insta_shield(now)
        elif item == S['emp']['menu']:
            self.emp(now)
        elif item == S['atlama_cpu']['menu']:
            self.jump_cpu(now)
        elif item == S['gelismis_atlama']['menu']:
            it = self.p.window_item('spacemap')       # hedef uzay haritasının atlama panelinden seçilir: tık haritayı açar
            if it:
                self.send([('WindowItemCommand', dict(it, maximized=True))])
        elif item == S['gizlenme_cpu']['menu']:
            self.cloak(now)
        elif item in TOGGLES:
            self.toggle(item)
        elif item == S['fircatici']['menu']:
            self.launcher_fire(now)
        elif item in ALIEN_CPUS:
            self.alien_cpu(item, now)
        elif item == S['hayalet']['menu']:
            self.ghostify(now)
        else:
            return False
        return True

    def toggle(self, item):
        if not EK.has(self.p, TOGGLES[item]):
            return
        on = not toggled(self.p, item)
        with self.p.lock:
            self.p.d.setdefault('cpu_acik', {})[item] = on
            self.p.dirty = True
        self.send(self.status(item))
        self.log('   %s %s' % (item, 'açık' if on else 'kapalı'))

    # ------------------------------------------------------------ mayınlar
    def mine_worlds(self):
        """Aynı haritadaki oyuncular; görünürlük/gizlenme mayın tetiklemesini değiştirmez."""
        w = self.w
        return [w] + [other for other in (w.ortak.uyeler if w.ortak else [])
                      if other is not w and other.running]

    def mine_snapshot(self, now=None):
        """Yüklenen istemciye mevcut mayınlar; paylaşılmış oyuncu mayınları ve yalnız kendi uzaylı mayınları."""
        now = time.time() if now is None else now
        out, seen = [], set()
        for other in self.mine_worlds():
            if str(other.map_id) != str(self.w.map_id):
                continue
            for h, mine in other.items.mines.items():
                player = mine['sahip'] == other.hid
                if h in seen or mine['bitis'] <= now or (other is not self.w and not player):
                    continue
                seen.add(h)
                out.append(('AddMineCommand', dict(hash=h, x=int(mine['x']), y=int(mine['y']),
                                                   typeId=MINES[mine['loot']]['tip'],
                                                   maxSkill1=mine.get('maxSkill1', player and YT.maxed(other.p, '1')),
                                                   maxSkill5b=mine.get('maxSkill5b', player and YT.maxed(other.p, '5b')))))
        return out

    def place_mine(self, loot, now):
        w, p, M = self.w, self.p, S['mayin']
        cfg = MINES[loot]
        group = item_cooldown(loot)[0]
        if w.hero_dead or w.jumping or self.start_map() or p.ammo(loot) <= 0 or not self.ready(group, now):
            self.log('   mayın konmadı: %s' % loot)
            return
        x, y = w.hero_pos(now)
        if w.in_pvp_peace(x, y):
            self.log('   mayın konmadı: güvenli bölge')
            return
        mines = [m for other in self.mine_worlds() for m in other.items.mines.values() if m['bitis'] > now]
        if any(m['loot'] == loot and math.hypot(m['x'] - x, m['y'] - y) < M['istif'] for m in mines):
            self.send([stm('msg_no_mine_stacking')])
            return
        if len(mines) >= M['harita_siniri']:
            self.send([stm('msg_map_too_many_mine')])
            return
        p.use_ammo(loot, 1)
        self.seq += 1
        h = 'M%d_%d' % (w.hid, self.seq)
        self.mines[h] = dict(loot=loot, x=x, y=y, sahip=w.hid, kurulma=now + cfg.get('kurulma_sn', M['kurulma_sn']),   # SLM-01 1 sn
                             bitis=now + cfg.get('omur_sn', M['omur_sn']),
                             hasar=max(0.0, 1 + p.mods().get('mayin', 0) + p.mods().get('mayin_lance', 0)),     # Lance yalnız mayınlara
                             yaricap=M['patlama'] * max(0.0, 1 + p.mods().get('mayin_yaricap', 0)),
                             maxSkill1=YT.maxed(p, '1'), maxSkill5b=YT.maxed(p, '5b'))
        p.ach('shot', silah='MINE')
        # mayının görseli: Explosives (1) ve Detonation II (5b) son seviyesinde (resmî SSS: "mine visuals")
        self.send(w.ammo_msgs(loot) + [('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=cfg['tip'],
                                                               maxSkill1=self.mines[h]['maxSkill1'], maxSkill5b=self.mines[h]['maxSkill5b'])),
                                       self.cooldown(loot, now)])
        self.log('   mayın: %s (%d, %d)' % (loot, x, y))

    def place_firework(self, loot, now):
        """Havai fişek kutusu geminin yerine (AddFireworkBoxCommand: typeId fireworkDescriptor kimliği; colourCode'un her basamağı
        bir aşamanın rengi 1-3; eventModifier boş -> istemcinin 'standart' sınıfı). Ateşleme öğesi hepsini birden ateşler."""
        w, p = self.w, self.p
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or len(self.fireworks) >= FIREWORK_LIMIT:
            self.log('   havai fişek konmadı: %s' % loot)
            return
        x, y = w.hero_pos(now)
        p.use_ammo(loot, 1)
        self.seq += 1
        h = 'F%d_%d' % (w.hid, self.seq)
        self.fireworks.append(h)
        colour = int(''.join(random.choice('123') for _ in range(3)))
        self.send(w.ammo_msgs(loot) + [('AddFireworkBoxCommand', dict(hash=h, x=int(x), y=int(y), colourCode=colour,
                                                                       typeId=FIREWORKS[loot], eventModifier=''))])
        self.log('   havai fişek: %s (%d, %d)' % (loot, x, y))

    def ignite(self):
        """Kurulu kutuların hepsi (0|n|FWG|karma|…: istemci 3. parçadan itibaren her kutuyu ateşleyip kaldırır)."""
        if not self.fireworks:
            return
        hs, self.fireworks = self.fireworks, []
        self.send([legacy('0|n|FWG|%s' % '|'.join(hs))])
        self.log('   havai fişek ateşlendi: %d' % len(hs))

    def spray(self, loot, now):
        """Sprey geminin yerine (istemci desenin resmini yere çizer), SPRAY_SN sonra kalkar."""
        w, p = self.w, self.p
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(SPRAY_GROUP, now):
            return
        p.use_ammo(loot, 1)
        x, y = w.hero_pos(now)
        uid, kind = 970000 + next(SPRAY_SIRA), {'_': 'AssetTypeModule', 'typeValue': SPRAY_ASSET}
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now), (
            'AssetCreateCommand', dict(designId=SPRAYS.index(loot[len(SPRAY_PREFIX):]), clanId=0, showBubble=False, userName='',
                                       assetId=uid, expansionStage=0, modifier=[], type=kind, detectedByWarnRadar=False,
                                       invisible=False, posX=int(x) + SPRAY_KAYMA[0], posY=int(y) + SPRAY_KAYMA[1],
                                       clanRelation={'_': 'ClanRelationModule', 'type': 0},
                                       clanTag='', factionId=0, visibleOnWarnRadar=False))])
        w.later(SPRAY_SN, lambda: self.send([('AssetRemoveCommand', {'assetType': kind, 'uid': uid})]))
        self.log('   sprey: %s (%d, %d)' % (loot, x, y))

    def alien_mine(self, loot, x, y, owner, now):
        """Uzaylının mayını (Curcubitor'un Trick'i, Agatus): oyuncu yakınındaysa kurulunca patlar (mine_tick)."""
        M = S['mayin']
        self.seq += 1
        h = 'U%d_%d' % (owner, self.seq)
        self.mines[h] = dict(loot=loot, x=x, y=y, sahip=owner, kurulma=now + MINES[loot].get('kurulma_sn', M['kurulma_sn']),
                             bitis=now + MINES[loot].get('omur_sn', M['omur_sn']))
        self.send([('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=MINES[loot]['tip'], maxSkill1=False, maxSkill5b=False))])

    def field_mine(self, x, y, now):
        """Haritanın mayın alanındaki mayın (5-1, 5-3; harita_duzeni.json): kurulu, süresiz, sahipsiz (uzaylı mayını gibi oyuncuyla
        patlar; mine_tick). Patlayınca yenisi alanında (explode). -> AddMineCommand"""
        loot = HD.MINE['tur']
        self.seq += 1
        h = 'A%d' % self.seq
        self.mines[h] = dict(loot=loot, x=x, y=y, sahip=0, kurulma=now, bitis=float('inf'), alan=True)
        return ('AddMineCommand', dict(hash=h, x=int(x), y=int(y), typeId=MINES[loot]['tip'], maxSkill1=False, maxSkill5b=False))

    def mine_msgs(self):
        """Harita yeniden yüklenince (yeniden doğma) duran mayınlar yeniden."""
        return [('AddMineCommand', dict(hash=h, x=int(m['x']), y=int(m['y']), typeId=MINES[m['loot']]['tip'], maxSkill1=False,
                                        maxSkill5b=False)) for h, m in self.mines.items()]

    def serum_cure(self):
        """Serum CPU (ANTI-Z1 1 doz, XL 10 doz; istemci: "automatically cure you of any infections"): takılıysa ve dozu varsa bulaşan
        enfeksiyonu kendiliğinden iyileştirir, bir doz harcanır; sonraki iyileştirme 60 sn sonra (wiki bekleme). -> iyileştiyse True"""
        now = time.time()
        loot = next((l for l, _ in EK.props(self.p, 'serum') if EK.uses(self.p, l) > 0), None)
        if not loot or now < self.serum_next:
            return False
        self.serum_next = now + EK.X[loot]['bekleme_sn']
        self.log('   Serum CPU enfeksiyonu iyileştirdi (%s, kalan %d)' % (loot, EK.use(self.p, loot)))
        return True

    def mine_effect_msgs(self, now=None, replay=False, remember=True):
        """Mayının gemideki kalıcı görseli: PLAGUE (57), SL-M01'in slow-effect'i (uzaylıların yavaşlatan atışında da: Saboteur, Uber
        Protegit …); patlama bunları kendiliğinden başlatmaz."""
        now = time.time() if now is None else now
        w, msgs = self.w, []
        for kind in ('enfeksiyon', 'yavas'):
            effects = [] if w.hero_dead else w.hero_etki.get(kind, now)
            effects = [e for e in effects if kind == 'enfeksiyon' or e.get('kaynak') in MINES]
            if kind == 'yavas' and not w.hero_dead:
                effects += [e for e in w.hero_etki.get('yavas', now) + w.hero_etki.get('hiz_siniri', now)
                            if str(e.get('kaynak')).startswith('yavaslatma_')]
            until = max((e['bitis'] for e in effects), default=0)
            previous = self.mine_visuals.get(kind, 0)
            def message(on):
                if kind == 'enfeksiyon':
                    return ('VisualModifierCommand', dict(userId=w.hid, modifier=57, attribute=0,
                                                           additionalAttribute=str(max(0, math.ceil(until - now))) if on else '',
                                                           count=0, activated=on))
                return legacy('0|n|fx|%s|SABOTEUR_DEBUFF|%d' % ('start' if on else 'end', w.hid))
            if previous and not replay and previous != until:
                msgs.append(message(False))     # yenilenen enfeksiyonun eski parçacığını/timer'ını kaldır
            if until and (replay or previous != until):
                msgs.append(message(True))
            if remember:                       # başka istemcinin yeni gemi görünümü yerel bitiş takibini değiştirmez
                if until:
                    self.mine_visuals[kind] = until
                else:
                    self.mine_visuals.pop(kind, None)
        return msgs

    def mine_tick(self, now):
        if not self.mines:
            return
        w, M = self.w, S['mayin']
        hx, hy = w.hero_pos(now)
        for h, m in list(self.mines.items()):
            if h not in self.mines:
                continue
            if now >= m['bitis']:
                del self.mines[h]
                self.send([('RemoveMineCommand', {'hash': h})])
                continue
            if now < m['kurulma'] or 'yem' in MINES[m['loot']]:
                continue
            players = self.mine_worlds() if m['sahip'] == w.hid else [w]
            hit = any(not other.hero_dead and not other.jumping
                      and (other.hid != m['sahip'] or (M.get('kendine_hasar') and AY.get('kendi_mayin')))
                      and math.hypot(*(a - b for a, b in zip(other.hero_pos(now), (m['x'], m['y'])))) <= M['tetik']
                      and not other.in_pvp_peace(*other.hero_pos(now))
                      and not other.tech.mine_protected(now) for other in players)
            if not hit and m['sahip'] == w.hid and M.get('npc_uyarlama', False):
                hit = any(n.alive and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (m['x'], m['y'])))) <= M['tetik']
                          for n in w.npcs.values())       # yerel PvE uyarlaması; resmî oyunda NPC tetiklemez
            if hit:
                self.explode(h, now)

    def explode(self, h, now):
        m = self.mines.pop(h, None)
        if m is None:
            return
        self.send([legacy('0|n|MIN|%s' % h)])
        self.log('   mayın patladı: %s' % m['loot'])
        self.blast(m['x'], m['y'], m.get('yaricap', S['mayin']['patlama']), MINES[m['loot']], m['sahip'], now, m['loot'],
                   factor=m.get('hasar'), self_hit=S['mayin'].get('kendine_hasar', False) and AY.get('kendi_mayin'))       # panel: kendi mayının
        if m.get('alan'):                     # mayın alanı: yenisi aynı alanda biraz sonra
            rect = HD.mine_field_of(self.w.map_id, m['x'], m['y'])

            def again():
                p = rect and HD.free_spot(self.w.map_id, rect, pad=100)
                if p:
                    self.send([self.field_mine(p[0], p[1], time.time())])
            self.w.later(random.uniform(*HD.MINE['yeniden_sn']), again)

    def blast(self, x, y, radius, cfg, owner, now, source, self_hit=False, factor=None):
        """Patlama: yarıçaptaki uzaylılara (sahibi oyuncuysa) ve oyuncuya (uzaylının mayınıysa ya da self_hit) mayın etkisi."""
        w = self.w
        m = self.p.mods()
        f = factor if factor is not None else max(0.0, 1 + m.get('mayin', 0) + m.get('mayin_lance', 0)) if owner == w.hid else 1.0
        if source in MINES:                   # resmî SSS: mayınlar gemileri etkiler; uzaylıları değil
            if 'yem' in cfg:
                return
            if owner == w.hid and S['mayin'].get('npc_uyarlama', False):
                for n in list(w.npcs.values()):
                    if n.alive and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (x, y)))) <= radius:
                        self.mine_npc(n, cfg, f, now, source)
            for other in self.mine_worlds() if owner == w.hid else [w]:
                if other.hero_dead or other.jumping or (other.hid == owner and not self_hit):
                    continue
                hx, hy = other.hero_pos(now)
                if not other.in_pvp_peace(hx, hy) and math.hypot(hx - x, hy - y) <= radius:
                    other.items.mine_hero(cfg, f, owner, now, source)
            return
        f = max(0.0, 1 + m.get('mayin', 0)) if owner == w.hid else 1.0      # Turtle -%7,5, Detonation I/II; Lance değil (forum 127433)
        if owner == w.hid:
            radius *= 1 + m.get('mayin_yaricap', 0)                         # Explosives
            for n in list(w.npcs.values()):
                nx, ny = n.mover.pos(now)
                if n.alive and math.hypot(nx - x, ny - y) <= radius:
                    self.mine_npc(n, cfg, f, now, source)
        if owner != w.hid or self_hit:
            hx, hy = w.hero_pos(now)
            if math.hypot(hx - x, hy - y) <= radius:
                self.mine_hero(cfg, f, owner, now, source)

    def mine_npc(self, n, cfg, f, now, source):
        w = self.w
        sh = min(n.shield, n.d['kalkan'] * cfg.get('kalkan', 0) * f)       # SAB-M01 %50 x (Lance + Detonation) en çok %100 (wiki)
        hp = n.d['hp'] * cfg.get('can', 0) * f
        if cfg.get('hasar_turu') == 'standart':
            sh = min(n.shield, int(hp * n.d.get('kalkan_emme', _N['savas']['npc_kalkan_emme'])))
            hp = min(max(0, n.hp - 1), hp - sh)
        if sh or hp:
            w.hit_npc(n.id, 0, ATTACK_MINE, split=(int(sh), int(hp)))
        if not n.alive:
            return
        if 'yavas' in cfg:
            w.npc_effect(n, 'yavas', cfg['yavas'][1], cfg['yavas'][0], source=source)
        enf = cfg.get('enfeksiyon')
        if enf:
            w.npc_effect(n, 'yavas', enf['sn'], enf['yavas'], source=source)
            w.npc_effect(n, 'hasar_bonus', enf['sn'], enf['hasar_bonus'], source=source)
        if not sh and not hp and not n.engaged and ('yavas' in cfg or enf):
            n.engaged = True                   # yavaşlatılan uzaylı saldırgana döner

    def mine_hero(self, cfg, f, owner, now, source):
        w, p = self.w, self.p
        g = p.d['gemi']
        if w.hero_dead:
            return
        npc_owner = w.npcs.get(owner)
        yer = 'dalga' if getattr(npc_owner, 'hunt', False) else 'harita'
        k = AY.carpan('npc_hasar', yer) if npc_owner else 1.0
        shield, hull = g.get('shield', 0), g.get('hitPoints', 0)
        sh = min(shield, int(g.get('shieldMax', 0) * cfg.get('kalkan', 0) * f * k))
        hp = int(g.get('hitMax', 0) * cfg.get('can', 0) * f * k)
        if cfg.get('hasar_turu') == 'standart':
            sh = min(shield, int(hp * p.d.get('kalkan_emme', 0.8)))
            hp = min(max(0, hull - 1), hp - sh)          # ACM/IM tek başına gemi yok etmez
        elif cfg.get('hasar_turu') == 'dogrudan':
            base = p.ship_row().get('hp', g.get('hitMax', 0)) + YT.mods(p).get('can_mutlak', 0)
            hp = int(base * cfg.get('can', 0) * f * k)   # DD-M01: temel gövde + Pilot Bio
        if w.hero_etki.invulnerable(now) or w.invulnerable:
            sh = hp = 0
        if cfg.get('emp'):
            w.abilities.reveal()
            self.reveal('msg_uncloaked')
        if 'yavas' in cfg:
            w.hero_effect('yavas', cfg['yavas'][1], cfg['yavas'][0], source=source)
        infection = cfg.get('enfeksiyon')
        if not sh and not hp:
            if infection:
                w.hero_effect('enfeksiyon', infection['sn'], source=source)
            return
        w.last_combat = w.last_hurt = now
        w.stop_repair()
        new = hull - hp
        if npc_owner:
            new = max(new, w.tech.hp_floor(now))
        hp = hull - max(0, new)
        p.set_hull(hp=max(0, new), shield=shield - sh)
        msgs = [('AttackHitCommand', dict(attackType=attack_type(ATTACK_MINE), attackerId=owner, victimId=w.hid,
                                          victimHitpoints=int(g['hitPoints']), victimShield=int(g.get('shield', 0)),
                                          victimNanoHull=int(g.get('nanoHull', 0)), damage=int(sh + hp), skilled=False, strike=False,
                                          cannonType=0))]
        self.log('   mayın oyuncuyu vurdu: %d' % (sh + hp))
        if g['hitPoints'] <= 0:
            w.hero_death(msgs, npc_owner, note='killed_by_mine')
        self.send(msgs)
        if infection and not w.hero_dead:
            w.hero_effect('enfeksiyon', infection['sn'], source=source)  # önce ACM hasarı, ardından gövde kapasitesi değişimi

    def lure_tick(self, now):
        """AGL-M01: Agatus ve Spinel'ler yeme gelir (saldırıda değilken)."""
        if now < self.next_lure:
            return
        self.next_lure = now + 2.0
        baits = [m for other in self.mine_worlds() for m in other.items.mines.values()
                 if 'yem' in MINES[m['loot']] and m['kurulma'] <= now < m['bitis']]
        if not baits:
            return
        w = self.w
        for n in w.npcs.values():
            if not n.alive or n.engaged or n.d['hiz'] <= 0:
                continue
            nx, ny = n.mover.pos(now)
            names = [b for b in baits if any(k in n.d['ad'] for k in MINES[b['loot']]['yem'])
                     and math.hypot(b['x'] - nx, b['y'] - ny) <= MINES[b['loot']]['yaricap']]
            if not names:
                continue
            nx, ny = n.mover.pos(now)
            b = min(names, key=lambda b: math.hypot(b['x'] - nx, b['y'] - ny))
            if math.hypot(b['x'] - nx, b['y'] - ny) < 100:
                continue
            ms = n.mover.go(b['x'], b['y'], n.d['hiz'] * n.etki.speed_factor(now), now)
            n.next_think = now + ms / 1000.0
            if n.id in w.visible:
                self.send([('MoveCommand', dict(userId=n.id, x=int(b['x']), y=int(b['y']), timeToTarget=ms))])

    # ------------------------------------------------------------ Smart Bomb, Insta-Shield, EMP
    def smart_bomb(self, now):
        w, c = self.w, S['akilli_bomba']
        if (not EK.has(self.p, 'akilli_bomba') or self.start_map() or gate_map(w.map_id) or w.hero_dead or w.jumping
                or not self.ready(c['bekleme_grubu'], now)):
            return
        paid = self.pay_mines(c)
        if paid is None:
            self.log('   Smart Bomb: mayın ya da Xenomit yetmiyor')
            return
        x, y = w.hero_pos(now)
        self.send([legacy('0|n|SMB|%d' % w.hid)])
        self.blast(x, y, c['yaricap'], c, w.hid, now, c['menu'], self_hit=False)      # kendi gemisine zarar vermez (wiki)
        self.send(paid + [self.cooldown(c['menu'], now)] + self.status(c['menu'], S['aninda_kalkan']['menu']))
        self.p.ach('shot', silah='MINE')
        self.log('   Smart Bomb patladı')

    def insta_shield(self, now):
        w, c = self.w, S['aninda_kalkan']
        if not EK.has(self.p, 'aninda_kalkan') or w.hero_dead or not self.ready(c['bekleme_grubu'], now):
            return
        paid = self.pay_mines(c)
        if paid is None:
            self.log('   Insta-Shield: mayın ya da Xenomit yetmiyor')
            return
        w.hero_effect('dokunulmaz', c['sure_sn'], source=c['menu'])
        self.send([legacy('0|n|ISH|%d' % w.hid)] + paid + [self.cooldown(c['menu'], now)]
                  + self.status(c['menu'], S['akilli_bomba']['menu']))
        self.log('   Insta-Shield: %d sn hasar yok' % c['sure_sn'])

    def emp(self, now):
        w, p, c = self.w, self.p, S['emp']
        loot = c['menu']
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(c['bekleme_grubu'], now):
            return
        hx, hy = w.hero_pos(now)
        if w.in_pvp_peace(hx, hy):          # istasyon ve portal çevresinde kullanılmaz, mayın gibi (oyuncu bildirimi 2026-10-28, gerçek oyun)
            self.log('   EMP kullanılmadı: güvenli bölge')
            return
        p.use_ammo(loot, 1)
        msgs = [legacy('0|n|EMP|%d' % w.hid)]
        reset = 0
        for n in w.npcs.values():
            # oyuncuyu hedeflemiş her uzaylı kilidini kaybeder, mesafeden bağımsız (oyuncu bildirimi 2026-10-28: uzaktan ateş edenler
            # etkilenmiyordu); yarıçap öteki oyuncuların P.E.T.'leri için (aşağıda)
            if n.alive and n.engaged and w.bizim(n):
                n.engaged = False                                   # hedefi sıfırlanır
                n.next_shot = max(getattr(n, 'next_shot', 0), now + c['saskinlik_sn'])
                n.blocked = max(getattr(n, 'blocked', 0), now + c['saskinlik_sn'])     # saldırgan tür hemen yeniden kilitlenmesin
                reset += 1
        if w.hero_etki.get('yavas') or w.hero_etki.get('hiz_siniri'):
            w.hero_etki.remove('yavas')                             # EMP yavaşlatmaları kaldırır (aliens.md: Slowdown Orb)
            w.hero_etki.remove('hiz_siniri')
            msgs += self.mine_effect_msgs(now) + w.effect_stats_msgs(now)
        for other in self.mine_worlds()[1:]:          # forum 127074: EMP menzilindeki (öteki oyuncunun) P.E.T. etkin dışı kalır
            pet = getattr(other, 'pet', None)
            if pet and pet.active and math.hypot(*(a - b for a, b in zip(pet.pos(now), (hx, hy)))) <= c['yaricap']:
                pet.disrupt(now)
        self.send(msgs + w.ammo_msgs(loot) + [self.cooldown(loot, now)])
        self.log('   EMP: %d uzaylının hedefi sıfırlandı' % reset)

    # ------------------------------------------------------------ Chaos Alien CPU'ları, Cubi Portal, Ghostifier
    def alien_cpu(self, loot, now):
        """Haritası uygunsa (X-3..X-7 sınıfı ya da savaş haritası) yakına kademesinden rastgele bir uzaylı: oyuncunun peşine düşer,
        yeniden doğmaz. Haritada CPU uzaylısı yaşarken ve güvenli bölgede kullanılmaz (istemcinin metinleri)."""
        w, p, c = self.w, self.p, ALIEN_CPUS[loot]
        if w.hero_dead or w.jumping or p.ammo(loot) <= 0 or not self.ready(c['bekleme_grubu'], now):
            return
        if H.map_class(w.map_id) not in c['haritalar'] and not H.name(w.map_id).startswith('4-'):
            self.log('   %s bu haritada kullanılamaz (%s)' % (loot, H.name(w.map_id)))
            return
        hx, hy = w.hero_pos(now)
        if w.in_peace(hx, hy):
            self.send([stm('msg_aliencpu_dmz')])
            return
        if any(n.alive and getattr(n, 'cpu', False) for n in w.npcs.values()):
            self.send([stm('msg_aliencpu_npc_already_exists')])
            return
        if len(w.npcs) > c.get('npc_siniri', 10 ** 9):                # Bountiful: haritada 250'den çok uzaylı varsa kullanılamaz
            self.send([stm('msg_aliencpu_npc_limit_reached')])
            return
        if c.get('etkinlik') and not TKV.is_active(c['etkinlik']):    # Bountiful yalnız Gauntlet of Plutus sürerken (bitince silinir)
            self.log('   %s: %s etkinliği sürmüyor' % (loot, c['etkinlik']))
            return
        p.use_ammo(loot, 1)
        a = random.uniform(0, 2 * math.pi)
        x = min(max(600, hx + math.cos(a) * 800), w.map_w - 600)
        y = min(max(600, hy + math.sin(a) * 800), w.map_h - 600)
        n = w.spawn_npc_at(random.choice(c['turler']), x, y)
        n.summoned = n.hunt = n.cpu = True
        n.saturn = bool(c.get('oyuncu_sayilir'))          # Saturn Verici: PvP görevlerinde düşman oyuncu (forum 127576)
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now)])
        self.log('   %s: %s doğdu' % (loot, n.d['ad']))

    def ghost_msg(self, on):
        return ('VisualModifierCommand', dict(userId=self.w.hid, modifier=S['hayalet']['gorsel'], attribute=0, additionalAttribute='',
                                              count=0, activated=on))

    def ghostify(self, now):
        """Ghostifier: gemi bir dakika hayalet görünür (istemcinin VisualModifier GHOST_EFFECT'i)."""
        w, p, c = self.w, self.p, S['hayalet']
        loot = c['menu']
        if w.hero_dead or p.ammo(loot) <= 0 or not self.ready(c['bekleme_grubu'], now):
            return
        p.use_ammo(loot, 1)
        self.ghost_end = now + c['sure_sn']
        self.send(w.ammo_msgs(loot) + [self.cooldown(loot, now), self.ghost_msg(True)])
        self.log('   Ghostifier: %d sn' % c['sure_sn'])

    # ------------------------------------------------------------ gizlenme CPU'su
    def cloaked(self):
        return bool(self.p.d.get('cpu_gizli'))

    def cloak(self, now):
        w, p = self.w, self.p
        loot = cloak_loot(p)
        if not loot or self.cloaked() or w.hero_dead:
            return
        if EK.uses(p, loot) <= 0:
            self.send([stm('cloak_cpu_failed_generic')])
            return
        left = EK.use(p, loot)
        p.ach('spend', loot=loot, adet=1)       # Pass görevleri: "Cloak CPU'yu etkinleştir" (savas_bileti.py)
        w.abilities.reveal()                   # wiki: etkin Ultimate Cloaking biter, CPU'nun gizlenmesi devralır
        with p.lock:
            p.d['cpu_gizli'] = True
            p.dirty = True
        self.send([legacy('0|n|INV|%d|1' % w.hid)] + self.status(S['gizlenme_cpu']['menu']))
        self.log('   gizlendi (%s, kalan %d)' % (loot, left))

    def reveal(self, key='lost_invisible_attack'):
        """Saldırınca gizlenme biter."""
        if not self.cloaked():
            return
        with self.p.lock:
            self.p.d['cpu_gizli'] = False
            self.p.dirty = True
        self.send([legacy('0|n|INV|%d|0' % self.w.hid), stm(key)] + self.status(S['gizlenme_cpu']['menu']))
        self.log('   gizlenme bitti')

    # ------------------------------------------------------------ nişan CPU'su, otomatik roket ve fırlatıcı
    def aim(self, chance):
        """AIM-01/02: ıska oranı -%25/-%50; atış başına 10 Xenomit (yoksa etkisiz)."""
        p = self.p
        item = S['nisan_cpu']['menu']
        r = max((v for l, v in EK.props(p, 'nisan')), default=0)
        if not r or not toggled(p, item):
            return chance
        if p.ore_count(XENOMIT) < S['nisan_cpu']['xenomit']:
            if not self.aim_warned:              # "Warning: The Targeting Guidance CPU isn't working. You don't have enough Xenomit."
                self.aim_warned = True
                self.send([stm('aim_cpu_failed_xenomit')])
            return chance
        self.aim_warned = False
        p.remove_ores({XENOMIT: S['nisan_cpu']['xenomit']})
        self.send(self.ore_msgs())
        return 1 - (1 - chance) * (1 - r)

    def auto_weapons(self, n, now):
        """Lazer saldırısında: AROL-X seçili roketi, RL-LB1 dolu fırlatıcıyı kendiliğinden ateşler."""
        w = self.w
        uid = getattr(n, 'id', n)
        if toggled(self.p, 'equipment_extra_cpu_arol-x'):
            r = self.p.d['secili'].get('roket')
            if r and (self.ready(item_cooldown(r)[0], now) if special(r) else now >= w.rocket_ready):
                w.rocket({'targetId': uid})
        if toggled(self.p, 'equipment_extra_cpu_rllb-x') and capacity(self.p) and loaded(self.p)[1] >= capacity(self.p):
            self.launcher_fire(now, n)

    # ------------------------------------------------------------ roket fırlatıcısı
    def launcher_tick(self, now):
        w, p = self.w, self.p
        if self.launcher_cd and now >= self.launcher_cd:        # bekleme bitti: sayaç hazır
            self.launcher_cd = 0.0
            self.send([('MenuItemTimerCommand', dict(activatable=True, timerState=mod('TimerStateModule', timerStateValue=0), maxTime=0,
                                                     time=0, menuItemId=S['fircatici']['menu']))])
        cap = capacity(p)
        if not cap or w.hero_dead:
            return
        sel = p.d['secili'].get('fircatici')
        ammo, n = loaded(p)
        msgs = []
        if n and ammo != sel:                  # cephane değişti: yüklüler geri
            if not AY.get('sonsuz_cephane'):   # sonsuz cephanede yüklerken harcanmadı: iade bedava roket olurdu
                p.add_ammo(ammo, n)
            msgs += w.ammo_msgs(ammo)
            ammo, n = sel, 0
            self.store(ammo, 0)
        if not sel or n >= cap:
            self.send(msgs)
            return
        rapid = bool(w.abilities.flags.get('roket'))            # Tartarus Rapid Fire: fırlatıcı hemen dolar
        if not rapid and now < self.next_load:
            self.send(msgs)
            return
        add = min(cap - n, p.ammo(sel)) if rapid else min(1, p.ammo(sel))
        if add <= 0:
            self.send(msgs)
            return
        p.use_ammo(sel, add)
        n += add
        self.store(sel, n)
        self.next_load = now + (S['fircatici']['dolum_sn'] * max(0.1, 1 + p.mods().get('fircatici_bekleme', 0))   # Star +%33 …
                                * AY.carpan('roket_bekleme'))                                               # panel
        self.send(msgs + w.ammo_msgs(sel) + self.status(S['fircatici']['menu'])
                  + [legacy('0|RL|S|%d|%d|%d' % (launcher_type(p), LAUNCHER_AMMO.get(sel, {}).get('kimlik', 7), n))])

    def store(self, ammo, n):
        with self.p.lock:
            self.p.d['fircatici_dolu'] = [ammo, n]
            self.p.dirty = True

    def launcher_fire(self, now, n=None):
        w, p = self.w, self.p
        if now < self.launcher_cd:
            return
        if n is None and not capacity(p):              # kısayoldan, fırlatıcı takılı değil
            return self.send([stm('hellstorm_launcher_not_equipped')])
        uid = getattr(n, 'id', n) if n is not None else w.target
        n = w.npcs.get(uid)
        asset = w.asset_at(uid) if not n else None
        ammo, cnt = loaded(p)
        if (not asset and (not n or not n.alive)) or cnt <= 0 or w.hero_dead or w.jumping or ammo not in LAUNCHER_AMMO:
            return
        if asset:
            denied = w.asset_targets.asset_attackable(uid)
            if denied:
                return self.send(denied)
        hx, hy = w.hero_pos(now)
        nx, ny = asset if asset else n.mover.pos(now)
        rng = S['fircatici']['menzil']
        if math.hypot(nx - hx, ny - hy) > rng:
            self.send([('AttackRangeExceededCommand', {'uid': uid, 'maxRange': rng, 'type': 0})])
            return
        w.end_invuln(force=True)
        w.abilities.reveal()
        self.reveal()
        w.last_combat = now
        w.stop_repair()
        cfg = LAUNCHER_AMMO[ammo]
        hit = random.random() < cfg.get('isabet', 1.0)
        self.store(ammo, 0)
        if random.random() < p.ship_row().get('ek_roket_sans', 0):
            cnt += 1                                    # Tartarus Plus: "1 in 5 chance of firing an extra rocket" (cephanesiz)
        self.next_load = now + (S['fircatici']['dolum_sn'] * max(0.1, 1 + p.mods().get('fircatici_bekleme', 0))   # Star +%33 …
                                * AY.carpan('roket_bekleme'))                                               # panel
        p.ach('shot', silah='ROCKET_LAUNCHER')
        self.launcher_cd = now + FIRCATICI_BEKLEME            # kayıt (2026-10-27, 117 atış): atıştan sonra tam 3,0 sn sayaç
        menu = S['fircatici']['menu']
        self.send([('MenuItemTimerCommand', dict(activatable=False, timerState=mod('TimerStateModule', timerStateValue=2),
                                                 maxTime=int(FIRCATICI_BEKLEME * 1000), time=int(FIRCATICI_BEKLEME * 1000), menuItemId=menu))])
        first = salvo(w.hid, uid, hit, cnt, cfg['tur'])
        self.send([first, legacy('0|RL|S|%d|%d|0' % (launcher_type(p), cfg['kimlik']))] + self.status(S['fircatici']['menu']))
        self.log('   fırlatıcı: %d x %s%s' % (cnt, ammo, '' if hit else ' (ıska)'))
        if not hit:
            return
        mods = p.mods()
        dmg = sum(cfg.get('hasar', 0) * random.uniform(0.85, 1.0) for _ in range(cnt))
        fusion = YT.mods(p).get('roket', 0)                  # Rocket Fusion Hellstorm'u artırmaz (fandom Rocket launcher)
        dmg = int(dmg * (1 + mods.get('roket', 0) - fusion + (mods.get('npc', 0) if n else 0) + mods.get('fircatici_hasar', 0))     # Rapid Fire Plus +%20
                  * (1 + p.lab_bonus(1)) * launcher_upgrade(p))
        drain = cfg.get('kalkan_cek', 0) * cnt
        impact = w.hit_asset if asset else w.hit_npc
        kw = {} if asset else {'ammo': ammo}            # Referee-Bot yalnız CBR'den hasar alır (dunya.hit_npc)

        def land(part, share):
            if part:                           # SAR/CBR/PIR: uzaylının kalkanından çekilen oyuncuya
                w.last_shield_hit = 0
                impact(uid, part, cfg.get('saldiri', 0), shield_only=True, **kw)
                if w.last_shield_hit:
                    g = p.d['gemi']
                    p.set_hull(shield=g.get('shield', 0) + w.last_shield_hit)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
            if share:
                impact(uid, share, 0, **kw)
        # kayıt (2026-10-27, ~100 salvo): hasar roket başına ayrı AttackHitCommand, ardışık roketler 2,18 sn arayla (2,1-2,24);
        # ilk hasar salvodan 0,73-1,9 sn sonra. Toplam hasar aynı: roketlere bölünür, kalan sonuncuya.
        first = random.uniform(FIRCATICI_ILK[0], FIRCATICI_ILK[1])
        for i in range(cnt):
            w.later(first + i * FIRCATICI_ARALIK, lambda b=dmg // cnt + (dmg % cnt if i == cnt - 1 else 0),
                    c=drain - drain // cnt * (cnt - 1) if i == cnt - 1 else drain // cnt: land(c, b))

    # ------------------------------------------------------------ özel roketler
    def fire_special(self, rocket, n, now):
        w, p = self.w, self.p
        r = ROCKETS[rocket]
        uid = getattr(n, 'id', n)
        asset = not hasattr(n, 'id')
        if asset and (not w.asset_at(uid) or w.asset_targets.asset_attackable(uid)
                      or not (r.get('hasar') or r.get('kalkan_hasar'))):
            return
        if not self.ready(r['bekleme_grubu'], now) or p.use_ammo(rocket, 1) is None:
            return
        w.end_invuln(force=True)
        w.abilities.reveal()
        self.reveal()
        w.last_combat = now
        w.stop_repair()
        p.ach('shot', silah='ROCKET_LAUNCHER')
        hit = random.random() < w.rocket_hit(rocket)
        self.send(w.ammo_msgs(rocket) + [w.rocket_msg(uid, hit, r.get('kimlik', 1)), self.cooldown(rocket, now)])
        if hit:
            w.later(ROCKET_FLIGHT, lambda: self.special_hit(rocket, uid))
        else:
            w.later(ROCKET_FLIGHT, lambda: self.send([('AttackMissedCommand', dict(attackType=attack_type(0), targetUserId=uid,
                                                                                    skillColorId=0))]))
        self.log('   özel roket: %s' % rocket)

    def special_hit(self, rocket, uid):
        import lazer as LAZER
        w, p = self.w, self.p
        n = w.npcs.get(uid)
        asset = w.asset_at(uid) if not n else None
        if w.hero_dead or w.jumping or (not asset and (not n or not n.alive)):
            return
        if asset and w.asset_targets.asset_attackable(uid):
            return
        impact = w.hit_asset if asset else w.hit_npc
        r = ROCKETS[rocket]
        dmg = r.get('hasar', 0) * ((LAZER.name_match(r.get('hedef_carpan', {}), n) or 1) if n else 1)      # AGT-500: Agatus'a x5
        if dmg:
            mods = p.mods()
            impact(uid, int(dmg * random.uniform(0.85, 1.0) * (1 + mods.get('roket', 0) + (mods.get('npc', 0) if n else 0))), 0,
                      hull_only=bool(r.get('yalniz_govde')))                                  # SP-100X: kalkanı atlar
        if r.get('kalkan_hasar'):                                                             # SR-5: kalkandan çal
            w.last_shield_hit = 0
            impact(uid, r['kalkan_hasar'], 0, shield_only=True)
            got = int(w.last_shield_hit * r.get('kalkan_cal', 0))
            if got:
                g = p.d['gemi']
                p.set_hull(shield=g.get('shield', 0) + got)
                self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
            if r.get('kendine_yavas'):
                w.hero_effect('yavas', r['kendine_yavas'][1], r['kendine_yavas'][0], source=rocket)
        if asset:                       # yapıların gemi görünümü, hızı ve isabet etkileri yok
            return
        if not n.alive:
            return
        if r.get('gorunum_sn'):                                                               # WIZ-X: başka bir geminin görünümü
            models = {int(t.get('model', k)) for k, t in _N['tipler'].items() if str(t.get('model', k)).isdigit()}
            ev = [m for k, m in sorted(r.get('gorunum_etkinlik', {}).items()) if TKV.is_active(k)]    # Thanksgiving: hindi, her isabette
            pool = [m for k, ms in sorted(r.get('gorunum_sansli', {}).items()) if TKV.is_active(k) for m in ms]    # etkinlik tasarımları
            if ev:
                model = str(ev[0])
            elif pool and random.random() < r.get('gorunum_sans', 1.0):              # etkinlikte %30 olasılıkla etkinlik tasarımı (wiki)
                model = str(random.choice(pool))
            else:
                model = str(random.choice(sorted(models - {int(n.model)})))
            vis = lambda on: [('VisualModifierCommand', dict(userId=uid, modifier=25, attribute=0, additionalAttribute=model, count=0,
                                                             activated=on))]
            self.send(vis(True))
            w.later(r['gorunum_sn'], lambda: self.send(vis(False)) if uid in w.npcs else None)
        for kind, (val, sec) in r.get('etki', {}).items():
            w.npc_effect(n, kind, sec, val, source=rocket)
        fx = r.get('fx')
        if fx:
            sec = max(s for v, s in r.get('etki', {}).values())
            self.send([legacy('0|n|fx|start|%s|%d' % (fx, uid))])
            w.later(sec, lambda: self.send([legacy('0|n|fx|end|%s|%d' % (fx, uid))]))
        if not n.engaged:
            n.engaged = True

    # ------------------------------------------------------------ atlama CPU'ları
    def jump_cpu(self, now):
        w, p = self.w, self.p
        loot = jump_loot(p)
        if not loot or w.hero_dead or w.jumping or self.jump:
            return
        home = int(w.map_id) == home_map(p)             # map_id metin: önce hiç tutmuyor, ana haritada da atlıyordu
        if home or not jump_allowed(loot, w.map_id) or EK.uses(p, loot) <= 0:
            # istemcinin metinleri: "…already on the target map." / "Jump from the current map not possible with your CPU!"
            why = 'jump_cpu_failed_ontarget' if home else None if jump_allowed(loot, w.map_id) else 'jump_cpu_failed_map'
            self.send(self.status(S['atlama_cpu']['menu']) + ([stm(why)] if why else []))
            return
        if self.too_soon(now):
            return
        self.start_jump(home_map(p), loot, now)

    def too_soon(self, now):
        """İstemcinin metni: "son atlamanız ya da girişiniz 10 saniyeden kısa süre önceydi"."""
        if now - self.born < S['atlama_cpu'].get('bekleme_sn', 10):
            self.send([stm('jump_cpu_failed_time')])
            return True
        return False

    def start_jump(self, dest, loot, now, voucher=False):
        w = self.w
        if now - w.last_combat < S['atlama_cpu']['savas_sn']:
            self.send([stm('jump_cpu_failed_attack3')])          # "uzaylıyla çatışmadan sonra 5 sn" (savas_sn)
            return False
        if w.radiation_since is not None:                      # forum 127075: radyasyonlu bölgede atlanmaz
            self.send([stm('jump_cpu_failed_map')])
            return False
        if loot == 'ajp' and now < self.p.d.get('ajp_hazir', 0):
            self.send([stm('ttip_block_cooldown')])                 # "CPU cooling down. Jump not possible." (forum 127075: 120 sn)
            return False
        sec = S['atlama_cpu']['geri_sayim_sn_ajp' if loot == 'ajp' else 'geri_sayim_sn']     # JP-01/02 anında, AJP-01 10 sn
        self.jump = dict(hedef=dest, zaman=now + sec, cpu=loot, basla=now, kupon=voucher, yer=w.hero_pos(now))
        if sec:                                                  # geri sayımsızda atlama sonraki adımda (jump_tick)
            self.send([legacy('0|A|JCPU|S|%d|%d' % (sec, dest))])
        self.log('   CPU atlaması: %s -> %s, %d sn' % (H.name(w.map_id), H.name(dest), sec))
        return True

    def cancel_jump(self, key='jump_cpu_failed_attack3'):
        """Geri sayımda saldırı: attack3 uzaylı metni (attack2 "başka pilotla 20 sn" PvP'nin; canlı test H22)."""
        if not self.jump:
            return
        self.jump = None
        self.send([legacy('0|A|JCPU|S|-1|0'), stm(key)])
        self.log('   CPU atlaması iptal')

    def jump_tick(self, now):
        j = self.jump
        if not j:
            return
        w, p = self.w, self.p
        if w.hero_dead or w.last_combat > j['basla']:
            self.cancel_jump()
            return
        x, y = w.hero_pos(now)
        if j.get('yer') and math.hypot(x - j['yer'][0], y - j['yer'][1]) > 5:     # forum 127075: geri sayımda hareket edilirse iptal
            self.cancel_jump('error_cpu_jump_cancelled_through_move')
            return
        if now < j['zaman']:
            return
        self.jump = None
        if j['cpu'] == 'ajp':
            if not self.pay_ajp(j['hedef']):
                self.send([legacy('0|A|JCPU|S|-1|0'), stm('jump_cpu_malfunction')])
                return
            with p.lock:
                p.d['ajp_hazir'] = now + S['gelismis_atlama']['bekleme_sn'] * AY.carpan('yetenek_bekleme')
                p.dirty = True
        else:
            EK.use(p, j['cpu'])
        w.jumping, w.attacking, w.target = True, False, None
        for n in w.npcs.values():
            n.engaged = False
        dest, pos = j['hedef'], 'rastgele' if j['cpu'] == 'ajp' else 'istasyon'   # AJP-01: hedef haritada rastgele yere (gerçek oyun)
        if (j['cpu'] != 'ajp' and int(w.map_id) != 42 and AY.get('atlama_sapma')                 # panel: kapatılabilir
                and random.random() < S['atlama_cpu'].get('mezarlik_sansi', 0)):
            dest, pos = 42, None                      # Cubikon Mezarlığı (wiki: "her 1.000 atlamada bir"; tek oyunculu oran)
            self.log('   atlama CPU\'su Cubikon Mezarlığı\'na saptı')
        if w.on_jump:
            self.send([stm('msg_cpu_jump_sequence_complete')])     # "CPU jump completed. Map switched." (forum 127075)
            w.on_jump(dest, None, pos)

    def pay_ajp(self, dest):
        p, c = self.p, S['gelismis_atlama']
        if p.resource(c['kupon']):
            p.add_resource(c['kupon'], -1)
            self.send([vouchers_msg(p)])
            return True
        price = ajp_price(p, dest, self.w.map_id)
        if p.d['pilot'].get('uridium', 0) < price:
            return False
        p.gain(uridyum=-price, neden='buy_cpu_jump')
        self.send(self.w.money_msgs() if self.w.money_msgs else [])
        return True

    def jcpu(self, parts):
        """İstemcinin JCPU isteği (uzay haritası): S|harita seçim, J atla (GET girişte; game.py yanıtlar)."""
        w, p = self.w, self.p
        cmd = parts[1] if len(parts) > 1 else ''
        if cmd == 'GET':
            self.send([jcpu_list(p), vouchers_msg(p)])
        elif cmd == 'S' and len(parts) > 2 and parts[2].isdigit():
            m = int(parts[2])
            ok = (has_ajp(p) and m != w.map_id and m in H.NAMES and jump_allowed('equipment_extra_cpu_ajp-01', m)
                  and jump_allowed('equipment_extra_cpu_ajp-01', w.map_id) and not ajp_locked(p, m))
            price = ajp_price(p, m, w.map_id) if m in H.NAMES else 0
            self.ajp_target = m if ok else None
            self.send([legacy('0|A|JCPU|C|%d|%d|%d' % (m, price, 1 if ok else 0))])
        elif cmd == 'J':
            m = self.ajp_target
            if m is None or not has_ajp(p) or w.hero_dead or w.jumping or self.jump:
                self.send([stm('jump_cpu_malfunction')])
                return
            price = ajp_price(p, m, w.map_id)
            if price and p.d['pilot'].get('uridium', 0) < price:
                self.send([stm('jump_cpu_malfunction')])
                return
            if self.too_soon(time.time()):
                return
            self.start_jump(m, 'ajp', time.time())

    # ------------------------------------------------------------ ölüm
    def on_death(self):
        self.cancel_jump('jump_cpu_malfunction')
        if self.cloaked():
            with self.p.lock:
                self.p.d['cpu_gizli'] = False
                self.p.dirty = True
