"""Uridium Bank (yol haritası Aşama 5; tek oyunculu uyarlama, data/bank.json): oyunda kazanılan her uridyumun aynısı bankaya birikir
(en çok azami; kayıttaki UridiumBankInfoCommand.maxValue 34.500, oynadıkça currentValue 0 -> 2.150 -> 4.300). Gerçek oyunda banka
gerçek parayla açılır (UridiumBankClaimCommand ödeme bağlantısı); burada birikenin her uridyumu kredi_fiyati krediye alınır, en az
en_az uridyum birikince. Ödeme bağlantısı gönderilmez.

  girişte ve birikim değişince   UridiumBankInfoCommand {maxValue, currentValue, price (kredi tutarı), secondsLeft -1}
  UridiumBankClaimRequest        kredi yeterse birikim uridyuma geçer, banka boşalır
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
B = json.load(open(os.path.join(HERE, 'data', 'bank.json'), encoding='utf8'))
SKIP = ('uridium_bank', 'sell')                 # bankaya sayılmayan kazançlar (bankanın kendisi, satış)


def value(p):
    return int(p.d.get('bank', 0))


def accrue(p, n, reason=None):
    """Kazanılan uridyum (profil.gain) -> bankaya aynı miktar (azamiye dek). Kilidi çağıran tutmaz."""
    if n <= 0 or (reason and str(reason).startswith(SKIP)):
        return
    with p.lock:
        p.d['bank'] = min(B['maximum'], value(p) + n)
        p.dirty = True


def price(p):
    return value(p) * B['credit_price']


def info_cmd(p):
    return ('UridiumBankInfoCommand', dict(maxValue=B['maximum'], textKey='', secondsLeft=-1,
                                           price='%d C' % price(p) if value(p) >= B['en_az'] else '', imgKey='', currentValue=value(p)))


def claim(p, money_msgs=None, log=print):
    v, cost = value(p), price(p)
    if v < B['en_az'] or p.d['pilot'].get('credits', 0) < cost:
        log('   Uridium Bank: alınamadı (birikim %d, kredi %d / %d)' % (v, p.d['pilot'].get('credits', 0), cost))
        return [info_cmd(p)]
    p.gain(credits=-cost, uridium=v, reason='title_uridium_bank')
    with p.lock:
        p.d['bank'] = 0
        p.dirty = True
    log('   Uridium Bank: %d U alındı (%d kredi)' % (v, cost))
    return (money_msgs() if money_msgs else []) + [info_cmd(p)]
