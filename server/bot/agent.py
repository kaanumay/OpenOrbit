"""Botun ajanı (Gelişmiş kip, güçlü sağlayıcı: llm.GUCLU): model, Claude Code'un araç döngüsü gibi oyunu araçlarla oynar.

Her düşünme anında (dusun) model adım adım ilerler: kısa düşünce -> bir araç -> aracın sonucu -> sonraki adım; en çok
llm_ajan_adim adım, "bitir" ile biter. Araçlar üç türlü:
  gözlem    salt okunur: durum, haritalar, magaza, gorevler, etkinlikler, cevre, klan, defter, anilar (bakmadan karar vermesin)
  eylem     agent_tools.py'nin araçları (hedef niyetleri, alışveriş, görev, mod, kapı, sosyal ...): paketin izinleri aynen geçerli
  kendini yönetme: defter (uzun vadeli hedefler), hatirlat (kendini N dakika sonra uyandırır), not_al (anı defterine not)
Karar araçları kurallı karar motoruna güçlü niyet olarak gider (beyin.zorla): uçuş, savaş ve ayrıntı yine govde/soyut'ta.

Ne zaman düşünür (llm.Beyin._ajan_tick): llm_karar_dk'da bir; önemli olayda (öldü, seviye, görev bitti, yeni gemi, kargo doldu,
biriktirdiği para tamam) ve hatırlatıcının vakti gelince. Saatlik istek sınırı (llm_saatlik) aşılınca kurallı motor sürer.
Botun son adımları k['ajan']'da (izlemek için), defter k['defter'], hatırlatıcılar k['hatirlatici'].
"""
import json, time

import map_links as H
import player_profile as PF
from . import memories as MEM
from . import agent_tools as TL
from . import brain as B
from . import catalog as K

STEPS = 3                         # düşünme başına en çok istek (adımda birden çok araç)
WAKE_EVENTS = {'olum': 'you just got shot down', 'seviye': 'you just reached a new level', 'quest_done': 'you just finished a quest',
             'yeni_gemi': 'you just got a new ship', 'i_killed_player': 'you just shot down a player'}
NOTEBOOK_MAX = 8


# ------------------------------------------------------------------------------------------------------------ gözlem
def _fmt_money(n):
    return '{:,}'.format(int(n))


def _short(loot):
    return str(loot).rsplit('_', 1)[-1]


def observe_status(y, b, arg):
    from .goals import quest as QU, shopping as SHOP
    from . import weapons as WP
    d = b.value()
    PF.level_for(0)                                      # seviye eşikleri yüklensin
    next_ = next((need for lv, need in (PF._LEVELS or []) if lv == b.level + 1), None)
    out = ['Level %d (EP %s%s). Ship %s, power %.0f (damage/s %.0f, effective HP %.0f).' % (
        b.level, _fmt_money(b.k['ep']), (' / next level at %s' % _fmt_money(next_)) if next_ else '', _short(b.k['gear']['gemi']), d['power'],
        d['dps'], d['ehp']),
        'Credits %s, uridium %s, honor %s. Cargo %d%% full.' % (_fmt_money(b.k['kredi']), _fmt_money(b.k['uridyum']), _fmt_money(b.k['onur']),
                                                              100 * b.cargo_fill()),
        'Ammo: %s.' % ', '.join('%s x%s' % (_short(k), _fmt_money(v)) for k, v in sorted(WP.stock(b).items(), key=lambda x: -x[1])[:5] if v)]
    target = b.target.name if b.target is not None else 'nothing'
    out.append('On map %s, doing: %s for %d min.' % (H.name(b.game_map), target, max(0, y.now - b.goal_start) // 60))
    out.append("You fly for %s: %d-x maps are your company's, 4-x maps are shared PvP land, the other companies' maps are enemy "
               "land." % (('MMO', 'EIC', 'VRU')[b.firma - 1], b.firma))
    if not _laser(b):
        out.append('You have NO laser ammo: you cannot fight until you get some (credits) or sell cargo.')
    g = b.k.get('gorev')
    if g:
        q = QU.quests().get(g['id'], {})
        s = QU.next_up(b)
        out.append('Quest: %s%s.' % (q.get('ad', '?'), (' (next step on %s)' % ', '.join(H.name(m) for m in s[1][:3])) if s and s[1] else ''))
    _, savings = SHOP.candidate(b)
    if b.k.get('savings') or savings:
        saving_goal = b.k.get('savings') or savings[3]
        out.append('Saving for: %s%s.' % (_short(saving_goal), ' (your own choice)' if b.k.get('savings') else ''))
    out.append('Session: about %d more minutes online.' % max(0, (b.session_end - y.now) // 60))
    return ' '.join(out)


def observe_maps(y, b, arg):
    bg = B.Context(b, y, y.now)
    row = []
    for utility, m, r in bg.game_map[:7]:
        risk = 'high' if r['deaths_per_hour'] > 0.5 else 'medium' if r['deaths_per_hour'] > 0.15 else 'low'
        route = K.route(b.game_map, m, b.firma, b.level) or [m]
        names = sorted({str(v['ad']) for v, n in K.map_npcs(m)})[:4]
        owner = H.company(m)
        owner_label = 'your company' if owner == b.firma else 'enemy company' if owner else 'shared PvP'
        row.append('%s (%s): EP/h %s, credits/h %s, uridium/h %.0f, death risk %s, %d jumps, aliens: %s' % (
            H.name(m), owner_label, _fmt_money(r['ep_per_hour']), _fmt_money(r['credits_per_hour']), r['uridium_per_hour'], risk, len(route) - 1,
            ', '.join(names) or '-'))
    if row:
        return 'Best maps you can reach (best first):\n' + '\n'.join(row)
    return 'No farmable map reachable: %s' % ('you have no laser ammo, so you cannot kill anything (get ammo or sell cargo first).'
                                             if not _laser(b) else 'your ship is too weak for any map you can reach.')


def _laser(b):
    from . import weapons as WP
    return any(v > 0 for k, v in WP.stock(b).items() if 'laser' in k)


def observe_shop(y, b, arg):
    from .goals import shopping as SHOP
    if not y.permission('shop'):
        return 'The shop is closed for you.'
    m = b.game_settings.multiplier('shop_price')
    power = max(1.0, b.value()['power'])
    currency = {'C': b.k['kredi'], 'U': b.k['uridyum']}
    all_ = SHOP.candidates(b)
    all_candidates = sorted(all_, key=lambda c: -c[0] / max(1.0, c[2] * m * (SHOP.EXCHANGE_RATE if c[1] == 'U' else 1)))[:7]
    all_candidates += sorted((c for c in all_ if c not in all_candidates), key=lambda c: -c[0])[:3]       # büyük hedefler (gemi ...): biriktirmeye değer
    if not all_candidates:
        return 'Nothing in the shop would improve your ship right now.'
    row = ['%s: +%.0f%% power, %s %s, %s' % (_short(l), 100 * a / power, _fmt_money(f * m), 'uridium' if p == 'U' else 'credits',
                                               'affordable now' if currency[p] >= f * m else 'need %s more' % _fmt_money(f * m - currency[p]))
             for a, p, f, l in all_candidates]
    return ('Shop upgrades (best value first, the last ones are the biggest upgrades; use the name with buy_item / save_up):\n'
            + '\n'.join(row))


def observe_quests(y, b, arg):
    from .goals import quest as QU
    if not y.permission('gorev'):
        return 'Quests are closed for you.'
    out = []
    g = b.k.get('gorev')
    if g:
        out.append('Active quest: %s.' % QU.quests().get(g['id'], {}).get('ad', '?'))
    u = available_quests(b)[:8]
    if u:
        out.append('Quests you can take: %s.' % '; '.join('%s (#%s, level %s)' % (q.get('ad'), qid, q['seviye']) for qid, q in u))
    return ' '.join(out) or 'No quests available.'


def available_quests(b):
    """Alınabilir görevlerden şu an yeri gidilebilir olanlar (karar motorunun gorev.basla süzgeciyle aynı)."""
    from .goals import quest as QU
    if b.k.get('gorev'):
        return []
    out = []
    try:
        for qid, q in QU.eligible(b):
            b.k['gorev'] = dict(id=qid, conditions={})
            s = QU.next_up(b)
            if s and s[1]:
                out.append((qid, q))
            if len(out) >= 8:
                break
    finally:
        b.k['gorev'] = None
    return out


def observe_events(y, b, arg):
    from . import modes as MD, galaxy_gates as GT
    out = []
    if y.permission('modes') and b.level >= 8:
        a = sorted(MD.candidates(b, y.now), key=lambda m: -MD.value(b, m))[:6]
        if a:
            out.append('Open modes you can enter (enter_mode): %s.' % '; '.join('%s (worth ~%s credits/h)' % (m.name, _fmt_money(MD.value(b, m)))
                                                                             for m in a))
    if y.permission('kapi') and b.level >= 10:
        k = GT.can_run(b)
        if k:
            out.append('Galaxy gate ready to run (run_gate): %s.' % GT.KAPI[k]['ad'])
    return ' '.join(out) or 'No mode or gate open for you right now.'


def observe_surroundings(y, b, arg):
    out = []
    try:
        human = y.online_humans()
    except Exception:
        human = []
    if human:
        out.append('Real players online: %s.' % '; '.join('%s (%s, on %s, you feel %s)' % (
            k.name, ('MMO', 'EIC', 'VRU')[int(k.profile.d['pilot'].get('factionId', 1)) - 1],
            H.name(int(k.profile.d['position'].get('mapId', 0))), _his(b.memory.relation(k.name, y.now))) for k in human[:6]))
    friend = [x for x in y.bots if x is not b and x.online and b.memory.relation(x.name, y.now) >= 0.3][:5]
    if friend:
        out.append('Friends online: %s.' % ', '.join('%s (on %s)' % (x.name, H.name(x.game_map)) for x in friend))
    grudge = [x for x in y.bots if x is not b and x.online and b.memory.relation(x.name, y.now) <= -0.3][:4]
    if grudge:
        out.append('People you hold a grudge against online: %s.' % ', '.join('%s (on %s)' % (x.name, H.name(x.game_map)) for x in grudge))
    here = [x for x in y.on_map.get(b.game_map, ()) if x is not b][:8]
    if here:
        out.append('Pilots on your map: %s.' % ', '.join('%s (%s)' % (x.name, ('MMO', 'EIC', 'VRU')[x.firma - 1]) for x in here))
    return ' '.join(out) or 'Nobody you know is around.'


def _his(d):
    return 'friendly' if d >= 0.3 else 'hostile' if d <= -0.3 else 'neutral'


def observe_clan(y, b, arg):
    try:
        import clan as KL
        k = KL.clan_of(b.profile) if b.profile is not None else None
    except Exception:
        k = None
    if not k:
        return 'You are in no clan.' + (' Clans are closed for you.' if not y.permission('klan') else
                                       ' You can apply with apply_to_clan (clan name or tag).')
    from . import clan_management as CMG, clan_stations as CBA
    leader = k['lider'] == b.name.lower()
    out = [CMG.info_summary(k), 'You are the LEADER: you manage everything (klan_* tools).' if leader else
           'Your rights: %s.' % (', '.join(h for h in KL.RIGHTS if KL.right(b.profile, h)) or 'none')]
    if leader or KL.right(b.profile, 'battle_station_build'):
        out.append(CBA.summary(k))
    return '\n'.join(x for x in out if x)


def observe_notebook(y, b, arg):
    d = [x for x in b.k.get('ledger') or [] if not x.get('finished')]
    h = b.k.get('reminder') or []
    out = ['Your goals: %s.' % ('; '.join('#%d %s' % (i + 1, x['metin']) for i, x in enumerate(d)) if d else 'none written')]
    if h:
        out.append('Reminders: %s.' % '; '.join('in %d min: %s' % (max(0, x['due'] - y.now) // 60, x['metin']) for x in h))
    return ' '.join(out)


def observe_memories(y, b, arg):
    who = str(arg.get('ad') or arg.get('kim') or '').strip()
    if who:
        return MEM.text(b, who, y.now).strip() or 'You remember nothing about %s.' % who
    mems = MEM.important(b, y.now, 6)
    return ('Strongest memories: %s.' % '; '.join('%s (%s)' % (a['summary'], MEM.time_ago(y.now - a['t'])) for a in mems)) if mems else \
        'No strong memories.'


OBSERVATIONS = {
    'durum': (observe_status, 'your level, ship, power, money, cargo, ammo, current activity, quest, saving goal, session time', ''),
    'haritalar': (observe_maps, 'the best maps you can reach for farming: EP/credits/uridium per hour, death risk, jumps, aliens', ''),
    'shop': (observe_shop, 'shop upgrades that improve your ship, with price and whether you can afford them', ''),
    'quests': (observe_quests, 'your active quest and the quests you can take', ''),
    'events': (observe_events, 'open event / PvE modes and galaxy gates you can run', ''),
    'surroundings': (observe_surroundings, 'who is online: real players, your friends, your enemies, pilots on your map', ''),
    'klan': (observe_clan, 'your clan: members, ranks, treasury, budget, diplomacy, battle stations (look before managing it)', ''),
    'ledger': (observe_notebook, 'your written goals and reminders', ''),
    'memories': (observe_memories, 'your memories (of one person if ad is given)', 'ad?'),
}


# ------------------------------------------------------------------------------------------------------------ kendini yönetme
def self_notebook(y, b, arg):
    d = b.k.setdefault('ledger', [])
    operation = str(arg.get('islem') or 'add')
    if operation == 'add':
        text = ' '.join(str(arg.get('metin') or '').split())[:160]
        if not text:
            return 'failed: metin is empty'
        is_open = [x for x in d if not x.get('finished')]
        if len(is_open) >= NOTEBOOK_MAX:
            return 'failed: you already have %d goals; finish or delete one first' % len(is_open)
        d.append({'metin': text, 't': y.now})
        del d[:-20]
        return 'ok: goal added'
    is_open = [x for x in d if not x.get('finished')]
    try:
        x = is_open[int(arg.get('no')) - 1]
    except (TypeError, ValueError, IndexError):
        return 'failed: no such goal number'
    if operation == 'finish':
        x['finished'] = True
        MEM.add(b, b.name, 'I reached my goal: %s' % x['metin'], 'hedef', 0.5, 2, y.now)
        return 'ok: goal done'
    if operation == 'delete':
        d.remove(x)
        return 'ok: goal deleted'
    return 'failed: islem must be add, finish or delete'


def self_remind(y, b, arg):
    try:
        minutes = max(1, min(240, int(arg.get('dakika') or 0)))
    except (TypeError, ValueError):
        return 'failed: dakika must be a number'
    text = ' '.join(str(arg.get('metin') or '').split())[:160]
    h = b.k.setdefault('reminder', [])
    same = next((x for x in h if x['metin'] == (text or 'check how things are going')), None)
    if same is not None:                               # aynı hatırlatıcı: yalnız vakti güncellenir
        same['due'] = y.now + minutes * 60
        return 'ok: reminder moved to %d min from now' % minutes
    if len(h) >= 5:
        return 'failed: you already have 5 reminders'
    h.append({'due': y.now + minutes * 60, 'metin': text or 'check how things are going'})
    return 'ok: you will think again in %d min' % minutes


def k_not(y, b, arg):
    text = ' '.join(str(arg.get('metin') or '').split())[:200]
    if not text:
        return 'failed: metin is empty'
    MEM.add(b, str(arg.get('ad') or b.name), text, 'not', 0.0, 2, y.now, merge=False)
    return 'ok: noted'


SELF = {
    'ledger': (self_notebook, 'manage your long-term goals: islem ekle (metin), bitir (no) or sil (no)', 'islem, metin?, no?'),
    'remind': (self_remind, 'wake yourself up later to think again: in dakika minutes, about metin', 'dakika, metin'),
    'not_al': (k_not, 'write a private note into your memory (about ad, optional)', 'metin, ad?'),
}

# eylem araçları: araclar.py'deki ad -> (İngilizce açıklama, argümanlar); izinler araclar.cagir'da
ACTIONS = {
    'hunt_npcs': ('go farm aliens (on harita if given, one of the maps from haritalar)', 'harita?'),
    'do_quest': ('continue your active quest', ''),
    'pick_quest': ('take a specific quest from gorevler (name or #number)', 'gorev'),
    'hunt_pvp': ('go hunt enemy-company players', ''),
    'buy_item': ('buy a specific upgrade from magaza (by its name)', 'esya'),
    'save_up': ('save money for one upgrade from magaza (shopping then buys only that); empty esya clears it', 'esya'),
    'go_shopping': ('buy the best upgrade you can afford', ''),
    'sell_cargo': ('fly to a station and sell your cargo ore', ''),
    'enter_mode': ('enter an open mode from etkinlikler (by name)', 'mod'),
    'run_gate': ('run your ready galaxy gate', ''),
    'rest': ('go back to base and take a break', ''),
    'oturum': ('decide to stay online dakika more minutes (5-180)', 'dakika'),
    'go_offline': ('log off now', ''),
    'follow': ('fly to the map where player ad is', 'ad'),
    'go_help': ('go help player ad (on harita)', 'ad, harita?'),
    'duello': ('go fight player ad on harita', 'ad, harita'),
    'group_invite': ('invite player ad to your group', 'ad'),
    'leave_group': ('leave your group', ''),
    'add_friend': ('send a friend request to ad', 'ad'),
    'apply_to_clan': ('apply to a clan (name or tag)', 'klan'),
    'clan_description': ('leader: rewrite your clan description (who you are, rules, recruiting)', 'metin'),
    'clan_announce': ('post clan news', 'metin'),
    'clan_mail': ('send a mail to all clan members', 'konu, metin'),
    'clan_rank': ('create (ekle), delete (sil) or set the rights (haklar) of a clan rank', 'islem, rutbe, haklar?'),
    'member_rank': ('give a member a rank (empty rutbe removes it)', 'ad, rutbe'),
    'kick_member': ('kick a member from the clan', 'ad'),
    'transfer_leadership': ('hand the clan leadership to a member', 'ad'),
    'clan_tax': ('set the clan tax, 0-5 percent', 'oran'),
    'clan_budget': ('leader: split the treasury in percent: station, payouts, war (sum at most 90)', 'ksi, odeme, savas'),
    'clan_payout': ('pay a member from the treasury', 'ad, miktar'),
    'clan_station': ('target a free asteroid for your clan battle station (its name)', 'istasyon'),
    'clan_diplomacy': ('offer alliance (ittifak), non-aggression (saldirmazlik), war (savas) or peace (baris) to a clan', 'klan, tur, metin?'),
    'diplomacy_reply': ('accept (kabul true) or refuse a diplomacy offer from a clan', 'klan, kabul'),
    'whisper': ('send a private chat message to ad', 'ad, metin'),
    'write_chat': ('write in a chat channel (kanal: global, firma, klan or grup)', 'kanal, metin'),
    'send_mail': ('send an in-game mail to ad', 'ad, konu, metin'),
}
TOOL_NAMES = list(OBSERVATIONS) + [k for k in SELF if k not in OBSERVATIONS] + list(ACTIONS) + ['finish']


def catalog(y):
    """Modelin araç listesi (paketin izni kapalı olanlar hariç)."""
    # durum her düşünmenin başında zaten verilir (Right now): listede yok, model boşuna adım harcamasın
    out = ['Look (free, use before deciding):'] + ['- %s(%s): %s' % (k, a, d) for k, (f, d, a) in OBSERVATIONS.items() if k != 'durum']
    out.append('Plan yourself:')
    out += ['- %s(%s): %s' % ('ledger' if k == 'ledger' else k, a, d) for k, (f, d, a) in SELF.items()]
    out.append('Act:')
    for k, (d, a) in ACTIONS.items():
        permission = TL.TOOLS[k]['izin']
        if permission and not y.permission(permission):
            continue
        out.append('- %s(%s): %s' % (k, a, d))
    out.append('- bitir(): you are done thinking for now')
    return '\n'.join(out)


def run(br, y, b, tool, arg):
    """Bir adımı yürüt (y.lock altında) -> modele dönen sonuç metni."""
    arg = arg if isinstance(arg, dict) else {}
    if tool == 'ledger' and arg.get('islem') in ('add', 'finish', 'delete'):
        return self_notebook(y, b, arg)
    if tool in OBSERVATIONS:
        return OBSERVATIONS[tool][0](y, b, arg)
    if tool in SELF:
        return SELF[tool][0](y, b, arg)
    if tool not in ACTIONS:
        return 'failed: unknown tool %s' % tool
    if tool in ('whisper', 'write_chat'):
        # art arda yazmaz: aynı kişiye yanıtını beklemeden 2 dk'da bir, aynı kanala dakikada bir (sohbet denemesi 2026-10-30: bot
        # oyuncuya 6 sn arayla iki kez "geliyorum" fısıldadı; bir adımda iki araç ya da yakın iki uyanma)
        target = ('whisper', str(arg.get('ad') or '').lower()) if tool == 'whisper' else ('kanal', str(arg.get('kanal') or 'firma'))
        last = b.__dict__.setdefault('_agent_wrote', {})
        t = last.get(target)
        if t is not None and y.now - t < (120 if tool == 'whisper' else 60) and not (tool == 'whisper' and any(
                x[0] > t and str(x[1]).lower() == target[1] and x[2] == 'whisper:' + b.name for x in y.history[-40:])):
            return 'failed: you just wrote there; wait for an answer before writing again'
    if tool in ('whisper', 'write_chat', 'send_mail'):
        text = br._text(b, arg.get('metin')) if tool != 'send_mail' else ' '.join(str(arg.get('metin') or '').split())
        if not text:
            return 'failed: the message was not sent (too long, stats or numbers, or repeats what was said)'
        arg = dict(arg, metin=text)
        if tool == 'whisper':
            br._spoke(b, arg.get('ad'), y.now)
        if tool != 'send_mail':
            b.__dict__.setdefault('_agent_wrote', {})[target] = y.now
    r = TL.call(y, b, tool, {k: v for k, v in arg.items() if v not in (None, '')} if tool != 'save_up' else arg)
    return ('ok' if r.get('ok') else 'failed') + (': %s' % r['message'] if r.get('message') else '')


# ------------------------------------------------------------------------------------------------------------ döngü
# Maliyet (kullanıcı 2026-10-30: ajan saatte 1,2M token yaktı): bir adımda birden çok araç; döngü yalnız bir bakma aracı istenince
# sürer (çoğu düşünme 1-2 istek). Sistem istemi + araç listesi sabit önek, adımlar çok turlu konuşma: sağlayıcının önek önbelleğine
# girer (DeepSeek'te önbellekteki girdi 50 kat ucuz).
SYSTEM_PROMPT = ("You are the mind of one pilot in a DarkOrbit-like space MMO: you decide what he does next, exactly like a real human "
          "player with his personality, mood and history would. You act only through tools. Reply with ONE JSON object per step: "
          "{\"thought\": a few words of private thought in English, \"tools\": [up to 4 tool calls {\"tool\": name, \"arg\": "
          "{arguments}}]}. Look tools are free and their results come back in your next step; a step with only actions ends your "
          "thinking, so put everything you decided into that step (actions, goals, a reminder). Usually: one step to look (only if "
          "you need facts beyond what you are given), one step to act; if nothing should change, just finish. Use names exactly as "
          "the tools list them; never invent maps, items or players. Play like a person, not an optimizer: keep at what you started "
          "unless there is a reason, follow your written goals, save up for things you want, rest when tired, avoid maps that kill "
          "you, help friends, settle scores. Write long-term decisions into ledger and set a reminder (remind) to check on "
          "something later. Chat messages are short (at most 12 words), in your own chat language and style, never stats; do not "
          "keep messaging or inviting the same person when he does not answer. Output only the JSON.")


def system(y):
    """Sabit önek: kurallar ve araç listesi (paketin izinleriyle; bütün botlarda aynı -> önbellekte)."""
    from . import admin_warnings as AW
    return SYSTEM_PROMPT + AW.system_note() + '\n\nTOOLS:\n' + catalog(y)


def schema():
    s = {'type': 'string'}
    call = {'type': 'object', 'properties': {
        'tool': {'type': 'string', 'enum': TOOL_NAMES},
        'arg': {'type': 'object', 'properties': {
            'harita': s, 'ad': s, 'esya': s, 'gorev': s, 'mod': s, 'klan': s, 'kanal': s, 'metin': s, 'konu': s, 'islem': s,
            'rutbe': s, 'haklar': s, 'tur': s, 'istasyon': s, 'kabul': {'type': 'boolean'}, 'oran': {'type': 'integer'},
            'miktar': {'type': 'integer'}, 'ksi': {'type': 'integer'}, 'odeme': {'type': 'integer'}, 'savas': {'type': 'integer'},
            'dakika': {'type': 'integer'}, 'no': {'type': 'integer'}}}},
        'required': ['tool', 'arg']}
    return {'type': 'object', 'properties': {
        'thought': {'type': 'string', 'maxLength': 160}, 'tools': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': call}},
        'required': ['thought', 'tools']}


def _calls(r):
    """Modelin yanıtı -> [(araç, arg)] (eski tek araçlı biçim de)."""
    xs = r.get('tools') if isinstance(r.get('tools'), list) else [r] if r.get('tool') else []
    return [(str(x.get('tool') or 'finish'), x.get('arg') if isinstance(x.get('arg'), dict) else {}) for x in xs[:4] if isinstance(x, dict)]


def _is_observation(tool, arg):
    return tool in OBSERVATIONS and not (tool == 'ledger' and arg.get('islem') in ('add', 'finish', 'delete'))


def think(br, b, reason, max_count=STEPS):
    """Bir düşünme anı: adım adım araç döngüsü (adımda en çok 4 araç). -> [(düşünce, araç, arg, sonuç)]."""
    from . import llm
    y = br.y
    with y.lock:
        system_prompt = system(y)
        first = '%s\nYour chat style: %s.\n\nWHY YOU ARE THINKING NOW: %s\n\nRight now: %s\n%s\n\nYour step as JSON.' % (
            llm.persona(b, y), llm.style(b), reason, observe_status(y, b, {}), observe_notebook(y, b, {}))
    message = [{'role': 'user', 'content': first}]
    steps = []
    for i in range(max(1, max_count)):
        r = br.ask(message, schema(), max_count=200, temperature=0.5, system=system_prompt)
        short_thought = ' '.join(str(r.get('thought') or '').split())[:160]
        call = _calls(r)
        results, looked, finished = [], False, not call
        for tool, arg in call:
            if tool == 'finish':
                finished = True
                break
            with y.lock:
                try:
                    result = str(run(br, y, b, tool, arg))
                except Exception as e:                     # araç hatası modele söylenir, döngü sürer
                    result = 'failed: %s' % e
            looked = looked or _is_observation(tool, arg)
            steps.append((short_thought, tool, arg, result[:900]))
            results.append('%s -> %s' % (tool, result[:700]))
        if finished and not results:
            steps.append((short_thought, 'finish', {}, ''))
        if finished or not looked or i == max_count - 1:
            break                                          # yalnız eylem: düşünme biter (ek istek yok)
        message += [{'role': 'assistant', 'content': json.dumps(r, ensure_ascii=False)},
                  {'role': 'user', 'content': 'Results:\n%s\n\n%s' % ('\n'.join(results), 'This is your LAST step: act now or bitir.'
                                                                    if i == max_count - 2 else 'Your next step as JSON.')}]
    with y.lock:
        trace = b.k.setdefault('agent', [])
        trace.extend({'t': y.now, 'reason': reason[:120], 'thought': d, 'tool': a, 'arg': g, 'result': s[:200]} for d, a, g, s in steps)
        del trace[:-20]
    return steps


def wake_state(b):
    """uyandiranlar'ın tükettiği durum -> geri yükleyen işlev (iş kuyruğa giremezse ya da bayatlarsa hatırlatıcı, kargo/birikim
    uyarısı ve olaylar kaybolmasın)."""
    d = {k: b.__dict__[k] for k in ('_ajan_olay_t', '_kargo_uyandi', '_birikim_uyandi') if k in b.__dict__}
    h = b.k.get('reminder')
    h = list(h) if h is not None else None

    def refund():
        for k in ('_ajan_olay_t', '_kargo_uyandi', '_birikim_uyandi'):
            if k in d:
                b.__dict__[k] = d[k]
            else:
                b.__dict__.pop(k, None)
        if h is not None:
            b.k['reminder'] = h + [x for x in b.k.get('reminder') or [] if x not in h]    # arada kurulan yenisi de kalsın
    return refund


def wakers(y, b, now, events=True):
    """Botu şimdi düşündürecek sebep (olay, hatırlatıcı, biriktirmenin tamamlanması) ya da None. olaylar=False: oyuncudan uzak bot
    yalnız kendi kurduğu hatırlatıcıyla ve birikimiyle uyanır (ajan seyrek; olaylarını kurallı motor karşılar)."""
    last = b.__dict__.get('_agent_event_t', now)
    b._agent_event_t = now
    for o in reversed(b.events[-8:]) if events else ():
        if o['t'] > last and o['tur'] in WAKE_EVENTS:
            if o['tur'] == 'olum' and o.get('killer'):
                return 'you just got shot down by %s' % o['killer']
            return WAKE_EVENTS[o['tur']]
    h = b.k.get('reminder') or []
    is_due = [x for x in h if x['due'] <= now]
    if is_due:
        b.k['reminder'] = [x for x in h if x['due'] > now]
        return 'your reminder: %s' % is_due[0]['metin']
    if events and b.cargo_fill() >= 0.97 and not b.__dict__.get('_cargo_woke'):      # uzak botun kargosunu kurallı motor satar
        b._cargo_woke = True
        return 'your cargo is full'
    if b.cargo_fill() < 0.5:
        b._cargo_woke = False
    target = b.k.get('savings')
    if target:
        c = TL._item(b, target)
        if c is not None and {'C': b.k['kredi'], 'U': b.k['uridyum']}[c[1]] >= c[2] and not b.__dict__.get('_savings_woke'):
            b._savings_woke = True
            return 'you now have enough money for %s, which you were saving for' % _short(target)
    return None
