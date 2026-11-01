"""Uridium Bank (roadmap stage 5; single-player adaptation, data/bank.json): every uridium earned in the game is mirrored into the bank
(up to the maximum; in the save UridiumBankInfoCommand.maxValue is 34,500, and currentValue goes 0 -> 2,150 -> 4,300 as you play). In the
real game the bank is opened with real money (UridiumBankClaimCommand payment link); here each accumulated uridium is bought for
kredi_fiyati credits, once at least en_az uridium has accumulated. No payment link is sent.

  on login and when the accumulation changes   UridiumBankInfoCommand {maxValue, currentValue, price (credit amount), secondsLeft -1}
  UridiumBankClaimRequest                      if credits suffice the accumulation turns into uridium and the bank empties
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'bank.json'), encoding='utf8'))
SKIP = ('uridium_bank', 'sell')                 # earnings that do not count towards the bank (the bank itself, selling)


def value(p):
    return int(p.d.get('bank', 0))


def accrue(p, n, reason=None):
    """Earned uridium (profile.gain) -> the same amount into the bank (up to the maximum). The caller does not hold the lock."""
    if n <= 0 or (reason and str(reason).startswith(SKIP)):
        return
    with p.lock:
        p.d['bank'] = min(B['maximum'], value(p) + n)
        p.dirty = True


def price(p):
    return value(p) * B['credit_price']


def info_cmd(p):
    return ('UridiumBankInfoCommand', dict(maxValue=B['maximum'], textKey='', secondsLeft=-1,
                                           price='%d C' % price(p) if value(p) >= B['min_value'] else '', imgKey='', currentValue=value(p)))


def claim(p, money_msgs=None, log=print):
    v, cost = value(p), price(p)
    if v < B['min_value'] or p.d['pilot'].get('credits', 0) < cost:
        log('   Uridium Bank: could not claim (accumulated %d, credits %d / %d)' % (v, p.d['pilot'].get('credits', 0), cost))
        return [info_cmd(p)]
    p.gain(credits=-cost, uridium=v, reason='title_uridium_bank')
    with p.lock:
        p.d['bank'] = 0
        p.dirty = True
    log('   Uridium Bank: %d U claimed (%d credits)' % (v, cost))
    return (money_msgs() if money_msgs else []) + [info_cmd(p)]
