"""GM konsolu (yol haritası Ö2): istemcinin gizli yönetici penceresi (UIAdminTools, pencere 82) sunucuya bağlanır.

İstemcide (Ghidra: UnitFactory.InitMyUnit, GmComponentSystem, GmComponentSystemAwake, ClientDebugHelper):
  - Pencere yalnız Hero.Admin iken açılır; Admin = ShipInitializationCommand.dailyRank == 6000. Açma: Ctrl, ardından Shift, ardından Z.
    Admin olunca istemci ayrıca çıkış sayacını kısaltır ve görev listesinde görev kimliklerini "#id:" diye yazar.
  - İlk açılışta CCInitRequest -> CCInitCommand {commands: [CCommandModule {name, args: [CCAttributeModule {name, subAttributes,
    range (CCListRangeModule {valueList}), …}]}]}: istemci yalnız "box" (args 'spawn' > 'boxType' listesi) ve "quest" (args
    'accept' listesi) komutlarının değer listelerini açılır listelere alır.
  - Komutlar CCommandRequest {name, attributes: [CCRequestAttributeModule {name, value (CCIntValueModule / CCStringValueModule /
    CCItemValueModule / CCBooleanValueModule / CCQuestValueModule), subAttributes}]}:
      jump      map {x, y}                   haritaya ışınlan
      kill      range N | viewport | target | unselected | almost | me     uzaylıları öldür (ödülleriyle), canı 1'e indir, kendini
      quest     accept|finish|fail|cancel <id>, finishAll
      book      item {amount, level, overheatPetGear} | package {amount}     eşya ya da paket ver
      spawn     npcType {amount}             uzaylı doğur (istemcinin game.xml npcId'si: spawn_type)
      box       spawn {boxType, amount}      kutu bırak; collect {boxType, amount}: en yakın kutuları topla
      god       aç/kapa dokunulmazlık
      cooldown  resetAll                     yetenek ve eşya beklemeleri sıfır
      pet       petLevel/lv                  P.E.T. seviyesi
      galaxyGates bookGGReward <ad> | setup <ad> {lifes, wave, lastWave}
      addEternalBlacklightPoints <n>         EBL koşusuna puan
      battleStation                          Clan Battle Station (Ö5)
    Yanıt komutu yok (protokolde CCommand… yanıtı yok): sonuç ekrana yazılır.
  - Konsolun Ship Check, Switch Ship, Effects (efekt ve VisualModifier oynatma), Show Assets sayfaları sunucusuz.
Panelin "GM konsolu" ayarı (gm_konsol, geliştirici) açıkken dailyRank 6000 gider (rütbe simgesi boş görünebilir) ve komutlar çalışır.
"""
import json, math, os, random, time

import settings as SET
from legacy_protocol import legacy

REQUESTS = ('CCInitRequest', 'CCommandRequest')
ADMIN_RANK = 6000
GM_NPC = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'gm_npc.json'), encoding='utf8'))['npc']
DERIVED = ('gg_', 'etk_', 'pm_', 'apo_', 'deney_')      # kapı, etkinlik, mod kopyaları: aynı npc_kimlik'te asıl tür önce
STAND_IN = '79'                                          # sunucuda karşılığı olmayan NPC'nin değerleri (Kristallon)


def enabled(profile=None):
    """Arkadaş sunucusunda yalnız sunucunun oyuncusu (misafire sunucunun ayarı açık olsa da kapalı)."""
    return bool(SET.get('gm_konsol')) and getattr(profile, 'guest', None) is None


def mod(_cls, **f):
    f['_'] = _cls                 # 'name' modüllerin kendi alanı
    return f


def values(attrs):
    """CCRequestAttributeModule listesi -> [(ad, değer, alt öğeler)] (değer modülünün türüne göre int / str / bool / lootId)."""
    out = []
    for a in attrs or []:
        v = a.get('value') or {}
        val = next((v[k] for k in ('value', 'lootId', 'cdCom') if k in v), None)
        out.append((a.get('name') or '', val, values(a.get('subAttributes'))))
    return out


def flat(attrs):
    """Bütün öğeler tek sözlükte: ad -> değer (ilk görülen)."""
    d = {}
    for name, val, sub in values(attrs):
        d.setdefault(name, val)
        for k, v in flat_items(sub):
            d.setdefault(k, v)
    return d


def flat_items(rows):
    for name, val, sub in rows:
        yield name, val
        yield from flat_items(sub)


def num(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def world_types():
    import world
    return world.CFG['tipler']


def _plain(s):
    return ''.join(c for c in str(s or '').lower() if c.isalnum())


def spawn_type(want):
    """Spawn sayfasının npcId'si -> (tür, model, ad). İstemci game.xml'deki npcId'yi gönderir (data/gm_npc.json); tür anahtarları
    (Battleray '115') başka NPC'lerin kimlikleriyle çakıştığı için önce npc_kimlik (oyuncu bildirimi 2026-10-30: Emperor Kristallon
    115 -> Battleray, Ufo 25 -> Boss Saimon). Sunucuda kimliği olmayan: gemi türü bir tür anahtarıysa o, adı bir türünkiyle aynıysa o,
    yoksa yedek türün değerleriyle istemcinin modeli ve adı (model, ad dolu)."""
    T = world_types()
    same = [k for k, v in T.items() if str(v.get('npc_kimlik')) == want and not k.startswith(('eg_', 'kp_'))]
    if same:
        return min(same, key=lambda k: (not k.isdigit(), k.startswith(DERIVED))), None, None
    kind, name = GM_NPC.get(want) or (None, None)
    if not name:
        return (want, None, None) if want in T else (None, None, None)
    alike = next((k for k, v in T.items() if _plain(v.get('ad')) == _plain(name) and not k.startswith(('eg_', 'kp_'))), None)
    if alike:
        return alike, None, None
    name = name if name.startswith(('-=', '..', '(', '\\', '<')) else '-=[ %s ]=-' % name
    if kind in T:                            # aynı modelin başka adlı tasarımı (Boss Kucurbium: UberLordakium'un modeli)
        return kind, None, name
    return STAND_IN, kind, name


class Console:
    """Oturumun GM konsolu (game.Session bağlar: s)."""

    def __init__(self, session, log=print):
        self.s, self.log = session, log

    @property
    def w(self):
        return self.s.world

    def say(self, text):
        from galaxy_gates import screen
        self.log('   GM: %s' % text)
        return [screen('GM: ' + text)]

    def handle(self, name, f):
        if not enabled(self.s.profile):
            self.log('   GM konsolu kapalı (panel: Geliştirici > GM konsolu): %s' % name)
            return []
        if name == 'CCInitRequest':
            return [self.init_cmd()]
        cmd = (f.get('name') or '').strip()
        fn = getattr(self, 'cmd_' + cmd, None)
        if not fn:
            return self.say('bilinmeyen komut %s' % cmd)
        try:
            return fn(values(f.get('attributes')), flat(f.get('attributes')))
        except Exception as e:                      # konsol oyunu düşürmesin
            import traceback
            self.log(traceback.format_exc())
            return self.say('%s hatası: %s' % (cmd, e))

    # ------------------------------------------------------------ açılış listeleri
    def init_cmd(self):
        import world
        import loot as LOOT
        import quest as QU
        boxes = ['BONUS_BOX'] + sorted(LOOT.BOXES) + sorted({k for k in world.CFG.get('kutu_turleri', [])})
        box_list = mod('CCListRangeModule', valueList=[mod('CCStringValueModule', name=b, value=b) for b in dict.fromkeys(boxes)])
        quest_list = mod('CCListRangeModule', valueList=[mod('CCQuestValueModule', name='%d %s' % (q, d['ad']), value=q)
                                                         for q, d in sorted(QU.QUESTS.items())])
        attr = lambda name, rng=None, sub=(): mod('CCAttributeModule', name=name, subAttributes=list(sub), singleAttributeSelection=True,
                                                   range=rng or mod('CCAbstractRangeModule'), toolTip='')
        box = mod('CCommandModule', name='box', toolTip='', singleAttributeSelection=True,
                  args=[attr(a, sub=[attr('boxType', box_list), attr('amount', mod('CCNumericRangeModule', min=1, max=100))])
                        for a in ('spawn', 'collect')])
        quest = mod('CCommandModule', name='quest', toolTip='', singleAttributeSelection=True,
                    args=[attr('accept', quest_list), attr('finish', quest_list), attr('fail', quest_list), attr('finishAll')])
        return 'CCInitCommand', {'commands': [box, quest]}

    # ------------------------------------------------------------ komutlar
    def cmd_jump(self, rows, d):
        import map_links as H
        dest = num(d.get('map'))
        if dest not in H.NAMES and not H.client_map_name(dest):
            return self.say('harita %s yok' % d.get('map'))
        x, y = num(d.get('x')), num(d.get('y'))
        if not x and not y:
            pos = None
        else:
            w, h = H.map_size(dest)
            pos = (max(0, min(w, x)), max(0, min(h, y)))
        self.log('   GM: ışınlanma %s %s' % (dest, pos))
        self.s.change_map(dest, None, pos=pos)
        return []

    def cmd_kill(self, rows, d):
        """Konsolun kill sayfası (istemci "seçenek[,değer]" gönderir): range N (menzildeki uzaylılar), viewport (ekrandakiler), target
        (seçili), unselected (seçili dışında ekrandakiler), almost (seçili ya da ekrandakilerin canı 1, kalkanı 0), me (oyuncunun gemisi)."""
        w = self.w
        if not w:
            return []
        name, val = (rows[0][0].lower(), rows[0][1]) if rows else ('range', 1000)
        now = time.time()
        with w.lock:
            alive = [n for n in list(w.npcs.values()) if n.alive]
            seen = [n for n in alive if n.id in w.visible]
            if name == 'me':
                if w.hero_dead:
                    return self.say('gemi zaten yok edilmiş')
                msgs = []
                w.p.set_hull(hp=0, shield=0)
                w.hero_death(msgs)
                return msgs + self.say('gemin yok edildi')
            if name == 'target':
                near = [n for n in alive if n.id == w.target]
            elif name == 'unselected':
                near = [n for n in seen if n.id != w.target]
            elif name == 'viewport':
                near = seen
            elif name == 'almost':
                near = [n for n in alive if n.id == w.target] or seen
                msgs = []
                for n in near:
                    n.hp, n.shield = 1, 0
                    if n.id == w.target:
                        msgs.append(w.selection(n))
                return msgs + self.say('%d uzaylının canı 1' % len(near))
            else:
                rng = num(val, 1000)
                hx, hy = w.hero_pos(now)
                near = [n for n in alive if math.hypot(n.mover.pos(now)[0] - hx, n.mover.pos(now)[1] - hy) <= rng]
            msgs = []
            for n in near:
                msgs += w.kill(n)
        return msgs + self.say('%d uzaylı öldürüldü (%s)' % (len(near), name if name != 'range' else 'menzil %s' % val))

    def cmd_quest(self, rows, d):
        import quest as QU
        quests = self.s.quest
        msgs = []
        for name, val, sub in rows:
            name = name.lower()                     # istemcinin sayfası: Accept, Finish, FinishAll, Fail
            if name == 'finishall':
                done = [int(q) for q in list(quests.st['aktif'])]
                for q in done:
                    msgs += quests.complete(q)
                return msgs + self.say('%d görev bitirildi' % len(done))
            q = num(val)
            if q not in QU.QUESTS:
                return self.say('görev yok: %s' % val)
            if name == 'accept':
                return quests.accept(q) + self.say('görev alındı: %d' % q)
            if name == 'finish':
                if str(q) not in quests.st['aktif']:
                    msgs += quests.accept(q)
                return msgs + quests.complete(q) + self.say('görev bitti: %d' % q)
            if name == 'fail':
                return quests.fail(q, 'GM') + self.say('görev başarısız: %d' % q)
            if name == 'cancel':
                return quests.cancel(q) + self.say('görev iptal: %d' % q)
        return self.say('görev komutu anlaşılmadı')

    def cmd_book(self, rows, d):
        m = self.s.shop
        if d.get('package'):
            loot, n = d['package'], max(1, num(d.get('amount'), 1))
            grants = m.contents(loot, n) or []
            msgs = []
            for g, k in grants:
                msgs += m.reward(g, k)
            return msgs + m.money_msgs() + self.say('paket %s x%d (%d eşya)' % (loot, n, len(grants)))
        loot, n = d.get('item'), max(1, num(d.get('amount'), 1))
        if not loot:
            return self.say('eşya yok')
        msgs = m.reward(loot, n)
        lv = num(d.get('level'))
        if lv > 1:
            self.log('   GM: seviye %d istendi (yükseltme Assembly\'de)' % lv)
        return msgs + m.money_msgs() + self.say('%s x%d' % (loot, n))

    def cmd_spawn(self, rows, d):
        w = self.w
        if not w:
            return []
        want = str(d.get('npcType') or '')
        tip, model, name = spawn_type(want)
        if not tip:
            return self.say('uzaylı türü yok: %s' % want)
        n = max(1, min(50, num(d.get('amount'), 1)))
        prep = (lambda x: setattr(x, 'd', dict(x.d, ad=name))) if name else None
        now = time.time()
        with w.lock:
            hx, hy = w.hero_pos(now)
            for k in range(n):
                a = 2 * math.pi * k / n
                w.spawn_npc_at(tip, hx + math.cos(a) * 600, hy + math.sin(a) * 600, model=model, prep=prep)
        return self.say('%s x%d' % (name or world_types()[tip]['ad'], n))

    def cmd_box(self, rows, d):
        import world
        w = self.w
        if not w:
            return []
        kind, n = d.get('boxType') or 'BONUS_BOX', max(1, min(50, num(d.get('amount'), 1)))
        now = time.time()
        if any(name == 'collect' for name, _, _ in rows):
            # Collect düğmesi (istemci GmComponentSystem.SendCollectBox: 'collect' {boxType, amount}): en yakın kutuları toplar
            # (oyuncu bildirimi 2026-10-30: Spawn gibi kutu bırakıyordu)
            with w.lock:
                hx, hy = w.hero_pos(now)
                near = sorted((math.hypot(b['x'] - hx, b['y'] - hy), h) for h, b in w.boxes.items() if b['tip'] == kind and w.own(b))
                got = sum(1 for _, h in near[:n] if w.take_box(h) is not False)
            return self.say('%s toplandı: %d' % (kind, got))
        with w.lock:
            hx, hy = w.hero_pos(now)
            for k in range(n):
                x, y = hx + random.randint(-400, 400), hy + random.randint(-400, 400)
                content = random.choice(world.CFG['bonus_kutu']) if kind == 'BONUS_BOX' else None
                w.drop_box(kind, x, y, content, None)
        return self.say('%s x%d' % (kind, n))

    def cmd_god(self, rows, d):
        w = self.w
        if not w:
            return []
        w.invulnerable = not w._invulnerable
        return self.say('dokunulmazlık %s' % ('açık' if w._invulnerable else 'kapalı'))

    def cmd_cooldown(self, rows, d):
        import ship_ability as SA
        import combat_items as CIT
        p, now = self.s.shop.p, time.time()
        with p.lock:
            p.d[CIT.TIMERS] = {}
            for st in SA.state(p).values():
                if isinstance(st, dict):
                    st['hazir'] = 0
                    st['bitis'] = min(st.get('bitis', 0), now)
            p.dirty = True
        msgs = p.menu_changes()
        if self.w:
            self.w.rocket_ready = 0.0
            self.w.ammo_ready = {}
            msgs += [SA.timer_msg(p, i, now) for i in SA.ship_items(p)]
        return msgs + self.say('bekleme süreleri sıfırlandı')

    def cmd_pet(self, rows, d):
        import pet as PETM
        pet = self.s.pet
        if not pet.owned:
            return self.say('P.E.T. yok')
        lv = max(0, min(len(PETM.PET['seviyeler']) - 1, num(d.get('lv') or d.get('petLevel'))))
        with pet.p.lock:
            pet.d['seviye'] = lv
            pet.d['ep'] = PETM.PET['seviyeler'][lv]['ep']
            pet.p.dirty = True
        pet.p.ach('pet_level', deger=lv)
        return [('PetLevelUpdateCommand', dict(petLevel=lv, petExperiencePointsUntilNextLevel=pet.next_xp(), designId=pet.ship_type(),
                                               expansionStage=1)),
                ('PetExperiencePointsUpdateCommand', dict(currentExperiencePoints=pet.d['ep'], maxExperiencePoints=pet.next_xp()))] + \
            self.say('P.E.T. seviyesi %d' % lv)

    def cmd_galaxyGates(self, rows, d):
        import galaxy_gates as KAPI
        k = self.s.gates
        for name, val, sub in rows:
            if name == 'bookGGReward':
                key = str(val or '').strip().lower()
                if key not in KAPI.KAPI:
                    return self.say('kapı yok: %s' % val)
                w = self.w
                msgs, info = k.finish(key, w.reward_msgs if w else None)
                return msgs + self.say('%s ödülü verildi' % KAPI.KAPI[key]['ad'])
            if name in ('setup', 'galaxyGates'):
                parts = [x.strip() for x in str(val or '').split(',')]
                key = parts[0].lower() if parts and parts[0] else ''
                if key not in KAPI.KAPI:
                    return self.say('kapı yok: %s' % (parts[0] if parts else ''))
                flat = dict((n, v) for n, v in flat_items(sub))
                g = KAPI.KAPI[key]
                lifes = num(flat.get('lifes') or (parts[1] if len(parts) > 1 else 0)) or g['can']
                wave = num(flat.get('wave') or (parts[2] if len(parts) > 2 else 0))
                last = str(flat.get('lastWave') or (parts[3] if len(parts) > 3 else '')).lower() in ('true', '1')
                with k.p.lock:
                    G = k.gate(key)
                    G.update(hazir=True, can=lifes, alinan_can=0, parcalar=list(range(1, g['parca'] + 1)),
                             dalga=len(g['dalgalar']) - 1 if last else max(0, min(len(g['dalgalar']) - 1, wave - 1 if wave else 0)))
                    k.p.dirty = True
                return self.say('%s kuruldu: %d can, dalga %d (X-1 portalı)' % (g['ad'], lifes, G['dalga'] + 1))
        return self.say('kapı komutu anlaşılmadı')

    def cmd_addEternalBlacklightPoints(self, rows, d):
        n = next((num(v) for k, v in d.items() if num(v)), 0)
        ebl = self.s.pve.ebl if self.s.pve else None
        if not ebl or not getattr(ebl, 'run', None):
            return self.say('EBL koşusu yok')
        with ebl.p.lock:
            ebl.run['puan'] = ebl.run.get('puan', 0) + n
            ebl.p.dirty = True
        return self.say('EBL puanı +%d (%d)' % (n, ebl.run['puan']))

    def cmd_battleStation(self, rows, d):
        cbs = getattr(self.s, 'cbs', None)
        if cbs and hasattr(cbs, 'gm'):
            return cbs.gm(rows, d)
        return self.say('Clan Battle Station sunucuda henüz yok')
