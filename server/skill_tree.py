"""Pilot skill tree (in the profile "skills"; data data/skills.json <- the client's skilltree.xml and the wiki).

Client (protocol; the recording has no reply to SkillTreeListRequest, a level 1 player): SkillTreeListRequest -> SkillTreeListCommand {resetPrice,
list: [SkillTreeInfoCommand {id, curLevel}], researchPoints, resetCount, logFiles, required}; ConvertResearchPointsRequest ->
ConvertResearchPointsCommand {required, success, researchPoints, logfiles}; UpLevelSkillTreeRequest {id} -> UpLevelSkillTreeCommand
{id, researchPoints, stack, success, curLevel}; ResetSkillTreeRequest -> ResetSkillTreeCommand.
Rules: log disks are converted to pilot points (wiki: 1st point 30, 2nd 33 … log disks); each level costs 1 point + credits + Seprom (tier 1:
credits only; Seprom from cargo, any shortfall from the Skylab storage); prerequisites as in the client's tree. A reset gives the points back (credits and Seprom do not
return), its price is uridium, doubling each time (wiki: 1,000, 2,000 …). Log disks are in the Galaxy Gate generator's counter (kapilar.log_disk).
"""
import json, os
import ranks as RT

HERE = os.path.dirname(os.path.abspath(__file__))
Y = json.load(open(os.path.join(HERE, 'data', 'skills.json'), encoding='utf8'))
SKILLS = Y['skills']
SEPROM = 7                       # ore type
SKYLAB_SEPROM = '14'             # its id in the Skylab storage (skylab.json ores)


def mod(name, **f):
    f['_'] = name
    return f


def state(p):
    return p.d.setdefault('skills', {'level': {}, 'points': 0, 'converted': 0, 'resets': 0})


def level(p, sid):
    return state(p)['level'].get(sid, 0)


def maxed(p, sid):
    """Whether the skill is at its final level (the client's final-level visuals: thick laser, rocket trail, shield; world.skilled_laser, rocket_look, skill_shield; the rocket's homing starts from the first point)."""
    return level(p, sid) >= len(SKILLS[sid]['values'])


def shield_cmd(p):
    """The shield's look (AttributeSkillShieldUpdateCommand; client ShieldEffect: shieldSkillId 1 shield1_2D, 2 shield2_2D, 0 none):
    according to the official FAQ, a bubble at the final level of Shield Engineering (17), a white shield at the final level of Shield
    Mechanics (8). Sent on login, when config changes and when a skill changes (always 0 on an account without skills in the recording)."""
    sid = 2 if maxed(p, '8') else 1 if maxed(p, '17') else 0
    return ('AttributeSkillShieldUpdateCommand', {'shieldSkillId': sid, 'minSkinShieldTwinkle': 10, 'maxSkinShieldTwinkle': 100})


def mods(p):
    """The skills' bonuses (added to profile.mods): percentages are ratios, Ship Hull is absolute HP. Tier II continues tier I (skilltree
    successor; values are continuous: Ship Hull 5,000, 10,000 → 15,000, 25,000, 50,000): if II is open, I does not count."""
    out = {}
    for sid, lv in state(p)['level'].items():
        s = SKILLS.get(sid)
        if not s or not lv or not s['effect'] or (sid.endswith('a') and level(p, sid[:-1] + 'b')):
            continue
        v = s['values'][lv - 1]
        out[s['effect']] = out.get(s['effect'], 0) + (v if s['unit'] == 'absolute' else v / 100.0)
    return out


def requirements_met(p, sid):
    for r in SKILLS[sid]['prerequisite']:
        pts = [level(p, x) for x in r['skills']]
        if (sum(pts) if r['type'] == 'total' else min(pts)) < r['points']:
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
        return ('SkillTreeListCommand', dict(resetPrice=self.reset_price(), list=self.info_list(), researchPoints=st['points'],
                                             resetCount=st['resets'], logFiles=self.logs(), required=self.required()))

    def convert(self):
        """ConvertResearchPointsRequest: one pilot point if there are enough log disks."""
        need = self.required()
        st = state(self.p)
        ok = 0 < need <= self.logs()
        if ok:
            with self.p.lock:
                self.k.d['log_disk'] -= need
                st['points'] += 1
                st['converted'] += 1
                self.p.dirty = True
            self.log('   pilot point: %d log disks -> 1 point (points left %d)' % (need, st['points']))
        return [('ConvertResearchPointsCommand', dict(required=self.required(), success=ok, researchPoints=st['points'],
                                                      logfiles=self.logs()))]

    def skylab_seprom(self):
        """Seprom in the Skylab storage (Skylab ore 14)."""
        return int((self.p.d.get('skylab') or {}).get('storage', {}).get(SKYLAB_SEPROM, 0))

    def seprom(self):
        """Spendable Seprom: that in cargo and in the Skylab storage (official forum: the skill tree uses the Skylab one; user request
        2026-10-25: only the cargo was counted)."""
        return self.p.ore_count(SEPROM) + self.skylab_seprom()

    def up_level(self, f):
        """UpLevelSkillTreeRequest {id}: points, credits and Seprom are spent (cargo first, the rest from Skylab); prerequisites as in the client's
        tree. The text of whatever is lacking (credits, Seprom, points, prerequisite); before, all of them gave "An error occurred"
        (user report 2026-10-25)."""
        sid = str(f.get('id') or '')
        st = state(self.p)
        s = SKILLS.get(sid)
        cur = level(self.p, sid)
        cost = s['cost'][cur] if s and cur < len(s['values']) else None
        why = ('yetenek yok' if not s else 'en üst seviye' if cost is None else 'ön koşul' if not requirements_met(self.p, sid)
               else 'puan yetmiyor' if st['points'] < cost['points'] else 'kredi yetmiyor' if self.p.d['pilot'].get('credits', 0) < cost['credits']
               else 'Seprom yetmiyor' if self.seprom() < cost['seprom'] else None)
        if why:
            self.log('   skill %s did not level up: %s' % (sid, why))
            stack = {'ön koşul': lambda: self.m.reason('prerequisite'), 'puan yetmiyor': lambda: self.m.reason('research_points'),
                     'kredi yetmiyor': lambda: self.m.stack('not_enough_credits'),
                     'Seprom yetmiyor': lambda: self.m.stack('tf_message_not_enough_seprom')}.get(why, lambda: self.m.stack('eqt_error_generic'))
            return [('UpLevelSkillTreeCommand', dict(id=sid, researchPoints=st['points'], stack=stack(), success=False, curLevel=cur))]
        with self.p.lock:
            st['points'] -= cost['points']
            self.p.d['pilot']['credits'] -= cost['credits']
            st['level'][sid] = cur + 1
            self.p.dirty = True
        RT.money(self.p, 'credits', -cost['credits'], 'buy_SPECIAL')
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
            self.log('   skill: %d Seprom from the Skylab storage' % (cost['seprom'] - cargo))
        self.log('   skill %s (%s) level %d (-%d credits, -%d Seprom)' % (sid, s['name'], cur + 1, cost['credits'], cost['seprom']))
        return ([('UpLevelSkillTreeCommand', dict(id=sid, researchPoints=st['points'], stack=None, success=True, curLevel=cur + 1))]
                + self.m.money_msgs() + msgs + self.m.apply_stats() + ([shield_cmd(self.p)] if sid in ('8', '17') else []))

    def reset(self):
        """ResetSkillTreeRequest: all levels are reset, the spent points come back; the price is uridium, doubling each time."""
        st = state(self.p)
        price = self.reset_price()
        spent = sum(sum(c['points'] for c in SKILLS[s]['cost'][:lv]) for s, lv in st['level'].items() if s in SKILLS)
        ok = spent > 0 and self.p.d['pilot'].get('uridium', 0) >= price
        if ok:
            with self.p.lock:
                self.p.d['pilot']['uridium'] -= price
                st['level'] = {}
                st['points'] += spent
                st['resets'] += 1
                self.p.dirty = True
            RT.money(self.p, 'uridium', -price, 'buy_SPECIAL')
            self.log('   skills reset: %d points back, -%d U' % (spent, price))
        msgs = [('ResetSkillTreeCommand', dict(resetPrice=self.reset_price(), stack=None if ok else self.m.stack('eqt_error_generic'),
                                               list=self.info_list(), logFiles=self.logs(), researchPoints=st['points'],
                                               resetCount=st['resets'], success=ok))]
        return msgs + (self.m.money_msgs() + self.m.apply_stats() + [shield_cmd(self.p)] if ok else [])
