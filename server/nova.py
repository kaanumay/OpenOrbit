"""N.O.V.A. kaptanları (yol haritası Aşama 9; veri data/new_systems.json 'nova' <- tools/new_systems.py, kaynak darkorbitwiki).

İstemcinin N.O.V.A. penceresi (UINovaSystem; istekler istemcinin kodundan): CaptainActionRequest {command, captainId, perkId,
upgradeLevel}
  getRosterList          -> CaptainRosterListCommand {captainList: [CaptainCommand]}
  getResources           -> CaptainGetResourcesBackCommand {lootId: Evocation Chip, amount}
  updateActiveCaptain    {captainId} -> CaptainUpdateActiveBackCommand {result, captainId, errorId}; yalnız istasyonda ("You can
                         only change your N.O.V.A. at the station."). Aç-kapa: istemcinin EQUIP ve UNEQUIP düğmeleri aynı isteği
                         (seçili N.O.V.A.'nın kimliğiyle) gönderir, başarı yanıtında da aynı kimlik takılıysa çıkarılmış sayılır
                         (CaptainData.UpdateEquipRosterData); istemci başarıda listeyi yeniden ister
  dismissCaptain         {captainId} -> CaptainDismissBackCommand {result, captainId, errorId}: 50 Evocation Chip; takılıyken olmaz
  upgradePerk            {captainId, perkId, upgradeLevel (hedef + 1)} -> CaptainUpgradPerkBackCommand {result, captainId, perkId, level,
                         errorId}
                         (uridyum + Evocation Chip; U.P.S. bölümlerinde Calling Chip de)
CaptainCommand: captainName (ilk ad) ve captainTypeId (aile; istemci adın arkasına 'captain_<aile>_lastname' çevirisini ekler),
perkList (CaptainPerkCommand: perkTypeId 'perk_<yetenek>' -> 'captain_perk_<yetenek>_fullname', perkModifier yüzde, perkDrain
enerji/sn, upgradLevelList seviye başına değer ve bedel), captainEnergy/maxEnergy, sellingPrice (bırakınca çip).

Kurallar (wiki): mağazada 100.000 U (Neo ya da Eos bölümünden rastgele), en çok 30 (fazlası 10.000 U), iki rastgele yetenek, taban
değer BASE I-VI, seviye 5'e dek yükseltme. Takılı N.O.V.A. saniyede yeteneklerinin harcamalarının toplamı kadar enerji harcar;
enerji harcamadan azsa yetenekler çalışmaz. Dinlenen (takılı olmayan) N.O.V.A. saniyede 10 dolar. Galaksi Kapısı yetenekleri yalnız
kapı haritalarında (A/B/G olanlar Alpha, Beta, Gamma'da).
Profilde: nova {kadro: [{id, bolum, aile, ad, enerji, t, yetenekler: [{id, tur, taban, seviye}]}], aktif, sonraki}.
"""
import json, os, random, threading, time

import inventory as INV
import galaxy_gates as KAPI
from legacy_protocol import stm

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'new_systems.json'), encoding='utf8'))['nova']
PERKS = D['skills']
CHIP, CALLING = D['chip'], D['calling_chip']
MAX_E, REGEN = D['max_energy'], D['rest_sec']
REQUESTS = {'CaptainActionRequest'}


def mod(_cls, **f):
    f['_'] = _cls
    return f


def value(kind, base, level):
    """Yeteneğin değeri (%): taban kademe + seviye başına artış."""
    t = PERKS[kind]
    return round(t['base'][base - 1] + t['increase'] * (level - 1), 2)


def where(map_id):
    """Haritanın yeteneklerdeki yeri: 'abg' (Alpha/Beta/Gamma), 'kapi' (öteki kapılar) ya da None."""
    g = KAPI.BY_MAP.get(int(map_id or 0))
    return None if not g else 'abg' if g in ('alpha', 'beta', 'gamma') else 'kapi'


class Nova:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                              # mağaza (para göstergesi); oturum bağlar
        self.at_station = lambda: True             # oturum bağlar: oyuncu istasyonda mı
        self.lock = threading.RLock()              # enerji: profil.mods() profilin kilidi tutulurken de çağrılır (o kilit yeniden girilmez)
        with profile.lock:
            self.d = profile.d.setdefault('nova', {'roster': [], 'active': 0, 'next': 1})
        self.resume()

    # ------------------------------------------------------------ enerji
    def resume(self, now=None):
        """Oturum açıldı: takılı N.O.V.A. çevrimdışı sürede harcamaz (uyarlama); dinlenenler o sürede doldu."""
        c = self.active()
        if c:
            c['t'] = now or time.time()

    def drain(self, c):
        return sum(PERKS[y['tur']]['spending'] for y in c['skills'])

    def update(self, c, now=None):
        now = now or time.time()
        dt = max(0.0, now - c.get('t', now))
        if c['id'] == self.d['active']:
            c['energy'] = max(0.0, c['energy'] - self.drain(c) * dt)
        else:
            c['energy'] = min(float(MAX_E), c['energy'] + REGEN * dt)
        c['t'] = now
        self.p.dirty = True
        return c['energy']

    def find(self, cid):
        return next((c for c in self.d['roster'] if c['id'] == int(cid or 0)), None)

    def active(self):
        return self.find(self.d['active']) if self.d['active'] else None

    def working(self, now=None):
        """Yetenekleri çalışan N.O.V.A. (takılı ve enerjisi harcamasından çok) ya da None."""
        c = self.active()
        if not c:
            return None
        with self.lock:
            e = self.update(c, now)
        return c if e > self.drain(c) else None

    def mods(self, map_id):
        """Takılı N.O.V.A.'nın yetenekleri -> profilin bonus anahtarları (kesir); kapı yetenekleri yalnız kendi haritalarında."""
        c = self.working()
        if not c:
            return {}
        here, out = where(map_id), {}
        for y in c['skills']:
            key, place = D['effects'].get(y['tur'], (None, None))
            if key and (place == 'hepsi' or place == here or (place == 'kapi' and here == 'abg')):
                out[key] = out.get(key, 0) + value(y['tur'], y['base'], y['seviye']) / 100.0
        return out

    def hud(self):
        """Göstergedeki enerji (ShipInitializationCommand captainEnergy/maxCaptainEnergy): takılı N.O.V.A.'nınki, yoksa 0."""
        c = self.active()
        if not c:
            return {'captainEnergy': 0, 'maxCaptainEnergy': 0}
        with self.lock:
            e = self.update(c)
        return {'captainEnergy': int(e), 'maxCaptainEnergy': MAX_E}

    def energy_cmd(self):
        """EnergyUpdateCommand: göstergedeki N.O.V.A. enerjisi ve saniyelik harcaması."""
        c, h = self.active(), self.hud()
        return 'EnergyUpdateCommand', dict(maxCaptainEnergy=h['maxCaptainEnergy'], captainEnergyDrain=self.drain(c) if c else 0,
                                           currentCaptainEnergy=h['captainEnergy'])

    # ------------------------------------------------------------ edinme
    def new_captain(self, section, rng=random):
        info = D['sections'][section]
        pool = dict(info['skills'])
        perks = [rng.choices(list(pool), list(pool.values()))[0]]
        rest = {k: v for k, v in (pool if len(pool) > 1 else D['sections']['captain_captain-gen1-neo']['skills']).items()
                if k not in perks}
        while len(perks) < D['perk_count'] and rest:
            k = rng.choices(list(rest), list(rest.values()))[0]
            perks.append(k)
            rest.pop(k)
        with self.p.lock:
            cid = self.d['next']
            self.d['next'] = cid + 1
            c = {'id': cid, 'section': section, 'family': rng.choice(info['families']), 'ad': rng.choice(D['adlar']), 'energy': float(MAX_E),
                 't': time.time(), 'skills': []}
            for i, k in enumerate(perks):
                tier = rng.choices(range(1, 7), D['base_weight'])[0]
                c['skills'].append({'id': cid * 10 + i + 1, 'tur': k, 'base': tier, 'seviye': 1})
            self.d['roster'].append(c)
            self.p.dirty = True
        return c

    def hire(self, loot, n=1, rng=random):
        """Mağaza, Assembly, Battle Pass: captain_captain-generic (Neo ya da Eos) ya da bölümün kendisi. Kadro doluysa 10.000 U."""
        msgs, extra = [], 0
        for _ in range(n):
            section = loot
            if loot in D['genel']:
                w = D['genel'][loot]
                section = rng.choices(list(w), list(w.values()))[0]
            if section not in D['sections']:
                self.log('   N.O.V.A.: bilinmeyen bölüm %s' % loot)
                continue
            if len(self.d['roster']) >= D['max_roster']:
                extra += D['excess_uridium']
                continue
            c = self.new_captain(section, rng)
            self.log('   N.O.V.A. alındı: %s %s (%s; %s)' % (c['ad'], c['family'], section, ', '.join(
                '%s %.1f%%' % (y['tur'], value(y['tur'], y['base'], 1)) for y in c['skills'])))
            msgs.append(stm('captain_received_s'))         # "Recruited: N.O.V.A." (flashres'te yok: CSTM; canlı test H64)
        if extra:
            self.p.gain(uridyum=extra, neden='aktion_system_back')
            self.log('   N.O.V.A. kadrosu dolu: %d U' % extra)
            msgs += self.m.money_msgs() if self.m else []
        return msgs

    # ------------------------------------------------------------ pencere
    def costs(self, c, level):
        row = next((r for r in D['upgrade'] if r['seviye'] == level), None)
        if not row:
            return {}
        need = {'currency_uridium': row['uridyum'], CHIP: row['chip']}
        if D['sections'][c['section']].get('calling_chip'):
            need[CALLING] = row['calling_chip']
        return need

    def perk_cmd(self, c, y):
        # İstemci (CaptainPerkData, UINovaSystem.CreateCostTextItem): liste şimdiki seviyeden başlar (yükseltince baştan siler),
        # hedef T'nin bedeli listenin ilk T-şimdiki kaydının costList'lerinin toplamı (sırayla, aynı dizinle), satır sayısı hedef
        # kaydınkinden. Yani L kaydında L -> L+1 bedeli; en üst kayıtta türler için bir öncekinin bedeli. Önce 1'den başlayan liste
        # ve "L'ye ulaşma" bedeli gidiyordu: Total Cost boş kalıyordu (canlı test H66)
        levels, top = [], D['max_level']
        for lv in range(y['seviye'], top + 1):
            nxt = self.costs(c, lv + 1) if lv < top else self.costs(c, lv)
            cost = [mod('CaptainPerkUpgradLevelCostCommand', lootId=k, amount=v) for k, v in nxt.items()]
            levels.append(mod('CaptainPerkUpgradLevelCommand', modifier=float(value(y['tur'], y['base'], lv)), upgradeLevel=lv,
                              costList=cost))
        return mod('CaptainPerkCommand', perkModifier=float(value(y['tur'], y['base'], y['seviye'])), perkId=y['id'],
                   perkTypeId='perk_' + y['tur'], perkDrain=PERKS[y['tur']]['spending'], levelMax=D['max_level'],
                   upgradLevelList=levels, level=y['seviye'])

    def captain_cmd(self, c):
        with self.lock:
            e = self.update(c)
        return mod('CaptainCommand', sellingPrice=D['release_chip'], isSelected=c['id'] == self.d['active'], sellItemObtained=CHIP,
                   captainTypeId=c['family'], captainName=c['ad'], perkList=[self.perk_cmd(c, y) for y in c['skills']],
                   maxEnergy=MAX_E, captainId=c['id'], captainEnergy=int(e))

    def roster_cmd(self):
        return 'CaptainRosterListCommand', {'captainList': [self.captain_cmd(c) for c in self.d['roster']]}

    def chips_cmd(self):
        return 'CaptainGetResourcesBackCommand', {'amount': INV.count(self.p, CHIP), 'lootId': CHIP}

    def handle(self, f):
        from shop import stack_msg
        cmd, cid = f.get('command', ''), int(f.get('captainId') or 0)
        if cmd == 'getRosterList':
            return [self.roster_cmd()]
        if cmd == 'getResources':
            return [self.chips_cmd()]
        if cmd == 'updateActiveCaptain':
            err = None
            c = self.find(cid)
            if not self.at_station():
                err = 'captain_error_not_near_spacestation'
            elif cid and not c:
                err = 'captain_error_unhandled'
            if err:
                self.log('   N.O.V.A. değişmedi: %s' % err)
                return [('CaptainUpdateActiveBackCommand', dict(result=False, captainId=cid, errorId=stack_msg(err)))]
            with self.lock:
                old = self.active()
                if old:
                    self.update(old)                       # harcadığı enerji; bundan sonra dinlenir
                if c and old and old['id'] == c['id']:
                    c = None                               # takılı olanın kimliği geldi: UNEQUIP (canlı test H65; önce yine takıyordu)
                if c:
                    self.update(c)
                self.d['active'] = cid if c else 0
                self.p.dirty = True
            self.log('   N.O.V.A. %s' % ('takıldı: %s %s' % (c['ad'], c['family']) if c else 'çıkarıldı'))
            return [('CaptainUpdateActiveBackCommand', dict(result=True, captainId=cid, errorId=None)), self.energy_cmd()] + self.stats()
        if cmd == 'dismissCaptain':
            c = self.find(cid)
            err = 'captain_popup_dismiss_active_nova' if c and cid == self.d['active'] else None if c else 'captain_error_unhandled'
            if err:
                return [('CaptainDismissBackCommand', dict(errorId=stack_msg(err), result=False, captainId=cid))]
            with self.p.lock:
                self.d['roster'].remove(c)
                self.p.dirty = True
            self.p.add_resource(CHIP, D['release_chip'])
            self.log('   N.O.V.A. bırakıldı: %s %s (+%d Evocation Chip)' % (c['ad'], c['family'], D['release_chip']))
            return [('CaptainDismissBackCommand', dict(errorId=None, result=True, captainId=cid)), self.chips_cmd()]
        if cmd == 'upgradePerk':
            return self.upgrade(cid, int(f.get('perkId') or 0), int(f.get('upgradeLevel') or 0))
        self.log('   N.O.V.A.: bilinmeyen komut %r' % cmd)
        return []

    def upgrade(self, cid, pid, target):
        from shop import stack_msg
        c = self.find(cid)
        y = next((x for x in (c or {}).get('skills', []) if x['id'] == pid), None)
        back = lambda ok, err=None, lv=0: ('CaptainUpgradPerkBackCommand', dict(
            errorId=stack_msg(err) if err else None, level=lv, perkId=pid, captainId=cid, result=ok))
        if not y:
            return [back(False, 'captain_error_unhandled')]
        if y['seviye'] + 1 > D['max_level']:
            return [back(False, 'captain_hangar_error_perk_lvl_cap', y['seviye'])]
        # upgradeLevel istemcinin sayacı: açılışta seviye+1, her "+" bir artar ("-" azaltmaz; UINovaSystem.RefreshNotLevelInfo),
        # yani "+" ile seçilen hedef + 1. Hedef = upgradeLevel - 1 (en çok azami); şimdikinden büyük değilse bir seviye. Önce hep bir
        # seviye yapılıyordu, pencere ise seçilen hedefin toplam bedelini gösteriyordu (canlı test H67)
        nxt = max(y['seviye'] + 1, min(target - 1, D['max_level']))
        need = {}
        for lv in range(y['seviye'] + 1, nxt + 1):
            for k, v in self.costs(c, lv).items():
                need[k] = need.get(k, 0) + v
        if INV.spend(self.p, need, 'captain_perk_upgrade', y['tur']) is None:
            return [back(False, 'captain_hangar_error_not_enough_resources', y['seviye'])]
        with self.p.lock:
            y['seviye'] = nxt
            self.p.dirty = True
        self.log('   N.O.V.A. %s: %s seviye %d (%.1f%%)' % (c['ad'], y['tur'], nxt, value(y['tur'], y['base'], nxt)))
        return [back(True, None, nxt), self.chips_cmd()] + (self.m.money_msgs() if self.m else []) + self.stats()

    def stats(self):
        """Kargo, hız gibi değerler N.O.V.A. ile değişir: geminin değerleri yeniden (mağaza); oyuncu kutusundaki ipucu."""
        return (self.m.apply_stats() if self.m else []) + [self.perk_update_cmd()]

    def perk_update_cmd(self):
        """Oyuncu kutusundaki N.O.V.A. ipucu (Ö1): ActivePerkUpdateCommand {activePerkModuleList [ActivePerkModule {perkTypeId,
        modifierValue}]}; istemci her satırı ttip_captain_<perkTypeId>_description'dan %VALUE% ile kurar (ActivePerkUpdateCommandHandler;
        "evasion" geçenleri eksiye çevirir). Takılı N.O.V.A. yoksa boş liste."""
        c = self.active()
        rows = [mod('ActivePerkModule', perkTypeId='perk_' + y['tur'], modifierValue=float(value(y['tur'], y['base'], y['seviye'])))
                for y in (c['skills'] if c else [])]
        return 'ActivePerkUpdateCommand', {'activePerkModuleList': rows}
