"""Ranking rewards (roadmap Ö1; data in data/ranking_rewards.json <- tools/ranking_rewards.py).

The mode's window gets the reward ranges with the info command (ranges: RankRewardRangeModule {from, to}); for each range the reward tab sends
RankRewardRequest {ranking: start of the range, rankType} -> reward(): RankRewardCommand {rankType, rewardContentModuleList
[RewardModule {lootId, amount}, RewardTitleModule {titleKey}], rewardRange}. None if there is no table (the session looks at the recorded reply).
rankType: 2 Gauntlet of Plutus, 7 Eternal Black Light, 9 Astral Ascension. In single player only the player is in the ranking: the tables
show in the window, distribution with bot players (stage 11).
"""
import json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
_P = os.path.join(HERE, 'data', 'ranking_rewards.json')
_D = json.load(open(_P, encoding='utf8')) if os.path.exists(_P) else {}
TABLES = {int(k): v for k, v in _D.get('tables', {}).items()}
SET_TITLES = {t for k, v in _D.get('title_sets', {}).items() if not k.startswith('_') for t in v}
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
PLUTUS, EBL, ASTRAL = 2, 7, 9
DEFAULT_REWARD, PAYLOAD_ESCORT_REWARD = 3, 6                 # EventRewardConfirmationCommand.RewardType


def mod(name, **f):
    f['_'] = name
    return f


def range_mod(r):
    return mod('RankRewardRangeModule', **{'from': r['from_'], 'to': r['e']})


def ranges(rank_type):
    """The window's reward ranges (the info command's playerRanges / playerRankRanges field)."""
    return [range_mod(r) for r in TABLES.get(rank_type, {}).get('ranges', [])]


def reward(f):
    """RankRewardRequest -> [RankRewardCommand] or None (no table for this rankType)."""
    t = TABLES.get(int(f.get('rankType') or 0))
    if not t:
        return None
    n = int(f.get('ranking') or 0)
    r = next((r for r in t['ranges'] if r['from_'] <= n <= r['e']), None)
    if not r:
        return []
    return [('RankRewardCommand', dict(rankType=int(f['rankType']), rewardContentModuleList=items(r), rewardRange=range_mod(r)))]


def set_title(key, now=None):
    """The ranking title that varies by set (official forum: each set has its own title): title_<ranking>-<month><year>set<n>, before the 20th of the month
    set 1, then set 2, the first 3 days of the month the previous month's set 2; if not on the client, the table's title."""
    m = re.match(r'(title_\w+Rankings)-[a-z]{3}\d{4}set\d$', key or '')
    if not m:
        return key
    t = time.localtime(time.time() if now is None else now)
    y, mo, n = t.tm_year, t.tm_mon, 1 if t.tm_mday < 20 else 2
    if t.tm_mday <= 3:
        y, mo, n = (y, mo - 1, 2) if mo > 1 else (y - 1, 12, 2)
    cand = '%s-%s%dset%d' % (m.group(1), MONTHS[mo - 1], y, n)
    return cand if cand in SET_TITLES else key


def items(r, now=None):
    out = [mod('RewardModule', lootId=l, amount=a) for l, a in r['items']]
    if r.get('title'):
        out.append(mod('RewardTitleModule', titleKey=set_title(r['title'], now)))
    return out


def confirmation(rank, reward_type, r):
    """End-of-event congratulation window: EventRewardConfirmationCommand {ranking, rewardType (the command's own RewardType: 3 DEFAULT,
    6 PAYLOAD_ESCORT, ...), reward}; the client opens the window with EventRewardData."""
    return ('EventRewardConfirmationCommand', dict(ranking=int(rank), rewardType=reward_type, reward=items(r)))
