"""Etkinlik görünümleri (veri data/event_appearances.json <- tools/event_appearances.py): mağazadaki kaynaksız tasarımlardan
gerçek oyunda bir etkinlikle kazanılanlar ve tek oyunculudaki kazanma yolları.

Panelin 'etkinlik_gorunumleri_magazada' ayarı (varsayılan açık): açıkken mağazada satılırlar (E11'deki gibi); kapalıyken mağazada
görünmez ve satılmazlar (magaza.gate_ok). Yollar ayardan bağımsız hep açık:
  degisim  savas_bileti: etkinliğin Battle Pass'i sürerken anahtar değişiminde (exchange_rows)
  kutu     ganimet: kutunun yerel tasarım satırlarına ağırlığıyla (box_rows; wiki tablosundakiler 'tablo', ek satır olmaz)
  kapi     takvim: GG Special Rewards Weekend'lerin kapı ödüllerine seçimli satır (apply)
  harita   takvim: etkinliğin harita kutusunun içeriğine (apply)
  sezon    sezon: ödül sıralarındaki sezon tasarımları sezonun sırasıyla (season_track)
"""
import json, os, re

import settings as SET

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, 'data', 'event_appearances.json'), encoding='utf8'))
ITEMS = D['looks']
SEASONS = D['seasons']
RECORDED = SEASONS[-1]                   # kayıttaki sezon (ödül sıralarında onun tasarımları)
FIRST = tuple(int(x) for x in SEASONS[0]['season'].split('-'))


def in_shop(loot):
    """Mağazada satılır mı: etkinlik görünümü değilse ya da panelin ayarı açıksa."""
    return loot not in ITEMS or bool(SET.get(D['ayar']))


def paths(kind):
    return [(loot, y) for loot, x in ITEMS.items() for y in x['paths'] if y['route'] == kind]


def exchange_id(loot):
    """Anahtar değişimi satırının adı, istemcinin biçimiyle (<tema>-<gemi>-ship-design, nobilis-a-elite-pet-design): satırın başlığı
    istemcinin items_bpk_<ad>_fullname metni (gerçek oyunun değişimlerinde olanların metni var, ötekilerde başlık boş, ödül satırı
    yine "Obtain 1 … Design")."""
    if loot.startswith('ship_'):
        base, d = re.match(r'ship_(.+?)_design_(.+)$', loot).groups()
        return '%s-%s-ship-design' % (re.sub(r'^(ship-)?%s-' % re.escape(base), '', d), base)
    kind = 'drone' if loot.startswith('drone_') else 'pet'
    name = re.sub(r'^%s-' % kind, '', loot.split('_designs_', 1)[1]).rsplit('-', 1)
    return '%s-%s-%s-design' % (name[1], name[0], kind) if len(name) == 2 else '%s-%s-design' % (name[0], kind)


def exchange_rows(event):
    """Etkinliğin anahtar değişimine eklenen tasarım satırları (BattlePassKeyExchangeRewardModule; kayıttaki tasarımlar gibi özel)."""
    return [dict(_='BattlePassKeyExchangeRewardModule', cost=y['charge'], limit=y['cap'], exchangeReward=exchange_id(loot),
                 listOfloot=[dict(_='BattlePassKeyExchangeLootModule', lootId=loot, amount=1)], priority=2, isSpecial=True, claimCount=0)
            for loot, y in paths('exchange') if y['etkinlik'] == event]


def box_rows(box):
    """Kutunun yerel tasarım satırları [lootId, 1, ağırlık] (ganimet.pick'te tasarım çekilişine katılır): wiki tablosunda olmayan
    görünümler ve kutunun eski Red / Blue P.E.T. havuzu ('kutu_ek'); tablosunda zaten olan tasarım ek satır olmaz ('tablo')."""
    return [[loot, 1, y['weight']] for loot, y in paths('kutu') if y['kutu'] == box and not y.get('table')] + \
           [list(r) for r in D.get('box_extra', {}).get(box, [])]


def apply(events):
    """takvim'in etkinliklerine (yerinde): kapıların seçimli ödülü ve harita kutularının içeriği."""
    gates = {}
    for loot, y in paths('kapi'):
        gates.setdefault((y['etkinlik'], tuple(y['kapilar']), y['probability']), []).append([loot, 1])
    for (ev, keys, chance), rows in gates.items():
        for k, e in events.items():
            if k.startswith(ev):                               # gg_hafta_sonu_1, _3, _4
                e.setdefault('gate_reward', []).append(dict(kapilar=list(keys), probability=chance, choice=rows, non_repeating=True))
    for loot, y in paths('harita'):
        e = events[y['etkinlik']]
        for s in ([e['harita']] if 'harita' in e else []) + e.get('map_extra', []):
            for b in s.get('boxes', []):
                if b['tur'] == y['kutu']:
                    b['contents'].append([loot, 1, y['weight']])


def season(sid):
    """Sezonun tasarımları ('2026-11' gibi): ilk sezondan (2023-05) sayılarak 14 sezonluk sıra, sonra baştan."""
    y, m = (int(x) for x in sid.split('-'))
    n = ((y - FIRST[0]) * 12 + m - FIRST[1]) // 3
    return SEASONS[n % len(SEASONS)]


def season_track(key, rows, sid):
    """Ödül sırası ('ucretsiz' | 'gold' | 'ext': [[seviye, lootId, adet]]) -> sezonun tasarımlarıyla: kayıttaki sezonun dron ve P.E.T.
    tasarımları yerine sezonunkiler; sezonun gemi tasarımı varsa Gold sırasının son ödülü (dev Gold rezervi) yerine."""
    s = season(sid)
    swap = {RECORDED['drone']: s['drone'], RECORDED['pet']: s['pet']}
    out = [[lv, swap.get(l, l), n] for lv, l, n in rows]
    if key == 'gold' and s['gemi']:
        out[-1] = [out[-1][0], s['gemi'], 1]
    return out
