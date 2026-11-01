"""Gemi yetenekleri (profilde "gemi_yetenekleri"; veri data/ship_abilities.json ← wiki, istemcinin menüsü ve kodu).

İstemci: yetenekler kısayol menüsünün "ship_abilities" kategorisinde (kayıttaki MenuInitializationCommand: 65 öğe, hepsi gizli);
etkin geminin yetenekleri görünür ve kullanılabilir yapılır, oyuncu çubuğa sürükleyebilir. Tıklayınca MenuActionRequest {menuItemId,
actionType 0: zamanlayıcı öğesi, istemcinin kodu; testler 1 de gönderir}. Zamanlayıcı MenuItemTimerCommand {activatable, timerState (istemcinin TimerState'i: READY 0, ACTIVE 1, COOLING_DOWN 2),
menuItemId, maxTime, time}: milisaniye, time kalan süre (roket beklemesindeki MenuItemCooldownGroupTimerCommand gibi).
Görseller istemcinin kodundan: beceri kodu 1 Solace, 2 Diminisher, 3 Spectrum, 4 Sentinel, 5 Venom, 6 hız efekti. İstemcinin
AbilityEffectActivationCommand işleyicisi yalnız 1'i (ve 111, 140, 145) çiziyor; 2-6 eski metinle: 0|n|SD|A ya da D|kod|kalıcı|
etkinleştiren[|hedef] (SkillAssemblyHelper -> EventAssemblySkills; Frida izi ve canlı görüntü, 2026-10-23). AbilityStartCommand
(102 Draw Fire, 106 Target Marker, 110 EMP görseli, 111 Recon) ve AbilityStopCommand. Ötekilerin görsel kimliği bulunamadı.
Kurallar (wiki): bekleme etki bitince başlar; CD boosterı beklemeyi kısaltır; Elite tasarımları süre/bekleme/etki çarpanı. Speed
Boost aç/kapa (iki basış arası 10 sn). Gizlenme saldırınca, kutu toplayınca, atlayınca biter. Ölünce süren etkiler biter.
Bekleme süreleri profilde kalır (harita değişimi, yeniden giriş); hedefe bağlı etkiler (Venom, Diminisher, işaret) haritada kalır.
"""
import json, math, os, random, time

from legacy_protocol import legacy, stm
import settings as SET
import map_links as H

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'ship_abilities.json'), encoding='utf8'))
ABILITIES = D['skills']
SHIPS = D['ships']
READY, ACTIVE, COOLING = 0, 1, 2           # istemcinin TimerState'i
VISUAL_HOLD = 1.0                          # anlık yeteneklerin görseli bu kadar sonra kaldırılır


def mod(name, **f):
    f['_'] = name
    return f


def state(p):
    return p.d.setdefault('ship_abilities', {})


def sd_msg(op, effect, persistent, activator, target=None):
    """Eski metin: 0|n|SD|<A aç, D kapa>|<etki>|<kalıcı>|<etkinleştiren>[|<hedef>] (SkillAssemblyHelper; hedefsizse etkinleştirende)."""
    return legacy('0|n|SD|%s|%d|%d|%d' % (op, effect, persistent, activator) + ('|%d' % target if target else ''))


def row(p):
    """Geminin yetenek satırı: giyilen tasarımın kendi satırı varsa o (Centurion'un yetenek tasarımları, Holo tasarımlarının
    beklemesi, Hammerclaw Plus'ın Repair Pod'u; tools/ship_abilities.py)."""
    s = p.ship()
    return SHIPS.get(s.get('tasarim') or '') or SHIPS.get(s['lootId'], {})


def ship_items(p):
    return row(p).get('skills', [])


def factor(p, item, key):
    return row(p).get('multipliers', {}).get(item, {}).get(key, 1.0)


def special(p, item):
    """Geminin bu yetenek için kendi değerleri (istemcinin gemi verisi: sure_sn, bekleme_sn; wiki: etki)."""
    return row(p).get('ozel', {}).get(item, {})


def effect_def(p, item):
    """Yeteneğin etkisi, geminin kendi değerleriyle (Cyborg'un Singularity'si, Hammerclaw'ın onarımları)."""
    e = ABILITIES[item]['effect']
    o = special(p, item).get('effect')
    return dict(e, **o) if o else e


def duration(p, item):
    o = special(p, item)
    return o['sure_sn'] if 'sure_sn' in o else ABILITIES[item]['sure_sn'] * factor(p, item, 'sure')


def cooldown(p, item):
    """Bekleme: geminin kendi değeri ya da tasarım çarpanı, CD boosterı (ABILITY_COOLDOWN_TIME, booster.py 'bekleme')."""
    o = special(p, item)
    base = o['bekleme_sn'] if 'bekleme_sn' in o else ABILITIES[item]['bekleme_sn'] * factor(p, item, 'cooldown')
    return base * max(0.0, 1 - p.mods().get('cooldown', 0)) * SET.multiplier('skill_cooldown', 'yetenek')       # panel: yetenek beklemesi


def is_active(p, item, now=None):
    if item not in ABILITIES:
        return False
    s = state(p).get(item, {})
    if ABILITIES[item].get('toggle'):
        return bool(s.get('on'))
    return (now or time.time()) < s.get('bitis', 0)


def active_items(p, now=None):
    return [i for i in ship_items(p) if is_active(p, i, now)]


def effect(p, key, now=None):
    """Etkin yeteneklerin bir etkisi (ör. gorus, gizlen, roket_bekleme_ms) -> değer ya da None."""
    for i in active_items(p, now):
        e = effect_def(p, i)
        if key in e:
            return e[key]
    return None


def mods(p, now=None):
    """Etkin yeteneklerin bonusları (profil.mods'a eklenir); sabit_hiz en küçüğü (Fortify 0, Travel 450)."""
    out = {}
    for i in active_items(p, now):
        e = effect_def(p, i)
        for k, v in e.get('mods', {}).items():
            out[k] = min(out.get(k, v), v) if k == 'fixed_speed' else out.get(k, 0) + v
        if 'rage_hp' in e:                       # Berserk: kaybedilen her %1 can +%1 lazer hasarı
            g = p.d['gemi']
            lost = 1 - g.get('hitPoints', 0) / float(g.get('hitMax') or 1)
            out['lazer'] = out.get('lazer', 0) + max(0.0, lost) * e['rage_hp']
        y = e.get('cargo')
        if y:                                     # Momentum, Stockpile, Volt Discharge: etkinleşirken harcanan yük kadar
            n = state(p).get(i, {}).get('spent', 0)
            for k, v in y.get('mods', {}).items():
                out[k] = out.get(k, 0) + v * n
            for k, v in y.get('ramp', {}).items():           # Stockpile: her yük bir öncekinden %0,2 fazla
                out[k] = out.get(k, 0) + v * n * (n + 1) / 2.0
            if 'max_speed' in y:
                out['max_speed'] = min(out.get('max_speed', y['max_speed']), y['max_speed'])
        if 'reverse' in e:                     # Holo Self Reversal: takılı modüllerin eksileri artıya; eksi yoksa hasar ve hız
            import ship_module as GM
            neg = {k: v for k, v in GM.mods(p, p.ship()['lootId'], p.config().get('upgrades', []), p.d['pilot'].get('level')).items()
                   if v < 0}
            for k, v in ({k: -2 * v for k, v in neg.items()} if neg else e['reverse']).items():
                out[k] = out.get(k, 0) + v
    return out


def charge(p, kind, n=1):
    """Yük biriktiren yeteneklere yük (Momentum, Stockpile: uzaylı öldürme 'oldurme'; Volt Discharge: Voltage Link atlaması
    'zincir'), en çok azami kadar."""
    for i in ship_items(p):
        y = effect_def(p, i).get('cargo')
        if y and y['kaynak'] == kind and n > 0:
            with p.lock:
                st = state(p).setdefault(i, {})
                st['cargo'] = min(y['azami'], st.get('cargo', 0) + n)
                p.dirty = True


def range_bonus(p, now=None):
    """Etkin olmayan yük biriktiren yeteneklerin lazer menzili artışı (Momentum, Stockpile: yük başına +5)."""
    return sum(effect_def(p, i)['cargo'].get('menzil', 0) * state(p).get(i, {}).get('cargo', 0) for i in ship_items(p)
               if effect_def(p, i).get('cargo') and not is_active(p, i, now))


def take(p, key):
    """Bir sonraki atışa bir kez işleyen etki (Quantum Amplifier: Singularity Drive +%10) -> değer ya da 0."""
    for i in ship_items(p):
        if key in effect_def(p, i) and state(p).get(i, {}).get('pending'):
            with p.lock:
                p.dirty = True
                return state(p)[i].pop('pending')
    return 0


def timer_fields(p, item, now=None):
    now = now or time.time()
    s = state(p).get(item, {})
    if is_active(p, item, now):
        if ABILITIES[item].get('toggle'):
            return dict(activatable=now >= s.get('hazir', 0), timerState=ACTIVE, maxTime=0, time=0)
        return dict(activatable=False, timerState=ACTIVE, maxTime=s.get('duration_ms', 0), time=max(0, int((s['bitis'] - now) * 1000)))
    if now < s.get('hazir', 0):
        return dict(activatable=False, timerState=COOLING, maxTime=s.get('cooldown_ms', 0), time=int((s['hazir'] - now) * 1000))
    return dict(activatable=True, timerState=READY, maxTime=0, time=0)


HECATE_BEAM = {k: dict(sure_sn=5, ilk=8050, increase=6000, slow=0.1, npc=('experiment_beacon',))      # forum 143093 (Plutus Deneyleri)
               for k in ('ability_hecate_particle-beam', 'ability_hecate-plus_particle-beam-plus')}
GROUP_RANGE = 1000          # grup yeteneklerinin menzili (kaynakta yok: uyarlama)
PVP_SLOW = 0.4             # forum 160373: Hyperion Çapa oyuncuyu %40 yavaşlatır
ALLY_REPAIR = {'ability_aegis_hp-repair': {'hp_repair': 280000}, 'ability_aegis_shield-repair': {'shield_repair': 125000}}
REPEAT_END = ('ability_retiarus-plus_chsp', 'ability_solaris-plus_incinerate-plus')


def tartarus_set(p, pet):
    """Tartarus tam set: Chimera P.E.T. tasarımı ve bütün dronlarda aynı renkte Phantom tasarımı (forum 160373)."""
    es = p.d['esyalar']
    pet = pet.design() or ''
    designs = {es.get(str(p.drone_design_id(d, 'design', p.active_config)), '') for d in p.d.get('drones', [])}
    return 'chimera' in pet and len(p.d.get('drones', [])) >= 10 and len(designs) == 1 and 'phantom' in next(iter(designs))


def timer_msg(p, item, now=None):
    f = timer_fields(p, item, now)
    return ('MenuItemTimerCommand', dict(activatable=f['activatable'], timerState=mod('TimerStateModule', timerStateValue=f['timerState']),
                                         menuItemId=item, maxTime=f['maxTime'], time=f['time']))


def line(item, stop=False):
    """Yeteneğin "… activated" / "… deactivated" satırı (istemcinin metni, ship_abilities.json "metin"; yoksa boş)."""
    key = (ABILITIES[item].get('metin') or [None, None])[1 if stop else 0]
    return [stm(key)] if key else []


def menu_status(p, item, st):
    """Kısayol menüsündeki yetenek öğesi: yalnız etkin geminin yetenekleri görünür; Last Stand kuruluyken seçili."""
    owned = item in ship_items(p)
    st.update(visible=owned, available=owned, activatable=owned and timer_fields(p, item)['activatable'])
    if owned:                                  # ipucundaki %DURATION% (Incinerate, Shield Disarray …): istemci yalnız mağazada doldurur
        rep = {'_': 'MessageWildcardReplacementModule', 'wildcard': '%DURATION%', 'replacement': '%g' % duration(p, item),
               'replacementType': {'_': 'ReplacementTypeModule', 'typeValue': 0}}
        for k in ('toolTipSlotBar', 'toolTipItemBar'):
            for line_ in (st.get(k) or {}).get('commandList', []):
                line_['wildCardReplacements'] = [dict(rep)]
    if owned and ABILITIES[item].get('effect', {}).get('last_stand'):
        st['selected'] = bool(state(p).get(item, {}).get('built'))
    return st


POD_UID = [980000]                 # yetenek nesnelerinin kimlikleri (haritanın varlıklarıyla çakışmaz)


class Engine:
    """Dünyadaki yetenekler: etkinleştirme, süre boyunca etkiler (onarım, zehir), bitiş ve bekleme bildirimleri."""

    def __init__(self, world, laser_range=700):
        self.w, self.p, self.range = world, world.p, laser_range
        self.pods = {}             # yetenek -> haritadaki nesnesinin kimliği (Repair Pod)
        self.ending = {}           # yetenek -> bitiş anı (bitince görsel kaldırılır, bekleme başlar)
        self.charging = {}         # yetenek -> [hedef, başlangıç] (Charge Shot dolumu)
        self.beams = {}            # Hecate Particle Beam: yetenek -> {hedef, basla, son}
        self.waiting = set()       # beklemesi süren: bitince READY
        self.next_heal = 0.0
        self.flags = dict(cloak=False, vision=1.0, roket=None)   # sık sorulanlar: döngüde bir kez hesaplanır (refresh)
        now = time.time()
        for i in ship_items(self.p):
            s = state(self.p).get(i, {})
            if not ABILITIES[i].get('toggle') and now < s.get('bitis', 0):
                self.ending[i] = s['bitis']
            elif now < s.get('hazir', 0):
                self.waiting.add(i)
        self.refresh(now)

    def refresh(self, now=None):
        self.flags = dict(cloak=bool(effect(self.p, 'cloak', now)), vision=effect(self.p, 'vision', now) or 1.0,
                          roket=effect(self.p, 'rocket_cooldown_ms', now))

    # ------------------------------------------------------------ sorgular (dunya.py)
    def cloaked(self, now=None):
        return self.flags['cloak']

    def view_factor(self, now=None):
        return self.flags['vision']

    def rocket_ms(self, ms, now=None):
        fast = self.flags['roket']
        return min(ms, fast) if fast else ms

    # ------------------------------------------------------------ etkinleştirme
    def send(self, msgs):
        if msgs:
            self.w.send(msgs)

    def stats(self):
        return self.w.stats_msgs() if self.w.stats_msgs else []

    def visual_on(self, item, target):
        g = ABILITIES[item].get('visual', {})
        if 'appearance' in g:                        # gemi görünümü (istemcinin VisualModifier'ı: 8 FORTIFY zırh, 9 PROTECT_OWNER halka)
            return [('VisualModifierCommand', dict(userId=self.w.hid, modifier=g['appearance'], attribute=0, additionalAttribute='',
                                                   count=0, activated=True))]
        if 'entity' in g:                         # haritaya konan nesne (Aegis Repair Pod: HEALING_POD 33), etki boyunca yerinde
            hx, hy = self.w.hero_pos()
            self.pods[item] = POD_UID[0] = POD_UID[0] + 1
            return [('AssetCreateCommand', dict(designId=0, clanId=0, showBubble=False, userName='', assetId=self.pods[item],
                                                expansionStage=0, modifier=[], type={'_': 'AssetTypeModule', 'typeValue': g['entity']},
                                                detectedByWarnRadar=False, invisible=False, posX=int(hx), posY=int(hy),
                                                clanRelation={'_': 'ClanRelationModule', 'type': 0}, clanTag='',
                                                factionId=self.p.d['pilot'].get('factionId', 0), visibleOnWarnRadar=False))]
        if 'effect' in g:
            persistent = duration(self.p, item) > 0 or bool(ABILITIES[item].get('toggle'))
            if g['effect'] != 1:                    # istemci ikili komutu yalnız Solace'a çiziyor; 2-6 eski "SD" metniyle (EventAssemblySkills)
                return [sd_msg('A', g['effect'], int(persistent), self.w.hid, target)]
            return [('AbilityEffectActivationCommand', dict(selectedAbilityId=g['effect'], activatorId=self.w.hid,
                                                            isPersistent=persistent, targetIds=[target or self.w.hid]))]
        if 'launch' in g:
            return [('AbilityStartCommand', dict(selectedAbilityId=g['launch'], activatorId=self.w.hid, noStopCommand=False))]
        return []

    def visual_off(self, item, target):
        g = ABILITIES[item].get('visual', {})
        if 'appearance' in g:
            return [('VisualModifierCommand', dict(userId=self.w.hid, modifier=g['appearance'], attribute=0, additionalAttribute='',
                                                   count=0, activated=False))]
        if 'entity' in g:
            uid = self.pods.pop(item, None)
            return [('AssetRemoveCommand', {'assetType': {'_': 'AssetTypeModule', 'typeValue': g['entity']}, 'uid': uid})] if uid else []
        if 'effect' in g:
            if g['effect'] != 1:
                return [sd_msg('D', g['effect'], 0, self.w.hid, target)]
            return [('AbilityEffectDeActivationCommand', dict(selectedAbilityId=g['effect'], activatorId=self.w.hid,
                                                              targetIds=[target or self.w.hid]))]
        if 'launch' in g:
            return [('AbilityStopCommand', dict(selectedAbilityId=g['launch'], activatorId=self.w.hid, targetIds=[target or self.w.hid]))]
        return []

    def mates(self, now, radius=GROUP_RANGE):
        """Aynı haritada, radius içinde, grubundaki öteki oyuncular (yerel çok istemci)."""
        w = self.w
        if not w.shared:
            return []
        hx, hy = w.hero_pos(now)
        return [o for o in w.shared.members if o is not w and o.running and not o.hero_dead and w.is_group_member(o.hid)
                and math.hypot(*(a - b for a, b in zip(o.hero_pos(now), (hx, hy)))) <= radius]

    def mate_bots(self, now, radius=GROUP_RANGE):
        """Haritada, radius içinde, grubundaki botların gemileri (bot/govde; oyuncu bildirimi 2026-10-31: Solace onları onarmıyordu)."""
        w = self.w
        hx, hy = w.hero_pos(now)
        return [n for n in list(w.npcs.values()) if n.bot is not None and n.alive and w.is_group_member(n.bot.uid)
                and math.hypot(*(a - b for a, b in zip(n.mover.pos(now), (hx, hy)))) <= radius]

    def heal_bot(self, n, hp=0, shield=0):
        h0, s0 = n.hp, n.shield
        n.hp, n.shield = min(n.d['hp'], n.hp + hp), min(n.d['kalkan'], n.shield + shield)
        # oyuncu bildirimi 2026-11-01: onarım görünmüyordu; botun üstünde "+miktar" (dunya.heal_msgs'in HL satırı, iyileştiren kahraman)
        msgs = [legacy('0|A|HL|%d|%d|%s|%d|%d' % (self.w.hid, n.id, kind, int(v), int(v) - int(v0)))
                for kind, v0, v in (('HPT', h0, n.hp), ('SHD', s0, n.shield)) if int(v) > int(v0)]
        if self.w.target == n.id:
            msgs.append(self.w.selection(n))
        if msgs:
            self.w.send(msgs)

    def foes(self, now, e=None, radius=None):
        """Yeteneğin etkilediği düşman oyuncular: alan (radius ya da alan_yavaslat) içindekiler, saldırı kuralı geçerliyse."""
        w = self.w
        if not w.shared:
            return []
        import player_combat as OS_
        r = radius or ((e or {}).get('area_slow') or {}).get('yaricap') or (self.range if (e or {}).get('target_slow') else 0)
        if not r:
            return []
        hx, hy = w.hero_pos(now)
        return [o for o in w.shared.members if o is not w and not OS_.attack_error(w, o, now)
                and math.hypot(*(a - b for a, b in zip(o.hero_pos(now), (hx, hy)))) <= r]

    def foe_target(self, now):
        """Seçili hedef bir oyuncuysa onun dünyası."""
        return self.w.player(self.w.target) if self.w.target is not None else None

    def heal_mates(self, item, key, stop, now):
        """Aegis / Hammerclaw onarımı menzildeki grup üyelerine de (dosta Aegis HP 280.000, kalkan 125.000: wiki GEMILER-4)."""
        amount = ALLY_REPAIR.get(item, {}).get(key) or effect_def(self.p, item)[key]
        for o in self.mates(now):
            other_ship = o.p.d['gemi']
            if key == 'hp_repair':
                h0 = other_ship.get('hitPoints', 0)
                o.p.set_hull(hp=h0 + amount / stop)
                o.send([o.hp_msg()] + o.heal_msgs(h0))
            else:
                s0 = other_ship.get('shield', 0)
                o.p.set_hull(shield=s0 + amount / stop)
                o.send([('AttributeShieldUpdateCommand', {'shieldNow': int(other_ship['shield']), 'shieldMax': other_ship.get('shieldMax', 0)})])
        for n in self.mate_bots(now):
            self.heal_bot(n, **{('hp' if key == 'hp_repair' else 'shield'): amount / stop})

    def near(self, radius, now, center=None):
        """Gemiye (ya da center noktasına) radius içindeki canlı uzaylılar."""
        hx, hy = center or self.w.hero_pos(now)
        return [n for n in list(self.w.npcs.values()) if n.alive and math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= radius]

    def last_stand(self, now):
        """Paladin Last Stand: ölümcül vuruşta hazırsa can dolar, bekleme başlar -> True."""
        p = self.p
        for i in ship_items(p):
            s = state(p).get(i, {})
            if effect_def(p, i).get('last_stand') and s.get('built') and now >= s.get('hazir', 0):
                cd = cooldown(p, i)
                with p.lock:
                    state(p).setdefault(i, {}).update(bitis=now, hazir=now + cd, cooldown_ms=int(cd * 1000), built=False)
                    p.dirty = True
                self.waiting.add(i)
                self.send([timer_msg(p, i, now), stm('msg_last_stand_stopped')] + [('MenuItemStatusCommand', x) for x in
                                                                                 [p.menu_status(i)] if x])
                return True
        return False

    def hold_on(self, now):
        """Tempest Volt Back-up: etkinken ölümcül vuruşta can 1'de kalır, ardından kısa dokunulmazlık; tetiklenince yetenek biter ve
        bekleme başlar (istemci: "invulnerable for 3 seconds. Once the invulnerability is triggered, this skill enters cooldown") -> True."""
        for i in active_items(self.p, now):
            sec = effect_def(self.p, i).get('undying')
            if sec:
                self.w.hero_effects.add('immune_until', sec, 1.0, i, now)
                self.end_now(i, now)
                self.w.log('   Volt Back-up: can 1, %d sn dokunulmaz' % sec)
                return True
        return False

    def arm_last_stand(self, item, now):
        """Last Stand bir kurulur ("Last Stand activated"), ölümcül vuruşta can dolar ve bekleme o zaman başlar; yeniden basınca
        kapanır (istemcinin msg_last_stand_activated/stopped metinleri). Önceden basınca bekleme hemen başlıyor, koruma
        kalmıyordu (canlı test H42)."""
        p = self.p
        with p.lock:
            st = state(p).setdefault(item, {})
            st['built'] = not st.get('built')
            p.dirty = True
        st_ = p.menu_status(item)
        self.send([stm('msg_last_stand_activated' if st['built'] else 'msg_last_stand_stopped')]
                  + ([('MenuItemStatusCommand', st_)] if st_ else []))
        self.w.log('   Last Stand %s' % ('installed' if st['built'] else 'kapandı'))
        return True

    def activate(self, item):
        """MenuActionRequest ability_…: hazırsa etkinleştir -> True."""
        w, p, now = self.w, self.p, time.time()
        a = ABILITIES.get(item)
        if not a or item not in ship_items(p):
            w.log('   yetenek bu gemide yok: %s' % item)
            return False
        st = state(p).get(item, {})
        if item in REPEAT_END and is_active(p, item, now):    # forum 160989: Hyper Charge Shot ve Incinerate Plus yeniden basınca biter
            self.end_now(item, now)
            w.log('   yetenek erken bitirildi: %s' % item)
            return True
        if w.hero_dead or w.jumping or (not a.get('toggle') and is_active(p, item, now)) or now < st.get('hazir', 0):
            self.send([timer_msg(p, item, now)])
            w.log('   yetenek kullanılamaz: %s (bekliyor ya da etkin)' % item)
            return False
        e = effect_def(p, item)
        if e.get('last_stand'):
            return self.arm_last_stand(item, now)
        if e.get('cargo') and not st.get('cargo'):     # Momentum, Stockpile, Volt Discharge: yüksüz basılmaz
            self.send([timer_msg(p, item, now)])
            w.log('   yetenek için yük yok: %s' % item)
            return False
        if e.get('phase_out') and (w.gate or H.name(w.map_id).startswith('5-')):     # Phase Out: kapıda ve korsan haritasında çalışmaz
            self.send([timer_msg(p, item, now)])
            w.log('   yetenek bu haritada çalışmaz: %s' % item)
            return False
        target = None
        if a.get('targeted'):
            n = w.npcs.get(w.target)
            hx, hy = w.hero_pos(now)
            if not n or not n.alive or (math.hypot(*(c - h for c, h in zip(n.mover.pos(now), (hx, hy)))) > self.range
                                        and not e.get('teleport_to_target')):         # Sleight: seçili hedefe menzil sınırı olmadan ışınlanır
                self.send([timer_msg(p, item, now)])
                w.log('   yetenek için menzilde hedef yok: %s' % item)
                return False
            target = n
        if a.get('toggle'):                     # Speed Boost: aç/kapa, iki basış arası bekleme
            with p.lock:
                st = state(p).setdefault(item, {})
                st['on'] = not st.get('on')
                cd = cooldown(p, item)
                st.update(hazir=now + cd, cooldown_ms=int(cd * 1000))
                p.dirty = True
            self.refresh(now)
            msgs = (self.visual_on(item, None) if st['on'] else self.visual_off(item, None)) + [timer_msg(p, item, now)] +                 line(item, stop=not st['on'])
            self.waiting.add(item)                # iki basış arası bekleme bitince düğme yine basılabilir
            pet = getattr(w, 'pet', None)
            if st['on'] and p.ship()['lootId'] == 'ship_tartarus' and pet and pet.active and tartarus_set(p, pet):
                pet.select(1)                     # forum 160373 Tartarus tam seti: Hız Desteğinde P.E.T. yanaşır ve pasif moda geçer
            self.send(msgs + self.stats())
            w.log('   yetenek %s: %s' % (a['ad'], 'açık' if st['on'] else 'kapalı'))
            if st['on']:
                p.ach('ability', tur=a.get('achievement'))
            return True
        stop, cd = duration(p, item), cooldown(p, item)
        with p.lock:
            st = state(p).setdefault(item, {})
            st.update(bitis=now + stop, hazir=now + stop + cd, duration_ms=int(stop * 1000), cooldown_ms=int(cd * 1000), hedef=target.id if target else None)
            if e.get('cargo'):
                st['spent'], st['cargo'] = st.get('cargo', 0), 0       # menzil ilk değerine, yükler sıfıra
            if 'next_gsp' in e:
                st['pending'] = e['next_gsp']
            p.dirty = True
        msgs = self.visual_on(item, target.id if target else None) + [timer_msg(p, item, now)] + line(item)
        g = p.d['gemi']
        if 'hp_percent' in e:                      # Solace: anında azami canın %35'i
            hp0 = g.get('hitPoints', 0)
            p.set_hull(hp=hp0 + g.get('hitMax', 0) * e['hp_percent'] * factor(p, item, 'effect'))
            msgs += [w.hp_msg()] + w.heal_msgs(hp0)
            for o in self.mates(now):            # forum 160373: Nano-Cluster grup üyelerini de onarır
                other_ship = o.p.d['gemi']
                h0 = other_ship.get('hitPoints', 0)
                o.p.set_hull(hp=h0 + other_ship.get('hitMax', 0) * e['hp_percent'] * factor(p, item, 'effect'))
                o.send([o.hp_msg()] + o.heal_msgs(h0))
            for n in self.mate_bots(now):
                self.heal_bot(n, hp=n.d['hp'] * e['hp_percent'] * factor(p, item, 'effect'))
        if 'target_shield_damage' in e:            # Diminisher Weaken Shields: süre boyunca hedefin kalkanına giden hasar artar (dunya.hit_npc)
            target.effect.add('shield_damage_taken', stop, e['target_shield_damage'], item, now)
        if e.get('teleport_to_target'):                # Keres Sleight: hedefin konumuna ışınlan (Phase Out'taki anlık MoveCommand yolu), ardından hedef yavaşlar
            x, y = (int(c) for c in target.mover.pos(now))
            w.hero = type(w.hero)(x, y)
            msgs.append(('MoveCommand', dict(userId=w.hid, x=x, y=y, timeToTarget=0)))
        if 'target_shield_off' in e:             # Disruptor Shield Disarray: kalkanın yarısı süre boyunca kapanır, bitince geri
            st['shut_off'] = int(target.shield * e['target_shield_off'])
            target.shield -= st['shut_off']
            msgs.append(w.selection(target))
        if 'target_fire_interval' in e:             # DDoL: hedefin lazer beklemesi 3-5 sn
            target.effect.add('shot_disrupted', stop, 0, item, now, interval=e['target_fire_interval'])
        if 'poison' in e:                          # Venom: saniyede bir gövdeye
            z = e['poison']
            target.effect.add('poison', stop + 1, z['ilk'], item, now, increase=z['increase'], max_count=z['max_count'], kalan=z['toplam'],
                            next=now)
        if 'target_damage' in e:
            target.effect.add('damage_bonus', stop, e['target_damage'], item, now)
        if 'draw_fire' in e:                       # Draw Fire: menzildeki uzaylılar saldırır
            hx, hy = w.hero_pos(now)
            for n in w.npcs.values():
                nx, ny = n.mover.pos(now)
                if n.alive and n.d['hasar'] > 0 and math.hypot(nx - hx, ny - hy) <= e['draw_fire']:
                    n.engaged, n.next_think = True, now
        if e.get('cloak'):                       # Ultimate Cloaking: kovalayanlar bırakır
            for n in w.npcs.values():
                if n.engaged:
                    w.disengage(n, now)
        if item in HECATE_BEAM and w.target is not None:     # forum 143093: ışın 5 sn, oyunculara ve işaret kulelerine
            self.beams[item] = dict(hedef=w.target, start=now, last=now)
        if 'reload' in e:                          # Retiarus Charge Shot: süre boyunca dolar (tick), sonra vurur
            self.charging[item] = [target.id, now]
        if 'target_freeze' in e:                   # Goliath-X Frozen Claw
            target.effect.add('frozen', e['target_freeze'], 1.0, item, now)
        if 'target_slow' in e:                 # Pusat Plus Speed Sap
            target.effect.add('slow', stop, e['target_slow'], item, now)
        for o in self.foes(now, e):               # forum 160373: oyunculara da (Keres, Pusat Plus, Hyperion)
            if 'target_slow' in e and o is self.foe_target(now):
                o.hero_effects.add('slow', stop, e['target_slow'], item, now)
                o.send(o.effect_stats_msgs(now))
            if 'area_slow' in e:
                o.hero_effects.add('slow', stop, PVP_SLOW, item, now)
                o.send(o.effect_stats_msgs(now))
        if 'area_slow' in e:                  # Hyperion Gravitational Anchor: alan hedefin konumunda
            for n in self.near(e['area_slow']['yaricap'], now, target.mover.pos(now) if target else None):
                n.effect.add('slow', stop, e['area_slow']['oran'], item, now)
        if 'chain_damage' in e:                   # Tempest Voltage Link: hedef ve sıradaki en yakınlar, her atlamada artar
            z, hit, cur, dmg = e['chain_damage'], [], target, float(e['chain_damage']['ilk'])
            while cur and len(hit) < z['hedef']:
                hit.append(cur.id)
                cur.effect.add('frozen', 1.0, 1.0, item, now)
                w.hit_npc(cur.id, int(dmg), 1)
                dmg *= 1 + z.get('increase', 0)
                cx, cy = cur.mover.pos(now)
                rest = [(math.hypot(n.mover.pos(now)[0] - cx, n.mover.pos(now)[1] - cy), n) for n in w.npcs.values()
                        if n.alive and n.id not in hit]
                rest = [r for r in rest if r[0] <= z['menzil']]
                cur = min(rest, key=lambda r: r[0])[1] if rest else None
            charge(p, 'chain', len(hit) - 1)    # Volt Discharge: her atlama bir yük
        if 'triangle_blast' in e:                  # Zephyr Triple Barrage: hedefin arkasında üçgen üç patlama, kesişen alan toplanır
            u, (hx, hy), (tx, ty) = e['triangle_blast'], w.hero_pos(now), target.mover.pos(now)
            d = math.hypot(tx - hx, ty - hy) or 1.0
            ux, uy, gap = (tx - hx) / d, (ty - hy) / d, u['distance']
            for cx, cy in ((tx + ux * gap, ty + uy * gap), (tx + 2 * ux * gap - uy * gap, ty + 2 * uy * gap + ux * gap),
                           (tx + 2 * ux * gap + uy * gap, ty + 2 * uy * gap - ux * gap)):
                for n in self.near(u['yaricap'], now, (cx, cy)):
                    w.hit_npc(n.id, int(u['hasar']), 1)
        if 'rocket_cooldown_ms' in e and w.rocket_ready > now:
            w.rocket_ready = now                  # Rapid Fire: roket hemen hazır
            msgs.append(('MenuItemCooldownGroupTimerCommand', dict(timerState=mod('TimerStateModule', timerStateValue=READY),
                                                                   cooldownType=mod('CooldownTypeModule', typeValue=4), maxTime=0, time=0)))
        if 'mods' in e:
            msgs += self.stats()
        self.ending[item] = now + (stop if stop > 0 else VISUAL_HOLD)
        self.refresh(now)
        self.send(msgs)
        p.ach('ability', tur=a.get('achievement'))
        w.log('   yetenek: %s (%s sn, bekleme %d sn)%s' % (a['ad'], ('%.1f' % stop) if stop else 'anlık', cd,
                                                          ' -> %s' % target.d['ad'] if target else ''))
        return True

    # ------------------------------------------------------------ süre
    def finish(self, item, now):
        """Etki bitti: görsel kalkar, kendi kalkanın azalır (Diminisher Weaken Shields) ya da hedefin kalkanı geri gelir (Shield Disarray),
        dolan vuruş (Charge Shot), bekleme başlar."""
        p, w = self.p, self.w
        self.ending.pop(item, None)
        s = state(p).get(item, {})
        e = effect_def(p, item)
        msgs = []
        if 'phase_out' in e and not (w.hero_dead or w.jumping):     # Phase Out: solan gemi rastgele yönde belirir (anlık MoveCommand)
            (x, y), a = w.hero_pos(now), random.uniform(0, 2 * math.pi)
            x, y = int(min(max(0, x + e['phase_out'] * math.cos(a)), w.map_w)), int(min(max(0, y + e['phase_out'] * math.sin(a)), w.map_h))
            w.hero = type(w.hero)(x, y)
            msgs.append(('MoveCommand', dict(userId=w.hid, x=x, y=y, timeToTarget=0)))
        msgs += self.visual_off(item, s.get('hedef'))
        if item in self.charging:
            self.discharge(item, now)
        back = s.pop('shut_off', 0)
        if back and s.get('hedef') in w.npcs and w.npcs[s['hedef']].alive:
            n = w.npcs[s['hedef']]
            n.shield = min(max(n.d.get('kalkan', 0), n.shield), n.shield + back)
            if w.target == n.id:
                msgs.append(w.selection(n))
        if 'shield_loss' in e and not w.hero_dead:      # Weaken Shields: etki bitince KENDİ kalkanının %30'u gider
            g = p.d['gemi']
            p.set_hull(shield=g.get('shield', 0) * (1 - e['shield_loss']))
            msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)}))
        n = w.npcs.get(s.get('hedef'))
        if n:
            n.effect.remove(source=item)            # hedefteki etkiler (zayıf kalkan, zehir, işaret) erken kalkar
        if duration(p, item) > 0:                 # anlık yeteneklerin (Solace) bitiş satırı yok
            msgs += [timer_msg(p, item, now)] + line(item, stop=True)
        if 'mods' in e:
            msgs += self.stats()
        self.waiting.add(item)
        self.refresh(now)
        self.send(msgs)

    def discharge(self, item, now):
        """Charge Shot: dolan hasar hedefe (Plus'ta hedefin çevresindekilere bölünür)."""
        tid, start = self.charging.pop(item)
        d, n = effect_def(self.p, item)['reload'], self.w.npcs.get(tid)
        dmg = min(d['azami'], d['per_second'] * (now - start))
        if not n or not n.alive or dmg <= 0:
            return
        hit = [n] + ([m for m in self.near(d['split_radius'], now, n.mover.pos(now)) if m is not n] if d.get('split_radius') else [])
        for m in hit:
            self.w.hit_npc(m.id, int(dmg / len(hit)), 1)
        self.w.log('   Charge Shot: %d hasar, %d hedef' % (dmg, len(hit)))

    def end_now(self, item, now):
        with self.p.lock:
            s = state(self.p).get(item, {})
            if now < s.get('bitis', 0):
                left = s['bitis'] - now
                s['bitis'] = now
                s['hazir'] = s.get('hazir', now) - left
        self.finish(item, now)

    def reveal(self):
        """Saldırı, kutu toplama, atlama: gizlenme biter."""
        now = time.time()
        for i in active_items(self.p, now):
            if effect_def(self.p, i).get('cloak'):
                self.end_now(i, now)
                self.w.log('   gizlenme bitti')

    def on_death(self):
        now = time.time()
        self.charging.clear()                      # ölünce dolan vuruş gitmez
        for i in list(self.ending):
            self.end_now(i, now)
        with self.p.lock:
            for i in ship_items(self.p):
                if effect_def(self.p, i).get('cargo'):
                    state(self.p).setdefault(i, {})['cargo'] = 0      # yükler ölünce sıfırlanır (wiki)
        for i in ship_items(self.p):
            s = state(self.p).get(i, {})
            if s.get('on'):
                with self.p.lock:
                    s['on'] = False
                self.refresh(now)
                self.send(self.visual_off(i, None) + [timer_msg(self.p, i, now)] + line(i, stop=True))

    def tick(self, now):
        p, w = self.p, self.w
        if now >= self.next_heal:                 # Aegis onarımları: saniyede eşit pay
            self.next_heal = now + 1.0
            g = p.d['gemi']
            for i in active_items(p, now):
                e = effect_def(p, i)
                stop = max(duration(p, i), 1)
                if 'area_damage' in e and 'per_second' in e['area_damage'] and not w.hero_dead:     # Solaris, Paladin Ripper
                    a = e['area_damage']
                    dmg = a['per_second'] + (w.laser_damage(None)[0] * a['laser_share'] if a.get('laser_share') else 0)
                    for n in self.near(a['yaricap'], now):
                        w.hit_npc(n.id, int(dmg), 1)
                    for o in self.foes(now, None, a['yaricap']):     # forum 160373: Ripper/Incinerate oyunculara da
                        import player_combat as OS
                        OS._hit(w, o, now, int(dmg))
                if 'hp_repair' in e and not w.hero_dead:
                    hp0 = g.get('hitPoints', 0)
                    p.set_hull(hp=hp0 + e['hp_repair'] * factor(p, i, 'effect') / stop)
                    self.send([w.hp_msg()] + w.heal_msgs(hp0))
                    self.heal_mates(i, 'hp_repair', stop, now)
                if 'shield_melt' in e and not w.hero_dead:     # Scramble, Supercharge Plus: saniyede azami kalkanın %10'u
                    sh = max(0, g.get('shield', 0) - g.get('shieldMax', 0) * e['shield_melt'])
                    p.set_hull(shield=sh)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})])
                    if sh <= 0 and e.get('close_at_zero'):
                        self.end_now(i, now)               # Scramble: kalkan biterse kapanır
                if 'reload' in e and i in self.charging:     # Charge Shot: hedef menzilden çıkınca ya da dolunca vurur
                    tid, start = self.charging[i]
                    n = w.npcs.get(tid)
                    hx, hy = w.hero_pos(now)
                    full = e['reload']['per_second'] * (now - start) >= e['reload']['azami']
                    if full or not n or not n.alive or math.hypot(*(c - h for c, h in zip(n.mover.pos(now), (hx, hy)))) > self.range:
                        self.end_now(i, now)
                if 'shield_repair' in e and not w.hero_dead:
                    sh0 = g.get('shield', 0)
                    p.set_hull(shield=sh0 + e['shield_repair'] * factor(p, i, 'effect') / stop)
                    self.send([('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g.get('shieldMax', 0)})]
                              + w.heal_msgs(sh0=sh0))
                    self.heal_mates(i, 'shield_repair', stop, now)
        for i, b in list(self.beams.items()):          # Hecate: saniyede 8.050 + 6.000 x geçen sn (forum 143093)
            h = HECATE_BEAM[i]
            if now - b['start'] > h['sure_sn'] or w.hero_dead:
                del self.beams[i]
                continue
            if now - b['last'] < 1:
                continue
            b['last'] = now
            dmg = int(h['ilk'] + h['increase'] * int(now - b['start']))
            n = w.npcs.get(b['hedef'])
            if n and n.alive and n.tip in h['npc']:
                w.hit_npc(n.id, dmg, 1)
                n.effect.add('slow', 1.5, h['slow'], i, now)
            o = w.player(b['hedef'])
            if o:
                import player_combat as OS
                OS._hit(w, o, now, dmg)
                o.hero_effects.add('slow', 1.5, h['slow'], i, now)
        for i, t in list(self.ending.items()):
            if now >= t:
                self.finish(i, now)
        for i in list(self.waiting):
            if now >= state(p).get(i, {}).get('hazir', 0):
                self.waiting.discard(i)
                if i in ship_items(p):
                    self.send([timer_msg(p, i, now)])
