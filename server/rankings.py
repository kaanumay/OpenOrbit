"""Sıralama ödülleri (yol haritası Ö1; veri data/ranking_rewards.json <- tools/ranking_rewards.py).

Modun penceresi ödül aralıklarını bilgi komutuyla alır (ranges: RankRewardRangeModule {from, to}); ödül sekmesi her aralık için
RankRewardRequest {ranking: aralığın başı, rankType} gönderir -> reward(): RankRewardCommand {rankType, rewardContentModuleList
[RewardModule {lootId, amount}, RewardTitleModule {titleKey}], rewardRange}. Tablo yoksa None (oturum kayıttaki yanıta bakar).
rankType: 2 Gauntlet of Plutus, 7 Eternal Black Light, 9 Astral Ascension. Tek oyunculuda sıralamada yalnız oyuncu var: tablolar
pencerede görünür, dağıtım bot oyuncularla (Aşama 11).
"""
import json, os, re, time

HERE = os.path.dirname(os.path.abspath(__file__))
_P = os.path.join(HERE, 'data', 'ranking_rewards.json')
_D = json.load(open(_P, encoding='utf8')) if os.path.exists(_P) else {}
TABLES = {int(k): v for k, v in _D.get('tablolar', {}).items()}
SET_TITLES = {t for k, v in _D.get('title_sets', {}).items() if not k.startswith('_') for t in v}
MONTHS = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')
PLUTUS, EBL, ASTRAL = 2, 7, 9
DEFAULT_REWARD, PAYLOAD_ESCORT_REWARD = 3, 6                 # EventRewardConfirmationCommand.RewardType


def mod(name, **f):
    f['_'] = name
    return f


def range_mod(r):
    return mod('RankRewardRangeModule', **{'from': r['den'], 'to': r['e']})


def ranges(rank_type):
    """Pencerenin ödül aralıkları (bilgi komutunun playerRanges / playerRankRanges alanı)."""
    return [range_mod(r) for r in TABLES.get(rank_type, {}).get('ranges', [])]


def reward(f):
    """RankRewardRequest -> [RankRewardCommand] ya da None (bu rankType'ın tablosu yok)."""
    t = TABLES.get(int(f.get('rankType') or 0))
    if not t:
        return None
    n = int(f.get('ranking') or 0)
    r = next((r for r in t['ranges'] if r['den'] <= n <= r['e']), None)
    if not r:
        return []
    return [('RankRewardCommand', dict(rankType=int(f['rankType']), rewardContentModuleList=items(r), rewardRange=range_mod(r)))]


def set_title(key, now=None):
    """Sete göre değişen sıralama unvanı (resmî forum: her setin unvanı ayrı): title_<sıralama>-<ay><yıl>set<n>, ayın 20'sinden önce
    set 1, sonra set 2, ayın ilk 3 günü önceki ayın set 2'si; istemcide yoksa tablonun unvanı."""
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
    out = [mod('RewardModule', lootId=l, amount=a) for l, a in r['esyalar']]
    if r.get('unvan'):
        out.append(mod('RewardTitleModule', titleKey=set_title(r['unvan'], now)))
    return out


def confirmation(rank, reward_type, r):
    """Etkinlik sonu tebrik penceresi: EventRewardConfirmationCommand {ranking, rewardType (komutun kendi RewardType'ı: 3 DEFAULT,
    6 PAYLOAD_ESCORT, ...), reward}; istemci EventRewardData'yla pencereyi açar."""
    return ('EventRewardConfirmationCommand', dict(ranking=int(rank), rewardType=reward_type, reward=items(r)))
