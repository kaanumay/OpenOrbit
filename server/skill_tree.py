"""Pilot yetenek ağacı (profilde "yetenekler"; veri data/skills.json ← istemcinin skilltree.xml'i ve wiki).

İstemci (protokol; kayıtta SkillTreeListRequest'e yanıt yok, seviye 1 oyuncu): SkillTreeListRequest -> SkillTreeListCommand {resetPrice,
list: [SkillTreeInfoCommand {id, curLevel}], researchPoints, resetCount, logFiles, required}; ConvertResearchPointsRequest ->
ConvertResearchPointsCommand {required, success, researchPoints, logfiles}; UpLevelSkillTreeRequest {id} -> UpLevelSkillTreeCommand
{id, researchPoints, stack, success, curLevel}; ResetSkillTreeRequest -> ResetSkillTreeCommand.
Kurallar: log diskleri pilot puanına çevrilir (wiki: 1. puan 30, 2. 33 … log diski); her seviye 1 puan + kredi + Seprom (kademe 1:
yalnız kredi; Seprom kargodan, yetmeyeni Skylab deposundan); ön koşullar istemcinin ağacındaki gibi. Sıfırlama puanları geri verir (kredi ve Seprom dönmez), ücreti uridyum,
her seferinde iki katı (wiki: 1.000, 2.000 …). Log diskleri Galaksi Kapısı üreticisinin sayacında (kapilar.log_disk).
"""
import json, os
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
Y = json.load(open(os.path.join(HERE, 'data', 'skills.json'), encoding='utf8'))
SKILLS = Y['skills']
SEPROM = 7                       # cevher türü
SKYLAB_SEPROM = '14'             # Skylab deposundaki kimliği (skylab.json cevherler)


def mod(name, **f):
    f['_'] = name
    return f


def state(p):
    return p.d.setdefault('skills', {'seviye': {}, 'puan': 0, 'converted': 0, 'resets': 0})


def level(p, sid):
    return state(p)['seviye'].get(sid, 0)


def maxed(p, sid):
    """Yetenek son seviyesinde mi (istemcinin son seviye görselleri: kalın lazer, roket izi, kalkan; dunya.skilled_laser, rocket_look, skill_shield; roketin güdümü ilk puandan başlar)."""
    return level(p, sid) >= len(SKILLS[sid]['values'])


def shield_cmd(p):
    """Kalkanın görünümü (AttributeSkillShieldUpdateCommand; istemci ShieldEffect: shieldSkillId 1 shield1_2D, 2 shield2_2D, 0 yok):
    resmî SSS'ye göre Shield Engineering (17) son seviyesinde baloncuk, Shield Mechanics (8) son seviyesinde beyaz kalkan. Girişte,
    config değişince ve yetenek değişince gider (kayıttaki yeteneksiz hesapta hep 0)."""
    sid = 2 if maxed(p, '8') else 1 if maxed(p, '17') else 0
    return ('AttributeSkillShieldUpdateCommand', {'shieldSkillId': sid, 'minSkinShieldTwinkle': 10, 'maxSkinShieldTwinkle': 100})


def mods(p):
    """Yeteneklerin bonusları (profil.mods'a eklenir): yüzdeler oran, Ship Hull mutlak can. II basamağı I'in devamı (skilltree
    successor; değerler kesintisiz: Ship Hull 5.000, 10.000 → 15.000, 25.000, 50.000): II açıksa I sayılmaz."""
    out = {}
    for sid, lv in state(p)['seviye'].items():
        s = SKILLS.get(sid)
        if not s or not lv or not s['effect'] or (sid.endswith('a') and level(p, sid[:-1] + 'b')):
            continue
        v = s['values'][lv - 1]
        out[s['effect']] = out.get(s['effect'], 0) + (v if s['unit'] == 'absolute' else v / 100.0)
    return out


def requirements_met(p, sid):
    for r in SKILLS[sid]['prerequisite']:
        pts = [level(p, x) for x in r['skills']]
        if (sum(pts) if r['tur'] == 'toplam' else min(pts)) < r['puan']:
            return False
    return True


class Abilities:
    def __init__(self, profile, shop, gates, log=print):
        self.p, self.m, self.k, self.log = profile, shop, gates, log

    def logs(self):
        return self.k.d['log_disk']

    def required(self):
        tbl = Y['log_disk']
        n = state(self.p)['converted']
        return tbl[n] if n < len(tbl) else -1

    def reset_price(self):
        tbl, n = Y['resets'], state(self.p)['resets']
        return tbl[n] if n < len(tbl) else tbl[-1] * 2 ** (n - len(tbl) + 1)

    def info_list(self):
        return [mod('SkillTreeInfoCommand', id=sid, curLevel=level(self.p, sid)) for sid in SKILLS]

    def list_cmd(self):
        st = state(self.p)
        return ('SkillTreeListCommand', dict(resetPrice=self.reset_price(), list=self.info_list(), researchPoints=st['puan'],
                                             resetCount=st['resets'], logFiles=self.logs(), required=self.required()))

    def convert(self):
        """ConvertResearchPointsRequest: yeterli log diski varsa bir pilot puanı."""
        need = self.required()
        st = state(self.p)
        ok = 0 < need <= self.logs()
        if ok:
            with self.p.lock:
                self.k.d['log_disk'] -= need
                st['puan'] += 1
                st['converted'] += 1
                self.p.dirty = True
            self.log('   pilot puanı: %d log diski -> 1 puan (kalan puan %d)' % (need, st['puan']))
        return [('ConvertResearchPointsCommand', dict(required=self.required(), success=ok, researchPoints=st['puan'],
                                                      logfiles=self.logs()))]

    def skylab_seprom(self):
        """Skylab deposundaki Seprom (Skylab cevheri 14)."""
        return int((self.p.d.get('skylab') or {}).get('storage', {}).get(SKYLAB_SEPROM, 0))

    def seprom(self):
        """Harcanabilir Seprom: kargodaki ve Skylab deposundaki (resmî forum: yetenek ağacı Skylab'dakini kullanır; kullanıcı isteği
        2026-10-25: yalnız kargodaki sayılıyordu)."""
        return self.p.ore_count(SEPROM) + self.skylab_seprom()

    def up_level(self, f):
        """UpLevelSkillTreeRequest {id}: puan, kredi ve Seprom (önce kargodan, kalanı Skylab'dan) harcanır; ön koşullar istemcinin
        ağacındaki gibi. Yetmeyen şeyin metni (kredi, Seprom, puan, ön koşul); önceden hepsinde "An error occurred" çıkıyordu
        (kullanıcı bildirimi 2026-10-25)."""
        sid = str(f.get('id') or '')
        st = state(self.p)
        s = SKILLS.get(sid)
        cur = level(self.p, sid)
        cost = s['cost'][cur] if s and cur < len(s['values']) else None
        why = ('yetenek yok' if not s else 'en üst seviye' if cost is None else 'ön koşul' if not requirements_met(self.p, sid)
               else 'puan yetmiyor' if st['puan'] < cost['puan'] else 'kredi yetmiyor' if self.p.d['pilot'].get('credits', 0) < cost['kredi']
               else 'Seprom yetmiyor' if self.seprom() < cost['seprom'] else None)
        if why:
            self.log('   yetenek %s yükselmedi: %s' % (sid, why))
            stack = {'ön koşul': lambda: self.m.reason('prerequisite'), 'puan yetmiyor': lambda: self.m.reason('research_points'),
                     'kredi yetmiyor': lambda: self.m.stack('not_enough_credits'),
                     'Seprom yetmiyor': lambda: self.m.stack('tf_message_not_enough_seprom')}.get(why, lambda: self.m.stack('eqt_error_generic'))
            return [('UpLevelSkillTreeCommand', dict(id=sid, researchPoints=st['puan'], stack=stack(), success=False, curLevel=cur))]
        with self.p.lock:
            st['puan'] -= cost['puan']
            self.p.d['pilot']['credits'] -= cost['kredi']
            st['seviye'][sid] = cur + 1
            self.p.dirty = True
        RT.money(self.p, 'kredi', -cost['kredi'], 'buy_SPECIAL')
        msgs = []
        cargo = min(cost['seprom'], self.p.ore_count(SEPROM))
        if cargo:
            totals = self.p.remove_ores({SEPROM: cargo})
            msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': totals}), self.m.ore_pack([SEPROM])]
        if cost['seprom'] > cargo:
            with self.p.lock:
                storage = self.p.d['skylab']['storage']
                storage[SKYLAB_SEPROM] = storage.get(SKYLAB_SEPROM, 0) - (cost['seprom'] - cargo)
                self.p.dirty = True
            self.log('   yetenek: %d Seprom Skylab deposundan' % (cost['seprom'] - cargo))
        self.log('   yetenek %s (%s) seviye %d (-%d kredi, -%d Seprom)' % (sid, s['ad'], cur + 1, cost['kredi'], cost['seprom']))
        return ([('UpLevelSkillTreeCommand', dict(id=sid, researchPoints=st['puan'], stack=None, success=True, curLevel=cur + 1))]
                + self.m.money_msgs() + msgs + self.m.apply_stats() + ([shield_cmd(self.p)] if sid in ('8', '17') else []))

    def reset(self):
        """ResetSkillTreeRequest: bütün seviyeler sıfırlanır, harcanan puanlar geri gelir; ücret uridyum, her seferinde iki katı."""
        st = state(self.p)
        price = self.reset_price()
        spent = sum(sum(c['puan'] for c in SKILLS[s]['cost'][:lv]) for s, lv in st['seviye'].items() if s in SKILLS)
        ok = spent > 0 and self.p.d['pilot'].get('uridium', 0) >= price
        if ok:
            with self.p.lock:
                self.p.d['pilot']['uridium'] -= price
                st['seviye'] = {}
                st['puan'] += spent
                st['resets'] += 1
                self.p.dirty = True
            RT.money(self.p, 'uridyum', -price, 'buy_SPECIAL')
            self.log('   yetenekler sıfırlandı: %d puan geri, -%d U' % (spent, price))
        msgs = [('ResetSkillTreeCommand', dict(resetPrice=self.reset_price(), stack=None if ok else self.m.stack('eqt_error_generic'),
                                               list=self.info_list(), logFiles=self.logs(), researchPoints=st['puan'],
                                               resetCount=st['resets'], success=ok))]
        return msgs + (self.m.money_msgs() + self.m.apply_stats() + [shield_cmd(self.p)] if ok else [])
