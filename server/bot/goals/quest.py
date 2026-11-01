"""Görev: oyunun görev zincirinden (quests.json) uzaylı öldürme / oyuncu öldürme / harita ziyareti görevlerini almak ve bitirmek.

Bot görev vericiden seviyesine uygun, ön koşulları tamam, bitirmediği görevi alır; koşulların haritasına gidip istenen uzaylıyı
kovalar. Ödüller görevin kendi ödülleri (currency_credits, currency_experience, currency_uridium, currency_honour ve eşyalar).
Görev verisi değişince (Dünya Editörü) botlar yenisini kendiliğinden kullanır.
"""
from ..brain import Goal, target
from .. import catalog as K
from .. import abstract_sim as S

KILL_NPC, KILL_PLAYERS, VISIT_MAP, ON_MAP, HOME = 6, 28, 34, 77, 62
SUPPORTED = {KILL_NPC, KILL_PLAYERS, VISIT_MAP, HOME}
_quests = None
_id_type = None


def quests():
    """id -> {seviye, onceki, kosullar [{id, tur, hedef, eslesme, haritalar (belirteçler)}], oduller}: yalnız botun yapabildikleri."""
    global _quests, _id_type
    if _quests is None:
        import quest as QU
        _id_type = {}
        for tip, t in K.NPC['tipler'].items():
            _id_type.setdefault(str(t.get('npc_kimlik', '')), []).append(tip)
        out = {}
        for qid, q in QU.QUESTS.items():
            if q.get('turler') != [2] or q.get('sure_sn'):
                continue
            conditions = []
            ok = True
            for el in q['kok'].get('modifier', []):
                c = el.get('condition')
                if not c or c['type'] not in SUPPORTED:
                    ok = False
                    break
                maps = [m for s in c.get('subConditions', []) if s.get('type') == ON_MAP for m in s.get('matches', [])]
                if any(s.get('type') not in (ON_MAP,) for s in c.get('subConditions', [])):
                    ok = False
                    break
                conditions.append(dict(id=c['id'], tur=c['type'], hedef=int(c.get('targetValue', 1)), eslesme=list(c.get('matches', [])),
                                haritalar=maps))
            package = any(str(l).startswith('ship_') or (l == 'currency_uridium' and n >= 10000) for l, n in q.get('oduller', []))
            if ok and conditions and not package:            # hoş geldin paketi (gemi, binlerce uridyum): botlar herkes gibi sıfırdan
                out[int(qid)] = dict(seviye=int(q.get('seviye', 0)), onceki=[int(x) for x in q.get('onceki', [])], kosullar=conditions,
                                     oduller=q.get('oduller', []), ad=q.get('ad', ''), sirali=q['kok'].get('ordered', False))
        _quests = out
    return _quests


def map_list(spec, firma):
    import quest as QU
    try:
        return [int(m) for m in QU.maps_for(str(spec).lstrip('@'), firma) if int(m) in K.MAPS]
    except (KeyError, ValueError, TypeError):
        return []


def npc_types(uid):
    quests()
    return _id_type.get(str(uid), [])


def eligible(bot):
    """Botun şimdi alabileceği görevler (seviyeye yakın olanlar önce)."""
    done = set(bot.k['tamam'])
    deferred = bot.k.get('ertelenen') or {}
    out = []
    for qid, q in quests().items():
        if qid in done or deferred.get(str(qid), 0) >= bot.level or q['seviye'] > bot.level or any(x not in done and x in quests() for x in q['onceki']):
            continue
        out.append((qid, q))
    out.sort(key=lambda x: (-x[1]['seviye'], x[0]))
    return out


def next_up(bot):
    """Süren görevin sıradaki bitmemiş koşulu -> (koşul, haritalar) ya da None."""
    g = bot.k.get('gorev')
    if not g:
        return None
    q = quests().get(g['id'])
    if not q:
        bot.k['gorev'] = None
        return None
    for c in q['kosullar']:
        if g['kosullar'].get(str(c['id']), 0) < c['hedef']:
            maps = [m for h in c['haritalar'] for m in map_list(h, bot.firma)]
            if c['tur'] == VISIT_MAP:
                maps = [m for h in c['eslesme'] for m in map_list(h, bot.firma)]
            elif c['tur'] == HOME:
                maps = [K.ev(bot.firma)]
            elif c['tur'] == KILL_NPC and not maps:
                # haritası verilmemiş: o uzaylının çıktığı, girebildiği en yakın harita
                types = {t for k in c['eslesme'] for t in npc_types(k)}
                maps = [m for m in K.MAPS if K.can_enter(m, bot.firma, bot.level)
                        and any(v['tip'] in types for v, _ in K.map_npcs(m))]
            maps = [m for m in maps if K.can_enter(m, bot.firma, bot.level)]
            return c, maps
        if q['sirali']:
            continue
    return None


def advance(bot, kind, n=1, npc_id=None, game_map=None, y=None):
    """Olay görevi ilerletir (kasılmada öldürülen uzaylı, PvP, harita girişi) -> görev bitti mi."""
    g = bot.k.get('gorev')
    if not g:
        return False
    q = quests().get(g['id'])
    if not q:
        return False
    for c in q['kosullar']:
        key = str(c['id'])
        if g['kosullar'].get(key, 0) >= c['hedef']:
            continue
        if c['tur'] != kind:
            if q['sirali']:
                break
            continue
        if kind == KILL_NPC and npc_id is not None and str(npc_id) not in c['eslesme']:
            continue
        maps = [m for h in c['haritalar'] for m in map_list(h, bot.firma)]
        if kind == VISIT_MAP:
            maps = [m for h in c['eslesme'] for m in map_list(h, bot.firma)]
        elif kind == HOME:
            maps = [K.ev(bot.firma)]
        if maps and game_map not in maps:
            continue
        g['kosullar'][key] = min(c['hedef'], g['kosullar'].get(key, 0) + n)
        if q['sirali']:
            break
    if all(g['kosullar'].get(str(c['id']), 0) >= c['hedef'] for c in q['kosullar']):
        finish(bot, q, y)
        return True
    return False


def finish(bot, q, y):
    speed = y.speed(bot) if y is not None else 1.0
    currency = dict(currency_credits='kredi', currency_experience='ep', currency_uridium='uridyum', currency_honour='onur')
    earned = {}
    for loot, n in q['oduller']:
        if loot in currency:
            earned[currency[loot]] = earned.get(currency[loot], 0) + n
        else:
            bot.add(loot, n)
    bot.reward('gorev', speed, **earned)
    bot.k['tamam'].append(bot.k['gorev']['id'])
    bot.k['gorev'] = None
    bot.ist('gorev')
    bot.mood.it(moral=0.15, sikilma=-0.2)
    bot.event('gorev_bitti', ad=q['ad'])


def deferred(bot):
    """Görev şimdilik yapılamıyor (istenen uzaylıya gücü yetmiyor): bırakılır, bir seviye atlayınca yeniden denenir (gerçek
    oyuncu da görevi iptal edip sonra döner)."""
    g = bot.k.get('gorev')
    if g:
        bot.k.setdefault('ertelenen', {})[str(g['id'])] = bot.level
        bot.k['gorev'] = None
    bot.plan['bitti'] = True


@target
class Quest(Goal):
    name = 'gorev'
    permission = 'gorev'
    min_sec = 240

    def eligible(self, bot, b):
        if bot.k.get('gorev'):
            s = next_up(bot)
            return bool(s and s[1])
        return bool(eligible(bot))

    def points(self, bot, b):
        o = bot.traits
        p = 0.45 + 0.35 * o['hirs'] * o['sabir'] + (0.35 if bot.archetype == 'gorevci' else 0)
        if bot.k.get('gorev'):
            p += 0.15                     # yarım görev çeker
        from .. import weapons as WP
        if not WP.has_laser(bot):
            p *= 0.3                                      # görevlerin çoğu öldürme ister: cephanesiz ilerlemez
        return p * (1 - 0.3 * bot.mood['sikilma'])

    def start(self, bot, b):
        if not bot.k.get('gorev'):
            for qid, q in eligible(bot)[:6]:
                bot.k['gorev'] = dict(id=qid, kosullar={})
                s = next_up(bot)
                if s and s[1]:
                    break
                bot.k['gorev'] = None
            if not bot.k.get('gorev'):
                bot.plan['bitti'] = True
                return
            bot.event('gorev_aldi', ad=quests()[bot.k['gorev']['id']]['ad'])
        self._head_to(bot, b.y, b.now)

    def _head_to(self, bot, y, now=None):
        s = next_up(bot)
        if not s or not s[1]:
            bot.plan['bitti'] = True
            return
        c, maps = s
        types = [t for k in c['eslesme'] for t in npc_types(k)] if c['tur'] == KILL_NPC else []
        if types:
            # gücünün yettiği (öldürmeye cesaret ettiği) haritalar; hiçbiri yoksa görev güçlenene dek bekler
            d = bot.value()
            maps = [m for m in maps if set(types) & set(K.evaluate_map(m, d['dps'], d['ehp'], 0.8)['hedefler'])]
            if not maps:
                deferred(bot)
                return
        target_map = min(maps, key=lambda m: len(K.route(bot.game_map, m, bot.firma, bot.level) or range(99)))
        bot.plan['kosul'] = c['id']
        bot.plan['harita'] = target_map
        bot.plan['tip'] = next((v['tip'] for v, _ in K.map_npcs(target_map) if v['tip'] in types), None)
        S.go(bot, target_map, y, now)

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        s = next_up(bot)
        if not s:
            bot.plan['bitti'] = True
            return
        c, maps = s
        if c['id'] != bot.plan.get('kosul') or bot.game_map not in maps:
            self._head_to(bot, y)
            return
        if c['tur'] in (VISIT_MAP, HOME):
            if bot.plan.get('ziyaret') != (c['id'], bot.game_map):        # varışta bir kez (her soyut adımda sayılıyordu)
                bot.plan['ziyaret'] = (c['id'], bot.game_map)
                advance(bot, c['tur'], game_map=bot.game_map, y=y)
        elif c['tur'] == KILL_PLAYERS:
            S.farm(bot, dt, y)             # PvP koşulu: haritada dolaşırken karşılaşmalar (yonetici.pvp_tick) sayar
        else:
            S.farm(bot, dt, y, target_kind=bot.plan.get('tip'))

    def finished(self, bot, b):
        return bot.plan.get('bitti', False) or (not bot.k.get('gorev') and 'kosul' in bot.plan)
