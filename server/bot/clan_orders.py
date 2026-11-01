"""Klan emirleri (oyuncu isteği 2026-10-31): klanındaki botlara klan sohbetinden (ya da fısıltıyla) iş verirsin, gerçek bir klan gibi.

  odak    "everyone farm / do quests / go pvp / do gates / sell ore", "herkes görev yapsın"   -> o işe 2 saat ağırlık (beyin niyeti)
  git     "defend 4-4", "3 of you go to 2-4", "herkes 4-5'e"                               -> o haritaya gider, düşmanla dövüşür
  gel     "come help me", "regroup", "recall", "yanıma gelin"                              -> senin haritana gelir
  us      "defend our base / cbs / station"                                                -> klanın istasyonunun haritası (cbs.py)
  al      "get lf-3", "buy iris", "sg3n-b02 alın"                                          -> onu biriktirip alır (alisveris birikim)
  gemi    "use goliath", "fly vengeance", "goliath'a geçin"                               -> o gemiyi biriktirir, alınca uçar; zevki o olur
  yapi    "full shield", "full speed", "balanced"                                          -> jeneratörleri kalkana/hıza dağıtır (kalkan_payi)
  avla    "hunt Kaan", "x destroyed me, find them", "kill <ad>", "<ad>'i avlayın"            -> o kişiyi arar ve saldırır (30 dk)
  klan_odak "focus [TAG]", "prioritize <klan>", "focus clan X over Y"                      -> 2 saat o klanın üyeleri kin gibi öncelik
  dur     "stop", "dismissed", "serbest"                                                   -> emirler kalkar
"N of you" / "3 kişi" sayısı: en sadık N bot. Uyma olasılığı sadakat, sana ilişki ve liderlik (lider sensen) ile; yorgun bot
reddedebilir. Yanıt kısa kalıp (emir_tamam, emir_ret, geliyorum). İzin 'klan_emir'.
"""
import re

import map_links as H
from . import brain as B
from . import catalog as K
from . import speech as SPC

FOCUS_SEC = 7200
GO_SEC = 1800
BASE_SEC = 3600
_NUMBER_WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'bir': 1, 'iki': 2, 'üç': 3, 'uc': 3, 'dört': 4, 'dort': 4,
             'beş': 5, 'bes': 5}
_NUMBER = re.compile(r'\b(\d{1,2}|one|two|three|four|five|bir|iki|üç|uc|dört|dort|beş|bes)\s+(of\s+)?(you|u|ya|guys|kişi\w*|kisi\w*|'
                   r'tane\w*|biriniz|kişiniz)\b', re.I)
_STOP = re.compile(r"\b(stop|dismissed|as you were|at ease|carry on|free now|cancel|nevermind|serbest|bırakın|birakin|dağılın|"
                  r"dagilin|iptal)\b", re.I)
_COME = re.compile(r"\b(come (to me|here|back|help)|help me|regroup|recall|rally|back to me|to me|bana gel\w*|yan[ıi]ma gel\w*|"
                  r"gelin|toplan\w*|yard[ıi]m edin)\b", re.I)
_DEFEND = re.compile(r'\b(defend|protect|guard|hold|savun\w*|koru\w*|go to|go|head to|move to|git\w*|gidin|gelin)\b', re.I)
_US = re.compile(r'\b(base|cbs|station|battle ?station|[üu]s(s[üu]m[üu]z|[üu]m[üu]z|s[üu])?|istasyon\w*)\b', re.I)
_FOCUS = (('gate', re.compile(r'\b(gates?|gg|galaxy gates?|kap[ıi]\w*|alpha|beta|gamma|delta|epsilon|zeta|kappa|lambda|kuiper|'
                             r'hades)\b', re.I)),
         ('quest', re.compile(r'\b(quests?|missions?|g[öo]rev\w*)\b', re.I)),
         ('pvp', re.compile(r'\b(pvp|hunt\w*|enem(y|ies)|kill (players|enemies)|d[üu][şs]man\w*|avla\w*)\b', re.I)),
         ('selling', re.compile(r'\b(sell\w*|ore|cargo|cevher\w*|kargo\w*)\b', re.I)),
         ('mod', re.compile(r'\b(events?|etkinli\w*)\b', re.I)),
         ('grinding', re.compile(r'\b(farm\w*|grind\w*|npcs?|aliens?|uzayl[ıi]\w*|kas[ıi]n|kas[ıi]l\w*|kasma\w*)\b', re.I)))
_LAYOUT = (('kalkan', re.compile(r'\b(full|all|max)\s*(shields?|shd|kalkan)|\b(tam|full)\s*kalkan', re.I)),
         ('speed', re.compile(r'\b(full|all|max)\s*(speed|spd|h[ıi]z)|\b(tam|full)\s*h[ıi]z', re.I)),
         ('baseline', re.compile(r'\b(balanced|half|hybrid|dengeli|yar[ıi] yar[ıi]ya)\b', re.I)))
_SHIP_VERB = re.compile(r'\b(use|fly|switch|ride|change to|kullan\w*|u[çc]un|ge[çc]in|binin)\b', re.I)
_BUY = re.compile(r'\b(get|buy|equip|grab|save (up )?for|al[ıi]n|alsın|biriktir\w*|tak[ıi]n)\b', re.I)
LAYOUT_SHARE = {'kalkan': 0.95, 'speed': 0.3, 'baseline': 0.6}
HUNT_SEC = GO_SEC
CLAN_FOCUS_SEC = FOCUS_SEC
_NAME = r"([\w.\-]{2,20}?)"
_HUNT_EN = re.compile(r"\b(?:hunt|kill|get|find|destroy|attack|chase|murder|take out|go after)\s+(?:down\s+)?(?:the\s+)?(?:player\s+)?([\w.\-]{2,20})", re.I)
_HUNT_EN_PERSON = re.compile(r"\b([\w.\-]{2,20})\s+(?:just\s+)?(?:destroyed|killed|shot|ganked|attacked|blew up|murdered|got)\s+me\b", re.I)
_HUNT_TR = re.compile(_NAME + r"(?:['’][a-zçğıöşü]*)?\s+(?:avla\w*|bulun|bul|öldür\w*|oldur\w*|yakalay\w*|gebert\w*|vurun)\b", re.I)
_HUNT_TR_PERSON = re.compile(_NAME + r"\s+beni\s+(?:öldürdü|oldurdu|vurdu|patlattı|patlatti)\b", re.I)
_HUNT_PERSON_VERB = re.compile(r"\b(destroyed|killed|shot|ganked|attacked|blew up|murdered)\s+me\b|\bbeni\s+(öldürdü|oldurdu|vurdu|"
                           r"patlatt[ıi])", re.I)
_HUNT_VERB = re.compile(r"\b(hunt|kill|get|find|destroy|chase|avla\w*|bulun|bul|öldür\w*|oldur\w*)\b", re.I)
_NOT_NAMES = {'enemies', 'enemy', 'players', 'player', 'aliens', 'alien', 'npcs', 'npc', 'them', 'him', 'her', 'it', 'the', 'all', 'everyone',
           'anyone', 'someone', 'somebody', 'us', 'you', 'me', 'my', 'our', 'some', 'any', 'those', 'these', 'that', 'this', 'down', 'pvp',
           'pve', 'more', 'on', 'in', 'at', 'to', 'out', 'ready', 'up', 'a', 'an', 'one', 'ones', 'now', 'there', 'here', 'lf-3', 'beni',
           'onu', 'onlari', 'hepsini', 'herkesi', 'dusmanlari', 'düşmanları', 'bir', 'bunu', 'şunu', 'sunu', 'bu', 'o', 'şu', 'su'}
_CLAN_FOCUS = re.compile(r"\b(focus|prioriti[sz]e|target|go for|[öo]ncelik\w*|odaklan\w*|hedef al\w*)\b", re.I)
_CLAN_AFTER = re.compile(r"\b(over|instead of|rather than|before|not|then|yerine|ya[çc]|ama)\b", re.I)


def hunt_name(s, known=None, names=()):
    """Av emrindeki kişi adı ("hunt Kaan", "x destroyed me, find them", "Kaan'ı avlayın") ya da None. bilinen(ad): öyle biri var mı
    (olağan sohbet "herkes düşman avlasın" emir sanılmasın diye; verilmezse her ad kabul). adlar: çevrimiçi bilinen adlar; av fiili
    varken metinde geçen en uzun ad (oyuncu adlarında #, *, (), boşluk, sembol olur: "#Platonik", "亗TÜRK亗"; canlı 2026-11-01)."""
    candidates = [m.group(1) for rx in (_HUNT_EN, _HUNT_TR) for m in rx.finditer(s)]
    verb = _HUNT_VERB.search(s) or _HUNT_PERSON_VERB.search(s)
    if _HUNT_VERB.search(s):
        candidates += [m.group(1) for rx in (_HUNT_EN_PERSON, _HUNT_TR_PERSON) for m in [rx.search(s)] if m]
    for a in candidates:
        if a.lower() not in _NOT_NAMES and not SPC.MAP_RE.fullmatch(a) and (known is None or known(a)):
            return a
    if verb:
        lower = s.lower()
        for a in sorted((str(x) for x in names if len(str(x).strip()) >= 3), key=len, reverse=True):
            i = lower.find(a.lower())
            if i >= 0 and not (i and lower[i - 1].isalnum()) and not lower[i + len(a):i + len(a) + 1].isalnum():
                return a
    return None


def find_clan(s, own=None):
    """Metinde geçen klan (etiket [TAG] ya da adı), "X over Y" ise X; kendi klanın hariç -> klan kaydı ya da None."""
    import clan as KL
    after = _CLAN_AFTER.search(s)
    s = s[:after.start()] if after and after.start() > 2 else s
    en = None
    with KL.LOCK:
        clans = [c for c in KL.CLANS.values() if c['id'] != own]
    for c in clans:
        for rx in (r'\[\s*%s\s*\]' % re.escape(c.get('tag', '') or '\0'),
                   (r'(?<![\w])%s(?![\w])' % re.escape(c['tag'])) if len(c.get('tag', '')) >= 3 else None,
                   (r'(?<![\w])%s(?![\w])' % re.escape(c['name'])) if len(c.get('name', '')) >= 3 else None):
            m = re.search(rx, s, re.I) if rx else None
            if m and (en is None or m.start() < en[0]):
                en = (m.start(), c)
    return en[1] if en else None


def _items():
    """Kısa ad -> loot: "lf-3", "sg3n-b02", "iris", "goliath" (tasarımsız gemiler)."""
    out = {}
    for group in ('lasers', 'shield_generators', 'speed_generators', 'drones'):
        for loot in K.ITEMS[group]:
            out.setdefault(loot.rsplit('_', 1)[-1].lower(), loot)
    for loot in K.ships():
        out.setdefault(loot[len('ship_'):].lower(), loot)
    return out


_ITEMS = None


def find_item(text):
    global _ITEMS
    if _ITEMS is None:
        _ITEMS = _items()
        _ITEMS['rx'] = re.compile(r'(?<![\w-])(%s)(?![\w-])' % '|'.join(re.escape(k) for k in sorted(_ITEMS, key=len, reverse=True)), re.I)
    m = _ITEMS['rx'].search(text)
    return _ITEMS[m.group(1).lower()] if m else None


def parse(text, own_clan=None, known=None, names=()):
    """Klan emri -> {'tur', 'harita'?, 'hedef'?, 'esya'?, 'yapi'?, 'sayi'?} ya da None (emir değil: olağan sohbet). kendi_klan: emri
    verenin klanı (klan odağında hariç); bilinen: av emrindeki adın varlığını sınayan işlev (av_adi)."""
    s = str(text or '')
    if s.rstrip().endswith('?'):
        return None                                      # soru emir değil ("gates?" "kim kapı yapar?")
    m = _NUMBER.search(s)
    count = (int(m.group(1)) if m.group(1).isdigit() else _NUMBER_WORDS.get(m.group(1).lower())) if m else None
    e = {'number': count} if count else {}
    hm = SPC.MAP_RE.search(s)
    game_map = ('%s-%s' % (hm.group(1), hm.group(2).upper() if hm.group(2).isalpha() else hm.group(2))) if hm else None
    if _STOP.search(s):
        return dict(e, type='halt')
    for name, rx in _LAYOUT:
        if rx.search(s):
            return dict(e, type='structure', structure=name)
    item = find_item(s) if _BUY.search(s) or _SHIP_VERB.search(s) else None     # "nice goliath" emir değil
    if item:
        return dict(e, type='ship' if item.startswith('ship_') else 'al', item=item)
    if _CLAN_FOCUS.search(s):
        c = find_clan(s, own_clan)
        if c is not None:
            return dict(e, type='clan_focus', clan=c['id'])
    hunt = hunt_name(s, known, names)
    if hunt:
        return dict(e, type='hunt', target=hunt)
    if _DEFEND.search(s) and _US.search(s) and not game_map:
        return dict(e, type='us')
    if _COME.search(s) and not game_map:
        return dict(e, type='come')
    if game_map and (_DEFEND.search(s) or _COME.search(s) or re.search(r"\b(everyone|all|herkes|hepiniz)\b", s, re.I)):
        return dict(e, type='git', map=game_map)
    if re.search(r'\b(focus|everyone|all|go|let\'?s|herkes|hepiniz|odaklan\w*|yap[ıi]n|gidin)\b', s, re.I):
        for name, rx in _FOCUS:
            if rx.search(s):
                return dict(e, type='focus', target=name)
    return None


def base_map(profile):
    """Klanın kurulu (ya da kurulmakta olan) istasyonunun haritası ya da None."""
    import cbs as CB
    import clan as KL
    k = KL.clan_of(profile)
    for source in (CB.shared(), profile):
        if source is None:
            continue
        for aid, a in ((source.d.get('cbs') or {}).get('asteroids') or {}).items():
            if (isinstance(a, dict) and a.get('owner') != 'rival' and a.get('state') in ('built', 'building')
                    and a.get('clan') in (None, (k or {}).get('id'))):
                ast = CB.ASTEROIDS.get(int(aid))
                if ast:
                    return int(ast['map'])
    return None


def will_obey(b, name, leader, now):
    p = 0.45 + 0.4 * b.o('loyalty') + 0.4 * b.memory.relation(name, now) + (0.15 if leader else 0) - 0.25 * b.mood['fatigue']
    return b.r.random() < p


def apply(y, b, e, name, person, now):
    """Bir botta emir -> (kalıp, alanlar). Uymadıysa ('emir_ret', {})."""
    kind = e['type']
    if kind == 'halt':
        b.k['intent'] = None
        b.k.pop('order', None)
        b.k.pop('hunt_order', None)
        b.k.pop('clan_focus', None)
        b.next_decision = now
        return 'order_done', {}
    if kind == 'structure':
        b.k['structure'] = e['structure']
        b.loadout_changed()
        return 'order_done', {}
    if kind in ('al', 'ship'):
        if b.k['gear'].get('ship') == e['item']:
            return 'order_done', {}
        b.k['savings'] = e['item']                      # alışveriş yalnız onu biriktirir (alisveris.aday)
        b._candidates = None
        if kind == 'ship':
            family = e['item'][len('ship_'):].split('-')[0]
            b.k['personality']['taste'] = family               # bundan sonra o gemi ailesini sever
        b.k['order'] = {'type': kind, 'item': e['item'], 'who': name, 't': now}
        return 'order_done', {}
    if kind == 'focus':
        B.force(b, e['target'], plan={}, pay=1.3, duration=FOCUS_SEC, now=now)
        b.k['order'] = {'type': 'focus', 'target': e['target'], 'who': name, 't': now}
        return 'order_done', {}
    if kind == 'hunt':
        from .goals import pvp as PV
        t = PV.find_target(y, e['target'])
        if t is None or t[0].lower() == name.lower() or t[0].lower() == b.name.lower():
            return 'order_refuse', {}
        if t[1] == b.firma:
            return 'duel_same', {}                    # kendi firmasına saldıramaz
        if t[3] is not None and t[3] == b.k.get('clan'):
            return 'order_refuse', {}                       # klan arkadaşı
        if not y.permission('pvp') or t[4] and not y.permission('attack_player') or b.level < (y.setting('pvp_level', 6) or 1):
            return 'order_refuse', {}
        b.k['hunt_order'] = {'name': t[0].lower(), 'end_time': now + HUNT_SEC, 'who': name}
        B.force(b, 'pvp', plan={}, pay=1.6, duration=HUNT_SEC, now=now)
        return 'order_hunt', {'name': t[0]}
    if kind == 'clan_focus':
        import clan as KL
        c = KL.CLANS.get(e['clan'])
        if c is None or c['id'] == b.k.get('clan') or b.level < (y.setting('pvp_level', 6) or 1) or not y.permission('pvp'):
            return 'order_refuse', {}
        b.k['clan_focus'] = {'clan': c['id'], 'end_time': now + CLAN_FOCUS_SEC, 'who': name}
        B.force(b, 'pvp', plan={}, pay=1.0, duration=CLAN_FOCUS_SEC, now=now)
        return 'order_clan_focus', {'clan': c.get('tag') and '[%s]' % c['tag'] or c['name']}
    m = None
    if kind == 'git':
        from .agent_tools import _game_map
        m = _game_map(e['map'])
    elif kind == 'come':
        m = int(person.profile.d['position'].get('mapId', 0)) if person is not None else None
    elif kind == 'us':
        m = base_map(person.profile) if person is not None else None
        if m is None:
            return 'order_no_base', {}
    if not m or m not in K.MAPS or not K.can_enter(m, b.firma, b.level) or not K.route(b.game_map, m, b.firma, b.level):
        return 'cant_come', {}
    B.force(b, 'assist', plan={'map': int(m), 'name': name}, pay=1.6, duration=BASE_SEC if kind == 'us' else GO_SEC, now=now)
    b.memory.event(name, 'i_helped', now)
    return 'coming', {'map': H.name(m)}


def handle(y, channel, msg, who, listener, now):
    """Sohbet motorundan: klan kanalındaki (ya da bota fısıltıdaki) mesaj klan emriyse uygular ve yanıtlatır -> işlendi mi."""
    if not y.permission('clan_order') or channel not in ('clan', 'whisper'):
        return False
    import clan as KL
    import community as TP
    from .goals import pvp as PV
    name = who.get('userId', '')
    person = TP.find(name=name)
    kl = KL.clan_of(person.profile) if person is not None else None
    if kl is None or name.lower() in y.name_index:
        return False
    names = [b.name for b in y.bots if b.online] + [k.name for k in TP.all_().values()]
    e = parse(msg, kl['id'], lambda a: PV.find_target(y, a) is not None, names)
    if e is None:
        return False
    members = [b for b in listener if b.k.get('clan') == kl['id'] and b.online and b.dead_until <= now]
    if not members:
        return False
    leader = kl['leader'] == name.lower()
    order = sorted(members, key=lambda b: -(b.o('loyalty') + b.memory.relation(name, now)) * b.r.uniform(0.8, 1.2))
    accept = 0
    for i, b in enumerate(order):
        if e.get('number') and accept >= e['number']:
            break
        if e['type'] == 'halt' or will_obey(b, name, leader, now):
            template, area = apply(y, b, e, name, person, now)
            accept += template not in ('cant_come', 'duel_same')
        else:
            template, area = 'order_refuse', {}
        if i < 4 or template == 'coming':                 # herkes yazmaz: ilk birkaçı ve yola çıkanlar
            y.speak(b, 'whisper' if channel == 'whisper' else 'clan', SPC.template(b, template, **area), recipient=name if channel == 'whisper' else None,
                    now=now + b.r.uniform(0.5, 3) * (i + 1), priority=True)
    y.log('   botlar: klan emri %s: %s -> %d/%d bot' % (name, e, accept, len(members)))
    return True
