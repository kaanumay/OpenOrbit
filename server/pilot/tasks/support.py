"""Combat support, alongside whatever the bot is doing:
  - item rules (pilot.json support.rules): an ability or technology fired when its condition holds (HP / shield below a share, while
    fighting, against a big alien, or as soon as it is ready);
  - config switch (config_switch): when the shield runs low, the other config if the shield it kept is fuller;
  - P.E.T. (pet): launched with the chosen gear, another gear below a share of HP, repaired when destroyed (within a uridium limit)."""
from .. import brain as B

CHECK_SEC = 0.5
CONFIG_SEC = 15.0             # at most one config switch every 15 s (the game's own wait is 5 s)
PET_SEC = 2.0
PET_FAIL_SEC = 10.0


def run(pilot, s, now):
    if now - pilot.support_at < CHECK_SEC:
        return
    pilot.support_at = now
    rules(pilot, s, now)
    config(pilot, s, now)
    pet(pilot, s, now)


def shield_pct(s):
    return 100.0 * s['shield'] / s['shield_max'] if s['shield_max'] else 100.0


def holds(rule, pilot, s):
    w, v = rule['when'], rule['value']
    fighting = pilot.target is not None
    if w == 'hp':
        return B.hp_pct(s) < v
    if w == 'shield':
        return shield_pct(s) < v
    if w == 'fight':
        return fighting
    if w == 'big':
        t = pilot.view.get('target')
        return fighting and bool(t) and t['hp_max'] >= v
    return w == 'always'


def rules(pilot, s, now):
    for r in pilot.cfg['support']['rules']:
        if holds(r, pilot, s) and pilot.act.use_item(r['item'], now):
            pilot.note('Used {0}.', r['item'])


def config(pilot, s, now):
    c, act = pilot.cfg['config_switch'], pilot.act
    if not c['enabled'] or now - pilot.config_at < CONFIG_SEC or shield_pct(s) >= c['shield_pct']:
        return
    other = 2 if act.active_config() == 1 else 1
    if act.saved_shield(other) <= s['shield'] * 1.2 + 1000:
        return
    pilot.config_at = now
    if act.switch_config(other):
        pilot.note('Shield low: switched to config {0}.', other)


def pet(pilot, s, now):
    c, act = pilot.cfg['pet'], pilot.act
    if not c['enabled'] or now < pilot.pet_at:
        return
    pilot.pet_at = now + PET_SEC
    st = act.pet_state()
    if st is None:
        return
    if st['destroyed']:
        if c['repair'] and st['repair_cost'] <= c['repair_max']:
            cost = act.pet_repair()
            if cost is None:
                pilot.pet_at = now + PET_FAIL_SEC
            else:
                pilot.stats.add('spent_uridium', cost)
                pilot.note('P.E.T. repaired ({0} U).', cost)
        return
    if not st['active']:
        if st['relaunch'] or st['fuel'] <= 0:
            return
        if act.pet_launch(c['gear']):
            pilot.note('P.E.T. launched.')
        else:
            pilot.pet_at = now + PET_FAIL_SEC
        return
    want = c['low_hp_gear'] if c['low_hp_gear'] and B.hp_pct(s) < c['low_hp_pct'] else c['gear']
    if st['gear'] != want and not act.pet_gear(want):
        pilot.pet_at = now + PET_FAIL_SEC
