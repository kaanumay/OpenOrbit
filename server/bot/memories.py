"""Botların anı defteri (Gelişmiş kip, güçlü sağlayıcı: llm.GUCLU): kişilerle yaşanan önemli olaylar kısa notlar olarak, kayıtta kalıcı.

Generative Agents (Park ve ark. 2023) düzeni: anı akışı (önem x tazelikle seçilir), kişi başına izlenim (yansıma) ve anılardan doğan
sonuçlar (takip). Kayıtta:
  k['anilar']   [{t, kim, ozet, tur, duygu (-1..1), onem (1-3), n, takip}]; ozet modele giden İngilizce not ("Kaan shot me down on 2-4")
  k['izlenim']  {kim_kucuk: {ad, metin, t}}: kişi hakkında yoğun kanı (konuşma özetiyle model günceller)
takip: {amac (soz | intikam | tesekkur | rekabet | merak), vade (an), arac (yok | takip_et | grup_davet | duello | yardima_git), harita,
bitti}. Vakti gelen ve iki taraf da çevrimiçiyse llm.Beyin botun ağzından konuyu açar, aracı çalıştırır (vadesi_gelenler).

Kaynaklar: oyunun olayları (Hafiza.olay -> olaydan, şablonla; yalnız gerçek oyuncularla), konuşma sonunda modelin özeti (llm._ani_ozet)
ve botlar arası dedikodu (duydum). Botlarla bot arasındaki olaylar anı olmaz (çok olur, oyuncu görmez).
"""
import time

MAX_MEMORIES = 60                      # bot başına anı (en az değerli olan düşer)
MERGE_SEC = 1800              # aynı kişiyle aynı türden olay bu süre içinde tekrarlanırsa sayılır ("x3")
GRACE_SEC = 6 * 3600            # takibin vadesi geçince bu kadar bekler (kişi çevrimiçi olmadıysa unutulur)
PURPOSES = ('soz', 'intikam', 'tesekkur', 'rekabet', 'merak')
FOLLOWUP_TOOLS = ('none', 'follow', 'group_invite', 'duello', 'go_help')

# oyun olayı -> (not, tür, duygu, önem); {ad} oyuncu
TEMPLATE = {
    'killed_me': ('{ad} shot me down', 'savas', -0.6, 2),
    'oldurdum': ('I shot down {ad}', 'savas', 0.2, 1),
    'helped_me': ('{ad} came to help me', 'yardim', 0.6, 2),
    'i_helped': ('I flew over to help {ad}', 'yardim', 0.3, 1),
    'grup': ('grouped up with {ad}', 'grup', 0.3, 1),
    'hakaret': ('{ad} insulted me', 'hakaret', -0.4, 1),
    'meydan': ('{ad} challenged me to a duel', 'savas', 0.0, 2),
    'arkadas': ('became friends with {ad}', 'friendly', 0.6, 2),
    'klan': ('{ad} and I ended up in the same clan', 'friendly', 0.4, 2),
}


def memories(b):
    return b.k.setdefault('memories', [])


def impressions(b):
    return b.k.setdefault('impression', {})


def _value(a, now):
    """Anının ağırlığı: önem x tazelik (yarı ömür bir gün; tekrar eden olay biraz daha ağır)."""
    return a['importance'] * (1 + 0.15 * min(5, a.get('n', 1) - 1)) * 0.5 ** (max(0, now - a['t']) / 86400)


def add(b, who, summary, kind='not', emotion=0.0, importance=1, now=None, followup=None, merge=True):
    """Anı ekle; aynı kişiyle aynı türden yakın olay sayılır. -> anı."""
    now = now if now is not None else time.time()
    mems = memories(b)
    k = str(who).lower()
    if merge:
        for a in reversed(mems):
            if a['kim'].lower() == k and a['tur'] == kind and a['summary'] == summary and now - a['t'] < MERGE_SEC:
                a['n'] = a.get('n', 1) + 1
                a['t'] = now
                if followup and not a.get('takip'):
                    a['takip'] = followup
                return a
    a = {'t': now, 'kim': str(who), 'summary': str(summary)[:200], 'tur': kind, 'emotion': round(max(-1.0, min(1.0, float(emotion))), 2),
         'importance': max(1, min(3, int(importance))), 'n': 1, 'takip': followup}
    mems.append(a)
    if len(mems) > MAX_MEMORIES:
        is_open = [x for x in mems if x.get('takip') and not x['takip'].get('finished')]
        candidate = [x for x in mems if x not in is_open] or mems
        mems.remove(min(candidate, key=lambda x: _value(x, now)))
    return a


def time_ago(dt):
    dt = max(0, dt)
    if dt < 120:
        return 'just now'
    if dt < 3600:
        return '%d min ago' % (dt // 60)
    if dt < 86400:
        return '%d h ago' % (dt // 3600)
    return '%d days ago' % (dt // 86400)


def _line(a, now):
    return '%s (%s%s)' % (a['summary'], time_ago(now - a['t']), ', x%d' % a['n'] if a.get('n', 1) > 1 else '')


def recall(b, who, now, n=6):
    """Kişiyle en değerli n anı, eskiden yeniye."""
    k = str(who).lower()
    mems = [a for a in memories(b) if a['kim'].lower() == k]
    return sorted(sorted(mems, key=lambda a: -_value(a, now))[:n], key=lambda a: a['t'])


def text(b, who, now):
    """İsteme: kişi hakkındaki izlenim ve anılar (yoksa '')."""
    out = ''
    trace = impressions(b).get(str(who).lower())
    if trace and trace.get('metin'):
        out += ' Your impression of %s: %s.' % (trace['ad'], trace['metin'].rstrip('.'))
    mems = recall(b, who, now)
    if mems:
        out += ' Your memories with %s: %s.' % (mems[-1]['kim'], '; '.join(_line(a, now) for a in mems))
    is_open = [a['takip'] for a in mems if a.get('takip') and not a['takip'].get('finished')]
    if is_open:
        out += ' Still pending with him: %s.' % ', '.join(PURPOSE_NAME[t['amac']] for t in is_open)
    return out


PURPOSE_NAME = {'soz': 'a plan you agreed on', 'intikam': 'you want revenge', 'tesekkur': 'you owe him thanks', 'rekabet': 'a rivalry',
           'merak': 'something you wanted to ask him'}


def important(b, now, n=3, humans=None):
    """Botun en değerli anıları (kişi fark etmeksizin; insanlar verilirse yalnız onlarla)."""
    mems = [a for a in memories(b) if humans is None or a['kim'].lower() in humans]
    return sorted(mems, key=lambda a: -_value(a, now))[:n]


def write_impression(b, who, text_, now):
    if text_ and str(text_).strip():
        impressions(b)[str(who).lower()] = {'ad': str(who), 'metin': str(text_).strip()[:240], 't': now}


def set_followup(purpose, now, minutes=10, tool='none', game_map=''):
    if purpose not in PURPOSES:
        return None
    return {'amac': purpose, 'due': now + max(1, min(240, int(minutes or 10))) * 60, 'tool': tool if tool in FOLLOWUP_TOOLS else 'none',
            'harita': str(game_map or '')[:8], 'finished': False}


# ------------------------------------------------------------------------------------------------------------ oyun olayları
def is_human(y, name):
    """Gerçek oyuncu mu (bot ya da uzaylı değil)."""
    if not name or str(name).lower() in getattr(y, 'name_index', {}):
        return False
    try:
        import community as TP
        return TP.find(name=name) is not None
    except Exception:
        return False


def from_event(y, b, name, kind, now=None):
    """Hafiza.olay'ın kancası: oyuncuyla yaşanan önemli olay anı olur; bazıları sonuç doğurur (intikam, teşekkür)."""
    from . import llm
    if not llm.STRONG or kind not in TEMPLATE or not is_human(y, name):
        return None
    now = now if now is not None else y.now
    summary, t, emotion, importance = TEMPLATE[kind]
    a = add(b, name, summary.format(ad=name), t, emotion, importance, now)
    if a.get('takip'):
        return a
    if kind == 'killed_me' and a['n'] >= 2 and b.o('aggression') > 0.45 and _firma(name) not in (0, b.firma) and b.permission.get('pvp', True):
        a['takip'] = set_followup('intikam', now, b.r.uniform(3, 15), 'duello')             # iki kez vurduysa: intikam
    elif kind == 'helped_me' and b.r.random() < 0.4 + 0.5 * b.o('sociability'):
        a['takip'] = set_followup('tesekkur', now, b.r.uniform(2, 8))
    elif kind == 'hakaret' and a['n'] >= 2 and b.o('rekabet') > 0.5:
        a['takip'] = set_followup('rekabet', now, b.r.uniform(5, 30))
    return a


def _firma(name):
    try:
        import community as TP
        k = TP.find(name=name)
        return int(k.profile.d['pilot'].get('factionId', 0)) if k is not None else 0
    except Exception:
        return 0


def due_followups(y, now, online):
    """[(bot, anı)]: vakti gelmiş, bitmemiş takipler (bot ve kişi çevrimiçi). Süresi çok geçenler bitti sayılır."""
    out = []
    for b in y.bots:
        for a in memories(b):
            t = a.get('takip')
            if not t or t.get('finished') or now < t['due']:
                continue
            if now - t['due'] > GRACE_SEC:
                t['finished'] = True                         # fırsat kaçtı
                continue
            if b.online and b.dead_until <= now and a['kim'].lower() in online:
                out.append((b, a))
    return out


# ------------------------------------------------------------------------------------------------------------ dedikodu
def pick_gossip(b, now, r):
    """Botların kendi sohbetinde anlatılacak bir oyuncu anısı (önemli, bir günden taze) ya da None."""
    mems = [a for a in memories(b) if a['importance'] >= 2 and now - a['t'] < 86400 and a['tur'] != 'heard']
    return r.choice(mems) if mems else None


def hear_gossip(listener, narrator, a, now):
    """Dedikoduyu duyan bot: kişiye ilişkisi hafifçe değişir, düşük önemli "duydum" anısı."""
    listener.memory.event(a['kim'], 'gossip_good' if a['emotion'] > 0.1 else 'gossip_bad' if a['emotion'] < -0.1 else 'sohbet', now)
    add(listener, a['kim'], 'heard from %s: %s' % (narrator.name, a['summary']), 'heard', a['emotion'] * 0.5, 1, now)
