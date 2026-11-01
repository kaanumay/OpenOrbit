"""Botlar ve yönetici (admin_mode.py; kullanıcı isteği 2026-10-30): yöneticiyi tanırlar, sohbetteki uyarısına uyarlar, onu görünce
tepki verirler.

Uyarı: yöneticinin oda mesajı ya da fısıltısı uyarı sözcüğü içeriyorsa (sekiz dilde: "stop", "warning", "kes", "yeter", "hör auf" …)
konusu sözcüklerden: sohbet (spam, küfür, büyük harf), pvp (öldürme, acemi avlama, kamp), kutu (kargo kutusu, ganimet çalma); konusu
yoksa genel (sohbet ve PvP, kısa). Uyarılan botlar: adı geçenler; adı geçen yoksa kanalı dinleyenler. Etkisi süreli (tekrarlandıkça
iki katı, en çok 8 katı):
  sohbet  30 dk   konuşma çoğu kez susar (yalnız yanıtlar), hakarete karşılık yok
  pvp     4 sa    oyuncuya ve bota saldırmaz, PvP avına çıkmaz
  kutu    24 sa   başkasının kargo kutusunu almaz
Adı geçen bot kısaca özür diler (Gelişmiş kipte dil modeli: sistem istemi ve persona notu; değilse kalıp). Hafızasında yöneticiyle
"uyarildim" olayı. Yöneticiyi selamlayana karşılık verirler; haritada yönetici görünce biri firma sohbetinde söyler (harita başına
YORUM_SN'de bir).
"""
import re, time, unicodedata

import map_links as H
import admin_mode as YM
from . import name_style as NS
from . import speech as SPC

DURATION_MIN = {'sohbet': 30, 'pvp': 240, 'kutu': 1440}
GENERAL = {'sohbet': 30, 'pvp': 60}
COMMENT_SEC = 900
SIGHT = 1600


def _normalize(s):
    s = str(s or '').lower().replace('ı', 'i').replace('ß', 'ss').replace('ł', 'l')
    return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))


def _stem_regex(stems):
    return re.compile(r'(?<!\w)(%s)' % '|'.join(re.escape(_normalize(k)) for k in sorted(stems, key=len, reverse=True)))


# güçlü sözcük tek başına uyarıdır; zayıf olan ("dont", "yapma", "pare") ancak bir konu sözcüğüyle (yöneticinin sıradan sohbeti,
# "dont worry guys", kimseyi cezalandırmasın)
STRONG = _stem_regex([
    'warn', 'ban', 'mute', 'rules', 'last time', 'cut it out', 'not allowed', 'uyari', 'uyariyorum', 'son kez', 'kural', 'sustur',
    'yasak', 'verwarn', 'regel', 'advertencia', 'regla', 'avertissement', 'regle', 'interdit', 'ostrzez', 'zasad', 'aviso', 'regra',
    'proibido', 'предупрежд', 'правил', 'бан', 'нельзя'])
WEAK = _stem_regex([
    'stop', 'quit', 'dont', "don't", 'do not', 'no more', 'behave', 'enough', 'kes', 'yapma', 'yapmayin', 'birak', 'durdur', 'yeter',
    'dikkat edin', 'etme', 'etmeyin', 'olmaz', 'calmayin', 'almayin', 'saldirmayin', 'oldurmeyin', 'yazmayin', 'atmayin', 'hor auf', 'hoer auf', 'hort auf', 'lass das', 'stopp', 'deja', 'dejen', 'basta', 'arrete', 'przestan', 'dosc',
    'pare', 'parem', 'chega', 'прекрат', 'хватит', 'стоп'])
TOPICS = {
    'sohbet': _stem_regex(['spam', 'flood', 'caps', 'insult', 'swear', 'curs', 'toxic', 'rude', 'offensive', 'language', 'chat', 'kufur',
                      'hakaret', 'buyuk harf', 'kaba', 'argo', 'sohbet', 'beleidig', 'schimpf', 'flame', 'insult', 'groser', 'grossier',
                      'obraz', 'wyzwisk', 'xing', 'спам', 'флуд', 'мат', 'оскорб', 'капс', 'чат']),
    'pvp': _stem_regex(['kill', 'attack', 'grief', 'camp', 'newbie', 'noob', 'low level', 'lowbie', 'gank', 'pk', 'oldur', 'saldir', 'kesme',
                   'yeni oyuncu', 'acemi', 'dusuk seviye', 'avla', 'kamp', 'tot', 'angreif', 'neuling', 'anfanger', 'matar', 'atacar',
                   'novato', 'campear', 'tuer', 'attaqu', 'debutant', 'zabija', 'atak', 'nowi', 'nowicjusz', 'kampi', 'campar',
                   'убива', 'атак', 'нович', 'кемп']),
    'kutu': _stem_regex(['box', 'cargo', 'loot', 'steal', 'kutu', 'kargo', 'ganimet', 'cal', 'kiste', 'beute', 'klau', 'stehl', 'caja',
                    'botin', 'robar', 'caisse', 'butin', 'vol', 'skrzyn', 'lup', 'krad', 'caixa', 'saque', 'roub', 'ящик', 'карго',
                    'лут', 'ворова', 'краж']),
}


def topics(text):
    """Uyarı mı -> konuları (boşsa uyarı değil; konusu yoksa {'genel'})."""
    k = _normalize(text)
    talk = {name for name, phrase in TOPICS.items() if phrase.search(k)}
    if STRONG.search(k):
        return talk or {'genel'}
    return talk if WEAK.search(k) else set()


def active(b, topic, now=None):
    """Bot bu konuda yöneticinin uyarısı altında mı."""
    u = b.k.get('uyari') or {}
    return (now or time.time()) < u.get(topic, 0)


def warn(b, talk, now, name=''):
    """Uyarıyı uygula (süreler tekrarla uzar) -> uygulanan konular."""
    u = b.k.setdefault('uyari', {})
    u['sayi'] = n = int(u.get('sayi', 0)) + 1 if now - u.get('son', 0) < 86400 else 1
    u['son'] = now
    multiplier = min(8, 2 ** (n - 1))
    durations = {}
    for k in talk:
        durations.update(GENERAL if k == 'genel' else {k: DURATION_MIN[k]})
    for k, minutes in durations.items():
        u[k] = max(u.get(k, 0), now + minutes * 60 * multiplier)
    if name:
        b.memory.event(name, 'uyarildim', now)
    b.event('yonetici_uyardi', now, konu=','.join(sorted(durations)))
    b.mood.it(moral=-0.05)
    return set(durations)


def note(b, now=None):
    """Persona notu (Gelişmiş kip): yöneticinin süren uyarısı."""
    now = now or time.time()
    u = b.k.get('uyari') or {}
    is_open = [k for k in DURATION_MIN if now < u.get(k, 0)]
    if not is_open:
        return ''
    ne = {'sohbet': 'spamming or rude chat', 'pvp': 'attacking or killing other pilots', 'kutu': "taking other pilots' cargo boxes"}
    return ' The game master warned him about %s %d min ago: he obeys and avoids it.' % (
        ' and '.join(ne[k] for k in is_open), max(1, int((now - u.get('son', now)) // 60)))


def system_note():
    """Sistem istemine (llm.py, agent.py): yönetici varken; yoksa boş (önbellek bozulmaz)."""
    name = YM.name()
    if not name:
        return ''
    return ('\n\nGAME MASTER: %s is a game administrator (GM) of this server: admin badge on the ship, admin colour in chat, may fly '
            'an admin ship (a UFO). Everyone knows it. Be polite to the GM, never insult, threaten or attack them, never argue with '
            'their decisions. When the GM warns about conduct (spam, insults, caps, killing new players, camping, taking others\' '
            'loot), the warned pilot apologizes briefly and stops; others may comment but never mock the warning. Asking the GM for '
            'free items or bans only as an obvious joke. Seeing the GM in space is a small event worth a remark.' % name)


def handle(m, g, now):
    """Sohbet motorunun gelen mesajı (SohbetMotoru.sohbet_isle): yöneticinin uyarısı ya da selamı -> işlendi mi (True: yanıtlar
    burada ya da dil modelinde, kalıplara gitmez)."""
    if g[0] == 'fisilti':
        _, b, msg, who = g
        listener, mentioned, channel = [b], [b], None
    else:
        _, route, msg, who = g
        from .chat_engine import channel_name
        channel = channel_name(route)
        if channel is None:
            return False
        listener = m.listeners(channel, who)
        mentioned = [b for b in listener if NS.is_mentioned(b.name, msg)]
    name = who.get('userId', '')
    if not YM.mi(name_=name):
        return False
    talk = topics(msg)
    if talk:
        target = mentioned or listener
        for b in target:
            warn(b, talk, now, name)
        if m.llm is not None and m.llm.ready:
            return False                                 # dil modeli yanıtlar (persona notu ve sistem istemi)
        for b in (mentioned or [x for x in target if x.r.random() < 0.15])[:2]:
            m.speak(b, channel or 'fisilti', SPC.template(b, 'yonetici_ozur', ad=name), recipient=name if channel is None else None, now=now,
                    priority=True)
        return True
    kind, _ = SPC.intent(msg)
    if kind == 'selam' and channel is not None and not mentioned and (m.llm is None or not m.llm.ready):
        for b in [b for b in listener if b.r.random() < 0.5 + 0.4 * b.o('sosyallik')][:3]:
            m.speak(b, channel, SPC.template(b, 'yonetici_selam', ad=name), now=now, priority=True)
        return True
    return False


def sight_tick(y, now):
    """Haritada yönetici: yakınındaki bir bot firma sohbetinde söyler (harita başına YORUM_SN'de bir)."""
    if not YM.is_open():
        return
    last = y.__dict__.setdefault('_gm_comment', {})
    for w in list(y.worlds):
        if not getattr(w, 'running', False) or not YM.mi(profile=w.p) or now - last.get(w.map_id, 0) < COMMENT_SEC:
            continue
        hx, hy = w.hero_pos(now)
        nearby = [n.bot for n in list(w.npcs.values()) if n.bot is not None and n.alive and
                 ((n.mover.pos(now)[0] - hx) ** 2 + (n.mover.pos(now)[1] - hy) ** 2) ** 0.5 < SIGHT]
        if not nearby:
            continue
        last[w.map_id] = now
        b = max(nearby, key=lambda b: b.o('konuskanlik') * b.r.random())
        b.event('yonetici_gordu', now, harita=H.name(w.map_id))
        y.speak(b, 'firma', SPC.template(b, 'yonetici_gordu', harita=H.name(w.map_id)), now=now)
