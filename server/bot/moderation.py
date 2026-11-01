"""Sohbet moderatörleri (oyuncu isteği 2026-10-31): paketin ayarlarında açılır; sabırlı, yardımsever, sadık birkaç bot moderatördür
(sohbette rolü "mod": istemci moderatör rengiyle çizer). Kurallar panelde açılıp kapanır: BÜYÜK HARF, sel (aynı satır ya da çok hızlı),
hakaret ve zararlı söz, reklam/bağlantı. Kuralı çiğneyen (insan ya da bot; yönetici ve moderatörler hariç) önce uyarılır, 30 dk
içinde yine çiğnerse sustur_dk susturulur, yasak_esik susturmadan sonra yasak_saat global ve firma sohbetinden yasaklanır. Kararı
ancak çevrimiçi bir moderatör verir (gerçek sunucudaki gibi; kimse yoksa sohbet serbest), birkaç saniye sonra kanala yazar.
Susturulanın global/firma mesajı sohbet sunucusunda düşer (sohbet.Sohbet.engel), kendisine kalan süre sistem mesajıyla bildirilir.
"""
import math
import re
import time

from . import speech as SPC

RULES = ('buyuk', 'sel', 'hakaret', 'reklam')
TAG = 'CM'                    # moderatörün sohbette ve gemisinin üstünde gösterilen etiketi (klanlar alamaz: klan.ayrilmis)
CHAT_ROLE = 'mod'              # istemci yamasıyla kendi renginde (panel/plugin/Yamalar.cs ModeratorRengi); admin rolü etiketi gizlerdi
WARNING_SEC = 1800                  # uyarıdan sonra bu süre içindeki ikinci ihlal susturur
_LINK = re.compile(r'(https?://|www\.|discord\.gg|\b[\w-]+\.(com|net|org|gg|io|ru|tr|de)\b)', re.I)
CHANNELS = ('global', 'firma')
NOTICE = {'tr': 'Susturuldun: {0} dk kaldı.', 'en': 'You are muted: {0} min left.', 'de': 'Du bist stummgeschaltet: noch {0} Min.',
            'es': 'Estás silenciado: quedan {0} min.', 'fr': 'Tu es muet : encore {0} min.', 'pl': 'Jesteś wyciszony: zostało {0} min.',
            'pt': 'Você está silenciado: faltam {0} min.', 'ru': 'Вы заглушены: осталось {0} мин.'}


def is_open(y):
    return bool(y.setting('moderator', False)) and y.permission('sohbet')


def sec(y):
    """Moderatörleri seç (kalıcı: aynı paket hep aynı botları): sabır, yardımseverlik ve sadakati en yüksek, saldırganlığı düşük."""
    for b in y.bots:
        b.moderator = False
    if not is_open(y):
        return []
    n = int(y.setting('mod_count', 2) or 1)
    points = lambda b: b.o('patience') + b.o('helpfulness') + b.o('loyalty') - b.o('aggression') + 0.001 * (b.uid % 97)
    out = sorted(y.bots, key=points, reverse=True)[:n]
    for b in out:
        b.moderator = True
    return out


def _registry(y, name):
    return y.__dict__.setdefault('mod_record', {}).setdefault(str(name).lower(), {'warning': 0, 'warning_time': 0, 'mutes': 0, 'bitis': 0,
                                                                               'ban': False, 'last': []})


def violation(y, name, msg, now):
    """Mesaj hangi kuralı çiğniyor -> kural ya da None (açık kurallardan ilki). Sel için kişinin son mesajlarını tutar."""
    k = _registry(y, name)
    k['last'] = [x for x in k['last'] if now - x[0] < 60] + [(now, str(msg).strip().lower())]
    letters = [c for c in str(msg) if c.isalpha()]
    if y.setting('rule_ads', True) and _LINK.search(msg):
        return 'reklam'
    if y.setting('rule_insult', True):
        from . import llm as LLM
        if LLM.harmful(msg) or SPC.intent(msg)[0] == 'hakaret':
            return 'hakaret'
    if y.setting('rule_flood', True) and (sum(1 for t, m in k['last'] if m == k['last'][-1][1]) >= 3
                                       or sum(1 for t, m in k['last'] if now - t < 10) >= 5):
        return 'sel'
    if y.setting('rule_caps', True) and len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        return 'buyuk'
    return None


def is_muted(y, name, now=None):
    """Kalan susturma/yasak süresi (sn) ya da 0."""
    k = y.__dict__.get('mod_record', {}).get(str(name).lower())
    return max(0.0, k['bitis'] - (now or time.time())) if k else 0.0


def moderate(y, name, msg, channel, now, rol='chatter'):
    """Global/firma sohbetindeki satır (insanın ya da botun): kural çiğnendiyse çevrimiçi bir moderatör yaptırımı uygular ->
    yaptırım ('uyari' | 'sustur' | 'yasak') ya da None."""
    if not is_open(y) or channel not in CHANNELS or rol in ('admin', 'mod', 'system'):
        return None
    b = y.name_index.get(str(name).lower())
    if b is not None and getattr(b, 'moderator', False):
        return None
    import admin_mode as YM
    if b is None and YM.mi(name_=name):
        return None
    rule = violation(y, name, msg, now)
    modes = [m for m in y.bots if getattr(m, 'moderator', False) and m.online]
    if rule is None or not modes:
        return None
    m = max(modes, key=lambda m: m.o('patience') * m.r.random())
    k = _registry(y, name)
    if k['bitis'] > now:
        return None                                       # zaten susturulu (satırı zaten düştü)
    if now - k['warning_time'] > WARNING_SEC:
        k['warning'] = 0
    delay = m.r.uniform(2, 8)
    if k['warning'] == 0:
        k['warning'], k['warning_time'] = 1, now
        y.speak(m, channel, SPC.template(m, 'mod_uyari_' + rule, ad=name), now=now + delay, priority=True)
        return 'warning'
    k['warning'] = 0
    k['mutes'] += 1
    if k['mutes'] >= int(y.setting('ban_threshold', 3) or 3):
        hour = int(y.setting('ban_hours', 24) or 24)
        k['bitis'], k['ban'], k['mutes'] = now + hour * 3600, True, 0
        y.speak(m, channel, SPC.template(m, 'mod_yasak', ad=name, saat=hour), now=now + delay, priority=True)
        return 'ban'
    minutes = int(y.setting('mute_min', 10) or 10)
    k['bitis'], k['ban'] = now + minutes * 60, False
    y.speak(m, channel, SPC.template(m, 'mod_sustur', ad=name, dk=minutes), now=now + delay, priority=True)
    if b is not None:
        b.memory.event(m.name, 'hakaret', now)               # susturulan bot moderatöre biraz kırgın
    return 'mute'


def block(y, user, path, lang=None):
    """Sohbet sunucusundan (sohbet iş parçacığı): insanın global/firma mesajı düşsün mü -> oyuncuya bildirim metni ya da None."""
    if not is_open(y) or not (path.startswith('/room/global/') or path.startswith('/room/faction/')):
        return None
    remaining = is_muted(y, user.get('userId', ''))
    if remaining <= 0:
        return None
    return NOTICE.get(lang or 'en', NOTICE['en']).format(max(1, math.ceil(remaining / 60)))


def remind_rules(y, now):
    """Arada (45-90 dk) bir moderatör globalde kuralları hatırlatır."""
    if not is_open(y) or now < y.__dict__.get('_mod_reminder', 0):
        return
    first = '_mod_hatirlat' not in y.__dict__
    y._mod_reminder = now + (600 if first else 2700 + 2700 * (hash(int(now)) % 100) / 100)
    if first:
        return
    modes = [m for m in y.bots if getattr(m, 'moderator', False) and m.online]
    if modes:
        m = modes[int(now) % len(modes)]
        y.speak(m, 'global', SPC.template(m, 'mod_kurallar'), now=now)
