"""Eski metin protokolü (Flash döneminden kalma; LegacyModule {message}): üretme ve çözme yardımcıları.

İstemcideki dağıtım: belgeler/istemci/eski_protokol.md (tools/il2cpp/client_map.py). Sunucudan istemciye "0|<anahtar>|…":
  0|LM|ST|<tür>|…   kazanç/ganimet günlüğü: EP|<kazanç>|<toplam>|<seviye>, HON, CRE, URI (<kazanç>|<toplam>), BAT/ROK (cephane), LOT
                    (eşya, adet) — BoxCollectResponseAssemblyHelper
  0|A|STM|<anahtar>|…  yerelleştirilmiş ekran mesajı (loadfull, jumplevelfalse|%!|<seviye>, config_change_failed_time, …);
                    istemci yalnız flashres anahtarlarını gösterir. Ötekiler (resource_system_inc …) için 0|A|CSTM|<anahtar>|-1
                    (bütün kaynaklarda arar): legacy() flashres'te olmayan parametresiz STM'i buna çevirir (canlı test H24)
  0|A|ACG|<başarım>_<seviye>|<sayı>  başarım kazanma efekti ve penceresi
  0|A|SLA|0|<kullanıcı>  toplama ışını; 0|A|C|<kredi>|<uridyum>  para
  0|n|t|<kullanıcı>|<unvan kimliği>|<unvan>  gemi üstünde unvan; 0|n|LSH|<hedef>|<saldıran>  lazer çizgisi;
  0|n|e|… / 0|n|INV|… / 0|n|d|…  gemi görünümü, görünmezlik, dron dizgisi; 0|S|CFG|<n>  config; 0|v|<saldıran>|<hedef>|H|…  roket;
  0|l  çıkış (bağlantı kapanır)
İstemciden sunucuya (kayıt ve günlükler): S|CFG|<n>|<kullanıcı>|<anahtar> (config geçişi), i|<kimlik> (bilinmeyen varlığı sor),
LF|c ve JCPU|GET (her girişte; gerçek sunucu yanıt vermez).
"""

import json, os

MODULE = 'LegacyModule'
_FLASHRES = []                    # data/flashres_anahtarlari.json (tools/stm_anahtarlari.py); dosya yoksa çeviri yapılmaz


def flashres():
    if _FLASHRES == []:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'flashres_keys.json')
        _FLASHRES[:] = [set(json.load(open(p, encoding='utf8'))['keys']) if os.path.exists(p) else None]
    return _FLASHRES[0]


def legacy(text):
    """Hazır metinden komut: legacy('0|A|STM|loadfull'). Flashres'te olmayan parametresiz STM -> 0|A|CSTM|<anahtar>|-1."""
    if text.startswith('0|A|STM|') and text.count('|') == 3:
        keys = flashres()
        if keys is not None and text[8:] not in keys:
            text = '0|A|CSTM|%s|-1' % text[8:]
    elif text.startswith(('0|LM|ST|CRE|', '0|LM|ST|URI|')):
        p = text.split('|')                # istemci kazancı SafeInt okuyor (toplamı SafeLong): 2^31-1'i aşan kazanç eksi görünürdü
        if int(p[4]) > 2 ** 31 - 1:
            p[4] = str(2 ** 31 - 1)
            text = '|'.join(p)
    return (MODULE, {'message': text})


def msg(*parts):
    """Parçalardan "0|…" komutu: msg('A', 'STM', 'loadfull') -> 0|A|STM|loadfull."""
    return legacy('|'.join(['0'] + [str(p) for p in parts]))


def loot_kind(loot):
    """0|LM|ST satırının eşya türü: BAT lazer, RL roketatar (kayıt: RL|ammunition_rocketlauncher_eco-10|7), ROK roket cephanesi,
    öteki LOT; istemcide her biri ayrı metin."""
    if loot.startswith('ammunition_laser_'):
        return 'BAT'
    if loot.startswith('ammunition_rocketlauncher_'):
        return 'RL'
    return 'ROK' if loot.startswith('ammunition_rocket_') else 'LOT'


def stm(key, *args):
    """Yerelleştirilmiş ekran mesajı: stm('jumplevelfalse', '%!', 2) -> 0|A|STM|jumplevelfalse|%!|2."""
    return msg('A', 'STM', key, *args)


def parse(fields):
    """İstemcinin LegacyModule alanlarından -> (anahtar, parçalar): 'S|CFG|2|…' -> ('S|CFG', [..]), 'i|533' -> ('i', ['i', '533'])."""
    parts = (fields or {}).get('message', '').split('|')
    key = '|'.join(parts[:2]) if parts and parts[0] == 'S' and len(parts) > 1 else parts[0] if parts else ''
    return key, parts


def text(m):
    """Bir LegacyModule komutunun metni (değilse None) — testler ve günlük için."""
    return m[1].get('message') if m and m[0] == MODULE else None
