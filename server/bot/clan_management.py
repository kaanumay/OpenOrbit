"""Clan management (user request 2026-10-31): the bot clan leader (and officers with the right) runs the clan like a real leader.
All of it goes through the game's clan requests (clan.Clan.handle), everything a player can do from the clan window:
  ranks          3-4 ranks at founding (in the bot's language) and their rights; member roles: seniority, the leader's relation, level, contribution
  description    at founding and when the clan's identity changes (turned PvP, built a station, got full); refreshed now and then
  announcement   war, alliance, non-aggression, peace, payment, weekly target (clan news); mass mail during a war
  tax            0-5% depending on the budget need (it used to write 3-8% directly: the limit is clan.MAX_TAX)
  budget         treasury shares k['budget'] {ksi, payment, combat} (the rest is reserve): CBS if there is no station, war if at war
  payment        once a week, from the treasury to the period's top tax payers (with clan.payout_limit and a 10% cut)
  kicking        a member the leader holds a grudge against, or one with no contribution for a long time
  handover       a leader who has lost interest leaves the clan to the officer they trust most; a clan down to one member is dissolved
The rule-based decision comes from society.clan_actions; in Advanced mode the agent does the same jobs with tools (agent_tools.py: clan_*).
The last times of each job are in the clan's record k['management'] (also written to clans.json)."""
import os, random, time

import clan as KL
from . import speech as SPC
from . import society as T

DAY = 86400
TIER_RIGHTS = (                                   # rank tier -> its rights (0 officer ... 3 rookie)
    ['hiremember', 'firemember', 'news', 'roundmail', 'battle_station_build', 'battle_station_replace_module',
     'battle_station_deflector'],
    ['hiremember', 'news', 'battle_station_replace_module'],
    [],
    [])
INTERVALS = {'rank': 600, 'rol': 3 * 3600, 'description': 3600, 'announcement': 900, 'tax': 6 * 3600, 'budget': 6 * 3600, 'payment': 7 * DAY,
          'kick': 12 * 3600, 'handover': 12 * 3600, 'target': 5 * DAY}


LOGO_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'panel', 'ui', 'images', 'clan_logo')


def logos():
    """Logo pool (Orders.md OP-017): names (without extension) of panel/ui/images/clan_logo/*.webp."""
    try:
        return sorted(f[:-5] for f in os.listdir(LOGO_FOLDER) if f.endswith('.webp'))
    except OSError:
        return []


def pick_logo(k):
    """A random logo from the pool that no other clan uses, for a bot clan without one (it returns to the pool when the clan dissolves) -> logo or None."""
    if k.get('logo'):
        return k['logo']
    with KL.LOCK:
        used = {c.get('logo') for c in KL.CLANS.values()}
        empty = [x for x in logos() if x not in used]
        if empty:
            k['logo'] = random.choice(empty)
    return k.get('logo')


def kl_of(b):
    return KL.Clan(T.profile(b), log=lambda *_: None)


def is_successful(out):
    return bool(out) and bool(out[0][1].get('success'))


def raw(b, state):
    """The template without its style (rank names: the bot's writing style must not break the "|" separator)."""
    k = SPC.TEMPLATES.get(state) or {}
    row = k.get(SPC.lang(b)) or k.get('en')
    return b.r.choice(row) if row else None


def save(k):
    return k.setdefault('management', {})


def is_due(k, job, now, interval=None):
    """If the job's time has come (and now marks it) -> True."""
    y = save(k)
    last = y.get(job, 0)
    if now - last < (interval if interval is not None else INTERVALS[job]):
        return False
    y[job] = now
    return True


def find_member(k, name):
    """A member (name lowercased, record) or (None, None): the name or the display name matches."""
    s = str(name or '').strip().lower()
    for a, u in k['members'].items():
        if s in (a, str(u.get('name', '')).lower()):
            return a, u
    return None, None


def find_rank(k, name):
    s = str(name or '').strip().lower()
    return next((r for r in k['ranks'] if r['name'].lower() == s), None)


def seniority_days(u, now):
    try:
        return (now - time.mktime(time.strptime(u.get('joined', ''), '%Y-%m-%d %H:%M:%S'))) / DAY
    except (ValueError, OverflowError):
        return 0.0


def info_summary(k, who=None):
    """The clan's state (the agent's observation): members and their ranks, treasury, tax, budget, diplomacy, applications."""
    now = time.time()
    ranks = {r['id']: r['name'] for r in k['ranks']}
    sorted_members = sorted(k['members'].items(), key=lambda uid_member: (uid_member[0] != k['leader'], -int(uid_member[1].get('level', 1))))
    row = ['Clan [%s] %s, leader %s, %d members, treasury %s credits, tax %d%%.' % (
        k['tag'], k['name'], (k['members'].get(k['leader']) or {}).get('name', k['leader']), len(k['members']), '{:,}'.format(int(k['treasury'])),
        int(k.get('tax') or 0))]
    b = k.get('budget') or {}
    if b:
        row.append('Budget shares of the treasury: station %d%%, payouts %d%%, war %d%%, the rest is reserve.' % (
            100 * b.get('cbs', 0), 100 * b.get('payment', 0), 100 * b.get('combat', 0)))
    row.append('Ranks: %s.' % (', '.join('%s (%s)' % (r['name'], ', '.join(r['rights']) or 'no rights') for r in k['ranks'])
                                 or 'none yet'))
    row.append('Members: %s.' % '; '.join('%s (lvl %s, %s, %d days%s)' % (
        u.get('name', a), u.get('level', 1), 'leader' if a == k['leader'] else ranks.get(u.get('rank', 0), 'no rank'), seniority_days(u, now),
        ', paid %s tax this week' % '{:,}'.format(int(u['contrib_period'])) if u.get('contrib_period') else '') for a, u in sorted_members[:20]))
    diplo = {1: 'alliance', 2: 'non-aggression pact', 3: 'war'}
    d = [diplo.get(x['type'], '?') + ' with ' + str((KL.CLANS.get(x['clan']) or {}).get('name', x.get('name', '?'))) for x in k['diplomacy']]
    if d:
        row.append('Diplomacy: %s.' % ', '.join(d))
    incoming = [r for r in k.get('diplomacy_requests', []) if r['to'] == k['id']]
    if incoming:
        row.append('Diplomacy offers waiting for your answer: %s.' % ', '.join('%s from %s' % (
            {0: 'peace', 1: 'alliance', 2: 'non-aggression'}.get(r['type'], '?'), (KL.CLANS.get(r['from_clan']) or {}).get('name', '?'))
            for r in incoming))
    if k.get('applications'):
        row.append('Applications: %s.' % ', '.join(str(x.get('name')) for x in k['applications'][:8]))
    row.append('Description: %s' % (' '.join(str(k.get('description') or '').split())[:200] or '(empty)'))
    return '\n'.join(row)


# ------------------------------------------------------------------------------------------------------------ jobs
def setup_ranks(b, k, kl):
    """3-4 ranks for a clan without ranks (names in the bot's language, as one set) and the rights of their tiers."""
    if k['ranks']:
        return False
    names = [a.strip() for a in (raw(b, 'clan_ranks') or 'Officer|Veteran|Member|Recruit').split('|') if a.strip()][:4]
    if len(names) < 4:
        names += ['Member', 'Recruit'][len(names) - 2:]
    tiers = [0, 1, 2, 3]
    if b.r.random() < 0.35:                               # some leaders do not open the senior rank
        tiers.remove(1)
    elif b.r.random() < 0.3:
        tiers.remove(3)
    multiplier = save(k).setdefault('rank_tier', {})
    layout = []
    for i in tiers:
        out = kl.handle('ClanNewRankRequest', {'newRank': names[i]})
        r = find_rank(k, names[i])
        if is_successful(out) and r is not None:
            multiplier[str(r['id'])] = i
            layout.append({'rankId': r['id'], 'rankName': r['name'], 'rights': TIER_RIGHTS[i]})
    if layout:
        kl.handle('EditClanRanksRequest', {'ranks': layout})
        b.event('clan_rank', name=', '.join(d['rankName'] for d in layout))
    return bool(layout)


def _tier_rank(k, multiplier):
    """The id of the rank that fits the tier (or the closest tier below it if missing); 0 if there is none."""
    rank_cats = {int(i): int(v) for i, v in (save(k).get('rank_tier') or {}).items() if any(r['id'] == int(i) for r in k['ranks'])}
    for t in range(multiplier, 4):
        r = next((i for i, v in rank_cats.items() if v == t), None)
        if r is not None:
            return r
    return 0


def assign_roles(y, b, k, kl, now):
    """Roles for members: officers (about 1/8 of the members) from among those the leader trusts most, seniors are a few days old and
    contributing, newcomers are rookies. At most three changes per turn (so that not everyone is promoted at once)."""
    if not save(k).get('rank_tier'):
        return 0
    avg = sum(int(u.get('level', 1)) for u in k['members'].values()) / max(1, len(k['members']))
    points = []
    for a, u in k['members'].items():
        if a == k['leader']:
            continue
        day = seniority_days(u, now)
        rel = b.memory.relation(u.get('name', a), now)
        p = 0.45 * min(1.0, day / 14.0) + 0.35 * rel + 0.2 * max(-1.0, min(1.0, (int(u.get('level', 1)) - avg) / 6.0))
        points.append((p + (0.1 if u.get('contrib_period') else 0), day, rel, a, u))
    points.sort(key=lambda x: -x[0])
    officer = max(1, len(points) // 8)
    changed = 0
    for i, (p, day, rel, a, u) in enumerate(points):
        multiplier = 0 if i < officer and day >= 2 and rel >= 0.1 else 1 if day >= 5 and p >= 0.35 else 2 if day >= 1 else 3
        rid = _tier_rank(k, multiplier)
        if rid and int(u.get('rank', 0)) != rid:
            if is_successful(kl.handle('EditClanMemberRequest', {'rankId': rid, 'memberId': int(u.get('uid', 0))})):
                changed += 1
                if changed >= 3:
                    break
    return changed


def write_description(b, k, kl, now, force=False):
    """The clan's description: its focus (PvP, PvE, station), rule, intake (minimum level or full). Redone when the clan's identity changes."""
    from . import clan_stations as CBA
    pvp = b.o('aggression') > 0.6 or any(d['type'] == 3 for d in k['diplomacy'])
    cbs = CBA.stations(k)
    full = len(k['members']) >= KL.MAX_MEMBERS - 2
    signature = [pvp, bool(cbs), full]
    y = save(k)
    if not force and y.get('description_signature') == signature and now - y.get('description_time', 0) < b.r.uniform(4, 9) * DAY:
        return False
    avg = sum(int(u.get('level', 1)) for u in k['members'].values()) / max(1, len(k['members']))
    parts = [SPC.template(b, 'clan_description_focus_pvp' if pvp else 'clan_description_focus_pve', clan=k['name'], tag=k['tag'])]
    if cbs:
        parts.append(SPC.template(b, 'clan_description_focus_cbs', station=cbs[0]))
    if b.r.random() < 0.8:
        parts.append(SPC.template(b, 'clan_description_rules'))
    parts.append(SPC.template(b, 'clan_description_full') if full else SPC.template(b, 'clan_description_recruiting', level=max(1, int(avg * 0.6))))
    text = '\n'.join(p for p in parts if p)
    if not text or not is_successful(kl.handle('ChangeClanDescriptionRequest', {'desc': text[:2000]})):
        return False
    y.update(description_signature=signature, description_time=now)
    b.event('clan_description', now)
    return True


def announce(b, kl, state, **f):
    """Clan news (from the template) -> was it written."""
    text = SPC.template(b, state, **f)
    return bool(text) and is_successful(kl.handle('ClanAddNewsRequest', {'newsMessage': text}))


def bulk_mail(b, kl, state, **f):
    subject, text = SPC.template(b, state + '_subject', **f), SPC.template(b, state, **f)
    return bool(subject and text) and is_successful(kl.handle('ClanSendAllMessageRequest', {'subject': subject[:50], 'msgText': text}))


def announce_events(y, b, k, kl, now):
    """New developments in diplomacy (war, alliance, non-aggression, ended war) become news; when a war starts, mass mail to the members."""
    mgmt = save(k)
    seen = mgmt.setdefault('diplo_seen', {})
    current_time = {str(d['id']): d for d in k['diplomacy']}
    first = not seen and 'diplo_first' not in mgmt
    mgmt['diplo_first'] = True
    for i, d in current_time.items():
        if i in seen or first:
            continue
        name = (KL.CLANS.get(d['clan']) or {}).get('name', d.get('name', '?'))
        state = {1: 'clan_announce_alliance', 2: 'clan_announce_non_aggression', 3: 'clan_announce_war'}.get(d['type'])
        if state and announce(b, kl, state, clan=name) and d['type'] == 3 and KL.right(b.profile, 'roundmail'):
            bulk_mail(b, kl, 'clan_mail_war', clan=name)
    for i, d in seen.items():
        if i not in current_time and d.get('type') == 3:
            announce(b, kl, 'clan_announce_peace', clan=d.get('name', '?'))
    mgmt['diplo_seen'] = {i: {'type': d['type'], 'name': (KL.CLANS.get(d['clan']) or {}).get('name', d.get('name', '?'))}
                         for i, d in current_time.items()}


def set_budget(b, k, now, cbs=None, payment=None, combat=None):
    """Treasury shares (0-1; at most 0.9 in total, the rest is reserve). The ones not given are decided by state and personality: CBS
    share is high if there is no station, war if at war; a generous, low-ambition leader distributes more to members."""
    from . import clan_stations as CBA
    in_combat = any(d['type'] == 3 for d in k['diplomacy'])
    if cbs is None:
        cbs = (0.55 if not CBA.stations(k) else 0.3) * (0.7 + 0.6 * b.o('ambition')) if CBA.is_open() else 0.0
    if combat is None:
        combat = 0.25 if in_combat else 0.12 if b.o('aggression') > 0.6 else 0.04
    if payment is None:
        payment = 0.06 + 0.2 * b.o('sociability') * (1 - 0.6 * b.o('ambition'))
    pay = {'cbs': max(0.0, float(cbs)), 'payment': max(0.0, float(payment)), 'combat': max(0.0, float(combat))}
    top = sum(pay.values())
    if top > 0.9:
        pay = {a: v * 0.9 / top for a, v in pay.items()}
    with KL.LOCK:
        k['budget'] = {a: round(v, 3) for a, v in pay.items()}
    return k['budget']


def spendable(k, area):
    """The credits the budget sets aside for that area (the treasury's share)."""
    return int(k['treasury'] * float((k.get('budget') or {}).get(area, 0)))


def set_tax(b, k, kl, now, ratio=None):
    """Tax 0-5% (by request; not possible without the right): an ambitious leader keeps it high; raises it if money is short of the
    budget's goal (station), lowers it when the treasury is very full."""
    from . import clan_stations as CBA
    if ratio is None:
        ratio = 1 + round(3 * b.o('ambition'))
        if CBA.is_open() and CBA.need(k) > k['treasury']:
            ratio += 1
        if k['treasury'] > 50000000:
            ratio -= 2
    ratio = max(0, min(KL.MAX_TAX, int(ratio)))
    if int(k.get('tax') or 0) == ratio:
        return True
    return is_successful(kl.handle('ChangeClanTaxRequest', {'tax': ratio}))


def make_payout(b, k, kl, now):
    """Weekly payment: the budget's payment share goes to the period's top tax payers (at most 3), in proportion to their contribution;
    the period resets. The no-contribution counter of a member with no contribution grows (for kicking)."""
    pool = spendable(k, 'payment')
    contribution = sorted(((int(u.get('contrib_period', 0)), a, u) for a, u in k['members'].items() if u.get('contrib_period')), key=lambda x: -x[0])[:3]
    paid = []
    if pool >= 100000 and contribution:
        top = sum(x[0] for x in contribution)
        for multiplier, a, u in contribution:
            amount = min(int(pool * multiplier / top), KL.payout_limit(u, now))
            if amount >= 10000 and is_successful(kl.handle('PayoutClanRequest', {'amount': amount, 'payoutUserId': int(u.get('uid', 0)),
                                                                           'reason': 'top contributor'})):
                paid.append(u.get('name', a))
    with KL.LOCK:
        for a, u in k['members'].items():
            u['no_contribution'] = 0 if u.get('contrib_period') else int(u.get('no_contribution', 0)) + 1
            u['contrib_period'] = 0
    if paid:
        announce(b, kl, 'clan_announce_payout', names=', '.join(paid))
        b.event('clan_payout', now, names=paid)
    return paid


def kick(y, b, k, kl, now, name=None):
    """Kicking: the given member, or a (bot) member the leader holds a grudge against / with no contribution for three weeks; at most one per turn."""
    if name is None:
        candidate = None
        for a, u in k['members'].items():
            if a == k['leader']:
                continue
            rel = b.memory.relation(u.get('name', a), now)
            if rel <= -0.45 or (int(u.get('no_contribution', 0)) >= 3 and a in y.name_index and seniority_days(u, now) > 21):
                candidate = a
                break
        if candidate is None or b.r.random() > 0.5:
            return None
        name = candidate
    a, u = find_member(k, name)
    if u is None or not is_successful(kl.handle('DeleteClanMemberRequest', {'removeUserID': int(u.get('uid', 0))})):
        return None
    o = y.name_index.get(a)
    if o is not None:
        o.k['clan'] = None
        T.update(o)
    b.event('kicked_from_clan', now, name=u.get('name', a))
    return u.get('name', a)


def hand_over(y, b, k, kl, now, name=None):
    """Giving up leadership: to the given member or to the most trusted officer (else the most senior member). Very rare on its own: a
    low-ambition leader who has lost interest."""
    if name is None:
        if len(k['members']) < 3 or b.r.random() > 0.02 * (1.2 - b.o('ambition')) * (0.5 + b.mood['fatigue']):
            return None
        officer = {r for r, v in (save(k).get('rank_tier') or {}).items() if v == 0}
        candidates = [(str(u.get('rank', 0)) in officer, b.memory.relation(u.get('name', a), now), seniority_days(u, now), a)
                   for a, u in k['members'].items() if a != k['leader']]
        if not candidates:
            return None
        name = max(candidates)[3]
    a, u = find_member(k, name)
    if u is None or a == k['leader'] or not is_successful(kl.handle('ChangeClanLeaderRequest', {'newLeaderId': int(u.get('uid', 0))})):
        return None
    b.event('resigned_leadership', now, name=u.get('name', a))
    return u.get('name', a)


def distribute(y, b, k, kl, now):
    """The leader dissolves a clan that has been down to one member for a week (rare)."""
    if len(k['members']) > 1 or seniority_days(k['members'].get(k['leader']) or {}, now) < 7 or b.r.random() > 0.1:
        return False
    if not is_successful(kl.handle('DeleteClanRequest', {})):
        return False
    b.k['clan'] = None
    T.update(b)
    b.event('disbanded_clan', now, clan=k['name'])
    return True


def weekly_goal(b, k, kl, now):
    """According to the budget's focus, the week's target becomes news (money for the station, grinding, PvP)."""
    from . import clan_stations as CBA
    budget = k.get('budget') or {}
    if CBA.is_open() and budget.get('cbs', 0) >= max(budget.get('combat', 0), 0.3) and not CBA.stations(k):
        return announce(b, kl, 'clan_announce_target_cbs')
    if budget.get('combat', 0) >= 0.2:
        return announce(b, kl, 'clan_announce_target_pvp')
    return announce(b, kl, 'clan_announce_target_farm')


def manage(y, b, k, kl, now):
    """Rule-based management (from society.clan_actions, in the social turn): each job at its own interval; the leader does everything, an officer as far as their rights go."""
    leader = k['leader'] == b.name.lower()
    if not leader and (not kl.right('news', k) or k['leader'] not in y.name_index):
        return                                            # an officer bot does not manage the player's clan (you are the leader)
    if leader:
        if is_due(k, 'rank', now):
            setup_ranks(b, k, kl)
            if not k.get('logo') and pick_logo(k):
                KL.changed(k)                             # logo to clans.json (the panel's Clans tab)
        if is_due(k, 'rol', now):
            assign_roles(y, b, k, kl, now)
        if is_due(k, 'description', now):
            write_description(b, k, kl, now)
        if is_due(k, 'budget', now) or not k.get('budget'):
            set_budget(b, k, now)
        if is_due(k, 'tax', now):
            set_tax(b, k, kl, now)
        if is_due(k, 'payment', now) and seniority_days(k['members'].get(k['leader']) or {}, now) >= 6:
            make_payout(b, k, kl, now)
        if is_due(k, 'kick', now):
            kick(y, b, k, kl, now)
        if is_due(k, 'handover', now) and (hand_over(y, b, k, kl, now) or distribute(y, b, k, kl, now)):
            return
    from . import clan_stations as CBA
    CBA.manage(y, b, k, kl, now)                            # Clan Battle Station: race, development, defense (with the right to build)
    if is_due(k, 'announcement', now):
        announce_events(y, b, k, kl, now)
    if is_due(k, 'target', now, INTERVALS['target'] * b.r.uniform(0.8, 1.4)):
        weekly_goal(b, k, kl, now)
