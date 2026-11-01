"""The bot's actions (tools): the decision engine, chat and the LLM (Advanced mode) make the bot do things only through these tools.

Each tool: name, description, parameters (JSON schema; given to the LLM), permission (the pack's access setting) and function (y, bot, **arg) ->
{'ok': bool, 'message': str}. Tools that change the goal set the bot's intent (brain.force): the bot carries on the job with its own judgment, and if it
is interrupted the decision engine takes over. For a new action it is enough to add a function here with @tool; the schema goes to the LLM by itself.
"""
import map_links as H
from . import brain as B
from . import catalog as K

TOOLS = {}


def tool(name, description, parameters=None, permission=None):
    def save(fn):
        TOOLS[name] = dict(name=name, description=description, parameters=parameters or {}, permission=permission, fn=fn)
        return fn
    return save


def schema(y=None, names=None):
    """The tool list for the LLM: [{name, description, parameters}] (except those whose permission is off)."""
    out = []
    for a in TOOLS.values():
        if names is not None and a['name'] not in names:
            continue
        if a['permission'] and y is not None and not y.permission(a['permission']):
            continue
        out.append({'name': a['name'], 'description': a['description'], 'parameters': a['parameters']})
    return out


def call(y, bot, name, arg=None):
    """Run the tool -> {'ok', 'message'}. An unknown tool, a disabled permission or a bad argument returns an error (the bot does nothing)."""
    a = TOOLS.get(str(name or ''))
    if a is None:
        return {'ok': False, 'message': 'bilinmeyen araç'}
    if a['permission'] and y is not None and not y.permission(a['permission']):
        return {'ok': False, 'message': 'izin kapalı'}
    try:
        r = a['fn'](y, bot, **{k: v for k, v in (arg or {}).items() if k in a['parameters']})
    except (TypeError, ValueError, KeyError) as e:
        return {'ok': False, 'message': 'hatalı argüman: %s' % e}
    except Exception as e:                                  # an error inside a tool (AttributeError...) must not take down the rest of the chat tick
        return {'ok': False, 'message': 'araç hatası: %r' % e}
    bot.event('tool', y.now if y is not None else None, name=name, result=r.get('ok'))
    return r


def _game_map(name):
    from .speech import MAP_RE
    ids = {v.lower(): k for k, v in H.NAMES.items()}
    s = str(name or '').strip().lower()
    r = MAP_RE.search(s)
    m = ids.get(s) or (ids.get('%s-%s' % (r.group(1), r.group(2))) if r else None)
    return int(m) if m is not None and int(m) in K.MAPS else None


def _ok(m=''):
    return {'ok': True, 'message': m}


def _error(m):
    return {'ok': False, 'message': m}


# ------------------------------------------------------------------------------------------------------------ targets
@tool('hunt_npcs', 'Uzaylı kas (harita verilirse oraya gidip orada).', {'map': 'string, ör. "1-3" (isteğe bağlı)'})
def hunt_npcs(y, bot, map=None):
    m = _game_map(map) if map else None
    if map and (m is None or not K.can_enter(m, bot.firma, bot.level)):
        return _error('haritaya girilemez')
    B.force(bot, 'grinding', plan={'map': m} if m else {}, pay=0.8, now=y.now if y else None)
    return _ok()


@tool('hunt_pvp', 'Düşman firmadan oyuncu avına çık.', {}, permission='pvp')
def hunt_pvp(y, bot):
    B.force(bot, 'pvp', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('do_quest', 'Görev zincirine devam et.', {}, permission='quest')
def do_quest(y, bot):
    B.force(bot, 'quest', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('go_shopping', 'Parası yetiyorsa en iyi yükseltmeyi al.', {}, permission='shop')
def go_shopping(y, bot):
    from .goals import shopping as SHOP
    c = SHOP.candidate(bot)[0]
    if c is None:
        return _error('alınacak bir şey yok ya da para yetmiyor')
    if bot.pay(c[1], c[2]):
        bot.add(c[3])
        bot.event('purchase', y.now if y else None, item=c[3], price=c[2], currency=c[1])
        if c[3].startswith('ship_'):
            bot.event('new_ship', y.now if y else None, item=c[3])
        return _ok(c[3])
    return _error('para yetmedi')


@tool('rest', 'Üste dön ve bir süre dinlen / sohbet et.', {})
def rest(y, bot):
    B.force(bot, 'resting', pay=0.8, duration=900, now=y.now if y else None)
    return _ok()


@tool('go_help', 'Yardım isteyen oyuncunun haritasına gidip düşmanlarla savaş.', {'map': 'string, ör. "2-4"', 'name': 'string: yardım isteyen'},
      permission='assist')
def go_help(y, bot, map=None, name=''):
    m = _game_map(map) if map else None
    if m is None and name:
        import community as TP
        k = TP.find(name=name)
        m = int(k.profile.d['position'].get('mapId', 0)) if k is not None else None
    if m is None or m not in K.MAPS or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
        return _error('oraya gidemez')
    B.force(bot, 'assist', plan={'map': m, 'name': name}, pay=1.2, duration=900, now=y.now if y else None)
    if name:
        bot.memory.event(name, 'i_helped', y.now if y else None)
    return _ok(H.name(m))


@tool('duel', 'Meydan okuyan oyuncuyu buluşma haritasında bulup savaş.', {'name': 'string', 'map': 'string, ör. "4-4"'},
      permission='pvp')
def duel(y, bot, name='', map=None):
    m = _game_map(map) if map else None
    if not name or m is None or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
        return _error('oraya gidemez')
    B.force(bot, 'duel', plan={'map': m, 'name': name}, pay=1.5, duration=900, now=y.now if y else None)
    bot.memory.event(name, 'challenge', y.now if y else None)
    return _ok(H.name(m))


@tool('go_offline', 'Oyundan çık (oturumu bitir).', {})
def go_offline(y, bot):
    bot.session_end = y.now if y else 0
    return _ok()


# ------------------------------------------------------------------------------------------------------------ social
@tool('write_chat', 'Bir kanala yaz.', {'channel': 'global | firma | klan | grup', 'text': 'string'}, permission='sohbet')
def write_chat(y, bot, channel='company', text=''):
    if channel not in ('global', 'company', 'clan', 'group') or not str(text).strip():
        return _error('kanal ya da metin geçersiz')
    y.speak(bot, channel, str(text).strip()[:200])
    return _ok()


@tool('whisper', 'Birine özel mesaj yaz.', {'name': 'string', 'text': 'string'}, permission='sohbet')
def whisper(y, bot, name='', text=''):
    if not name or not str(text).strip():
        return _error('ad ya da metin yok')
    y.speak(bot, 'whisper', str(text).strip()[:200], recipient=name)
    return _ok()


@tool('group_invite', 'Oyuncuyu grubuna davet et.', {'name': 'string'}, permission='group')
def group_invite(y, bot, name=''):
    import group as GR
    from . import society
    out = GR.handle(society.person(bot), 'InvitationCreationRequest', {'name': name})
    hata = next((m[1].get('error') for m in out or () if m[0] == 'InvitationErrorCommand'), None)
    if hata is not None:                               # the player is in another group, offline, invitation limit ...: stays as words
        from . import interaction as IX
        IX.make_promise(bot, 'group', name, y.now if y else 0)
        reason = {GR.GROUP_FULL: 'grup dolu', GR.CANDIDATE_IN_GROUP: 'o zaten bir grupta', GR.CANDIDATE_NONEXISTENT: 'o çevrimiçi değil',
                 GR.BOSS_ONLY: 'yalnız grup lideri davet edebilir', GR.MAX_INVITER: 'çok fazla bekleyen davetin var',
                 GR.MAX_CANDIDATE: 'onun çok fazla bekleyen daveti var', GR.CANDIDATE_BLOCKING: 'seni engellemiş',
                 GR.DUPLICATE_INVITATION: 'davetin zaten gitti, yanıtını bekliyor'}.get(hata, 'hata %s' % hata)
        return _error('davet gitmedi: %s' % reason)
    return _ok()


@tool('leave_group', 'Gruptan ayrıl.', {}, permission='group')
def leave_group(y, bot):
    import group as GR
    from . import society
    if GR.group_of(bot.uid) is None:
        return _error('grupta değil')
    GR.handle(society.person(bot), 'LeaveGroupRequest', {})
    return _ok()


@tool('add_friend', 'Arkadaşlık isteği gönder.', {'name': 'string'}, permission='friend')
def add_friend(y, bot, name=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.CREATE, 'userName': name})
    bot.memory.event(name, 'friend', y.now if y else None)
    return _ok()


@tool('friend_accept', 'Gelen arkadaşlık isteğini kabul et.', {'name': 'string'}, permission='friend')
def accept_friend(y, bot, name=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.ACCEPT, 'userName': name})
    bot.memory.event(name, 'friend', y.now if y else None)
    return _ok()


@tool('send_mail', 'Birine oyun içi posta gönder.', {'name': 'string', 'subject': 'string', 'text': 'string'}, permission='sohbet')
def send_mail(y, bot, name='', subject='', text=''):
    import mail as PS
    from . import society
    subject, text = str(subject).strip()[:50], str(text).strip()[:1500]
    if not name or len(subject) < 3 or len(text) < 5:
        return _error('ad, konu ya da metin eksik')
    out = PS.Mail(society.profile(bot), log=lambda *_: None).handle('UserMessageSendRequest', {
        'recipients': [name], 'subject': subject, 'body': text, 'recipientType': 'user'})
    return _ok() if out and out[0][1].get('success') else _error('gönderilemedi')


@tool('follow', 'Oyuncunun bulunduğu haritaya git ve yanında avlan.', {'name': 'string'})
def follow(y, bot, name=''):
    import community as TP
    k = TP.find(name=name)
    if k is None:
        return _error('böyle biri yok')
    return hunt_npcs(y, bot, map=H.name(int(k.profile.d['position'].get('mapId', bot.game_map))))


@tool('apply_to_clan', 'Bir klana başvur.', {'clan': 'string: klanın adı ya da etiketi'}, permission='clan')
def apply_to_clan(y, bot, clan=''):
    import clan as KL
    from . import society
    c = next((c for c in KL.CLANS.values() if str(clan).lower() in (c['name'].lower(), c['tag'].lower())), None)
    if c is None:
        return _error('klan yok')
    out = KL.Clan(society.profile(bot)).handle('ApplyClanRequest', {'clanId': c['id'], 'message': 'lvl %d' % bot.level})
    society.update(bot)
    return _ok() if out and out[0][1].get('success') else _error('başvurulamadı')


# ------------------------------------------------------------------------------------------------------------ clan management
# (clan_management.py; the leader or a member with the right: the game's clan requests check the rights themselves)
def _clan(bot):
    import clan as KL
    from . import society
    k = KL.clan_of(society.profile(bot))
    return k, (KL.Clan(bot.profile, log=lambda *_: None) if k else None)


def _result(out, ok='', error='yapılamadı (hakkın yok ya da geçersiz)'):
    if out and out[0][1].get('success'):
        return _ok(ok)
    e = out[0][1].get('errorMsg') if out else None
    return _error(error if not isinstance(e, dict) or not e.get('stringBasekey') else '%s: %s' % (error, e['stringBasekey']))


@tool('clan_description', 'Klanın açıklamasını yaz (yalnız lider).', {'text': 'string, en çok 2000 karakter'}, permission='clan')
def clan_description(y, bot, text=''):
    k, kl = _clan(bot)
    if k is None or not str(text).strip():
        return _error('klanın yok ya da metin boş')
    return _result(kl.handle('ChangeClanDescriptionRequest', {'desc': str(text).strip()[:2000]}))


@tool('clan_announce', 'Klanın haberlerine duyuru yaz.', {'text': 'string'}, permission='clan')
def clan_announce(y, bot, text=''):
    k, kl = _clan(bot)
    if k is None or not str(text).strip():
        return _error('klanın yok ya da metin boş')
    return _result(kl.handle('ClanAddNewsRequest', {'newsMessage': str(text).strip()[:500]}))


@tool('clan_mail', 'Bütün klana posta gönder.', {'subject': 'string', 'text': 'string'}, permission='clan')
def clan_mail(y, bot, subject='', text=''):
    k, kl = _clan(bot)
    if k is None or not str(subject).strip() or not str(text).strip():
        return _error('klanın yok ya da konu/metin boş')
    return _result(kl.handle('ClanSendAllMessageRequest', {'subject': str(subject).strip()[:50], 'msgText': str(text).strip()[:1500]}))


@tool('clan_rank', 'Rütbe ekle, sil ya da haklarını değiştir.', {
    'operation': 'ekle | sil | haklar', 'rank': 'string: rütbenin adı',
    'rights': 'string: virgüllü haklar (hiremember, firemember, editranks, news, roundmail, tax, payout, diplo_start, diplo_end, '
              'diplo_war, battle_station_build, battle_station_replace_module, battle_station_deflector)'}, permission='clan')
def clan_rank(y, bot, operation='add', rank='', rights=''):
    import clan as KL
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or not str(rank).strip():
        return _error('klanın yok ya da rütbe adı boş')
    right = [h.strip() for h in str(rights or '').split(',') if h.strip() in KL.RIGHTS]
    if operation == 'add':
        out = kl.handle('ClanNewRankRequest', {'newRank': str(rank).strip()[:30]})
        r = CMG.find_rank(k, rank)
        if out and out[0][1].get('success') and r is not None and right:
            kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['name'], 'rights': right}]})
        return _result(out, 'rütbe eklendi')
    r = CMG.find_rank(k, rank)
    if r is None:
        return _error('böyle bir rütbe yok')
    if operation == 'delete':
        return _result(kl.handle('ClanDeleteRankRequest', {'deleteRankId': r['id']}), 'rütbe silindi')
    if operation == 'rights':
        return _result(kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['name'], 'rights': right}]}),
                      'haklar: %s' % (', '.join(right) or 'none'))
    return _error('islem ekle, sil ya da haklar olmalı')


@tool('member_rank', 'Bir üyeye rütbe ver (boş rütbe: rütbesini al).', {'name': 'string: üye', 'rank': 'string: rütbe adı'}, permission='clan')
def member_rank(y, bot, name='', rank=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    a, u = CMG.find_member(k, name)
    r = CMG.find_rank(k, rank) if str(rank or '').strip() else {'id': 0}
    if u is None or r is None:
        return _error('böyle bir üye ya da rütbe yok')
    return _result(kl.handle('EditClanMemberRequest', {'rankId': r['id'], 'memberId': int(u.get('uid', 0))}))


@tool('kick_member', 'Bir üyeyi klandan çıkar.', {'name': 'string'}, permission='clan')
def kick_member(y, bot, name=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    result = CMG.kick(y, bot, k, kl, y.now if y else 0, name=name)
    return _ok('%s çıkarıldı' % result) if result else _error('çıkarılamadı (hakkın yok ya da üye değil)')


@tool('transfer_leadership', 'Klanın liderliğini bir üyeye bırak.', {'name': 'string'}, permission='clan')
def transfer_leadership(y, bot, name=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    result = CMG.hand_over(y, bot, k, kl, y.now if y else 0, name=name)
    return _ok('lider artık %s' % result) if result else _error('devredilemedi (lider değilsin ya da üye değil)')


@tool('clan_tax', 'Klanın vergisini ayarla (yüzde 0-5).', {'ratio': 'integer'}, permission='clan')
def clan_tax(y, bot, ratio=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    return _ok('vergi %%%d' % int(ratio)) if CMG.set_tax(bot, k, kl, y.now if y else 0, ratio=int(ratio)) else _error('vergi hakkın yok')


@tool('clan_budget', 'Kasanın paylarını ayarla (yüzde; toplamı en çok 90, kalanı yedek): istasyon, üyelere ödeme, savaş.',
      {'ksi': 'integer', 'payment': 'integer', 'combat': 'integer'}, permission='clan')
def clan_budget(y, bot, ksi=None, payment=None, combat=None):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or k['leader'] != bot.name.lower():
        return _error('yalnız lider')
    b = CMG.set_budget(bot, k, y.now if y else 0, *[None if v is None else max(0, int(v)) / 100.0 for v in (ksi, payment, combat)])
    return _ok('istasyon %d%%, ödeme %d%%, savaş %d%%' % (100 * b['ksi'], 100 * b['payment'], 100 * b['combat']))


@tool('clan_payout', 'Kasadan bir üyeye kredi öde.', {'name': 'string', 'amount': 'integer'}, permission='clan')
def clan_payout(y, bot, name='', amount=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    a, u = CMG.find_member(k, name)
    if u is None:
        return _error('böyle bir üye yok')
    return _result(kl.handle('PayoutClanRequest', {'amount': int(amount), 'payoutUserId': int(u.get('uid', 0)), 'reason': 'payout'}),
                  'ödendi', 'ödenemedi (hakkın yok, kasa yetmiyor ya da üyenin haftalık sınırı doldu)')


@tool('clan_station', 'Klanın istasyon kuracağı boş asteroidi seç (adıyla; modüller kasadan, bütçenin istasyon payıyla).',
      {'station': 'string: asteroidin adı'}, permission='clan_cbs')
def clan_station(y, bot, station=''):
    from . import clan_stations as CBA
    k, kl = _clan(bot)
    if k is None or not CBA.is_open() or not kl.right('battle_station_build', k):
        return _error('istasyon kurma hakkın yok')
    return _ok('hedef: %s' % station) if CBA.set_target(k, station, bot) else _error('böyle boş bir asteroit yok')


_DIPLO = {'peace': 0, 'peace': 0, 'alliance': 1, 'alliance': 1, 'non_aggression': 2, 'nap': 2, 'combat': 3, 'war': 3}


@tool('clan_diplomacy', 'Başka bir klana ittifak, saldırmazlık, savaş ya da barış teklif et.',
      {'clan': 'string: klanın adı ya da etiketi', 'type': 'ittifak | saldirmazlik | savas | baris', 'text': 'string'}, permission='clan_diplomacy')
def clan_diplomacy(y, bot, clan='', type='', text=''):
    import clan as KL
    k, kl = _clan(bot)
    c = next((c for c in KL.CLANS.values() if str(clan).lower() in (c['name'].lower(), c['tag'].lower())), None)
    if k is None or c is None or str(type).lower() not in _DIPLO:
        return _error('klanın yok, böyle bir klan yok ya da tür geçersiz')
    return _result(kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': _DIPLO[str(type).lower()],
                                                        'desc': str(text or '').strip()[:200]}), 'teklif gitti')


@tool('diplomacy_reply', 'Klanına gelen diplomasi teklifini kabul ya da reddet.', {'clan': 'string', 'accept': 'boolean'},
      permission='clan_diplomacy')
def diplomacy_reply(y, bot, clan='', accept=False):
    import clan as KL
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    s = str(clan).lower()
    r = None
    for x in k.get('diplomacy_requests', []):
        o = KL.CLANS.get(x['from_clan']) or {}
        if x['to'] == k['id'] and s in (str(o.get('name', '')).lower(), str(o.get('tag', '')).lower()):
            r = x
            break
    if r is None:
        return _error('o klandan bekleyen teklif yok')
    return _result(kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if accept in (True, 'true', 1) else 'deny'}))


@tool('none', 'Bir şey yapma.', {})
def none_(y, bot):
    return _ok()


# ------------------------------------------------------------------------------------------------------------ the agent's tools
# (Advanced mode, strong provider: bot/agent.py offers them to the model; the decision engine can call them too)
def _item(bot, item):
    """Shop candidate (gain, currency, price, loot): matches the full loot or its ending ("lf-2", "goliath")."""
    from .goals import shopping as SHOP
    s = str(item or '').strip().lower()
    if not s:
        return None
    m = bot.game_settings.multiplier('shop_price')
    for a, p, f, l in SHOP.candidates(bot):
        if l.lower() == s or l.lower().rsplit('_', 1)[-1] == s:
            return a, p, f * m, l
    return None


@tool('buy_item', 'Mağazadan belirli bir yükseltmeyi al (magaza listesindeki ad).', {'item': 'string: eşyanın adı'}, permission='shop')
def buy_item(y, bot, item=''):
    c = _item(bot, item)
    if c is None:
        return _error('mağaza listesinde yok (ya da yuvası yok / daha iyisi takılı)')
    currency = {'C': bot.k['credits'], 'U': bot.k['uridium']}[c[1]]
    if currency < c[2]:
        return _error('para yetmiyor: %d %s gerekli, %d var' % (c[2], c[1], currency))
    if not bot.pay(c[1], c[2]):
        return _error('para yetmedi')
    bot.add(c[3])
    bot.ist('purchase')
    bot.event('purchase', y.now if y else None, item=c[3], price=c[2], currency=c[1])
    if c[3].startswith('ship_'):
        bot.event('new_ship', y.now if y else None, item=c[3])
    if bot.k.get('savings') == c[3]:
        bot.k['savings'] = None                         # bought what it had been saving for
    return _ok('%s alındı (%d %s)' % (c[3], c[2], c[1]))


@tool('save_up', 'Bir yükseltme için para biriktir (alışveriş başka şeye harcamaz); boş ad hedefi kaldırır.', {'item': 'string'},
      permission='shop')
def save_up(y, bot, item=''):
    if not str(item or '').strip():
        bot.k['savings'] = None
        return _ok('biriktirme hedefi kaldırıldı')
    c = _item(bot, item)
    if c is None:
        return _error('mağaza listesinde yok')
    bot.k['savings'] = c[3]
    bot._candidates = None
    bot._savings_woke = False                         # when the money is complete the agent wakes up once (agent.wakers)
    return _ok('%s için biriktiriliyor (%d %s)' % (c[3], c[2], c[1]))


@tool('pick_quest', 'Alınabilir görevlerden belirli birini al (görev yoksa).', {'quest': 'string: görevin adı ya da numarası'},
      permission='quest')
def pick_quest(y, bot, quest=''):
    from .goals import quest as QU
    if bot.k.get('quest'):
        return _error('zaten bir görev sürüyor: %s' % QU.quests().get(bot.k['quest']['id'], {}).get('name', '?'))
    s = str(quest or '').strip().lower().lstrip('#')
    for qid, q in QU.eligible(bot):
        if s in (str(qid), str(q.get('name', '')).lower()):
            bot.k['quest'] = dict(id=qid, conditions={})
            if not (QU.next_up(bot) or (None, None))[1]:
                bot.k['quest'] = None
                return _error('bu görevin yeri şu an gidilebilir değil')
            bot.event('quest_taken', y.now if y else None, name=q.get('name'))
            B.force(bot, 'quest', pay=0.9, now=y.now if y else None)
            return _ok('görev alındı: %s' % q.get('name'))
    return _error('alınabilir görevlerde yok')


@tool('sell_cargo', 'Kargodaki cevherleri en yakın istasyonda sat.', {}, permission='cargo')
def sell_cargo(y, bot):
    if bot.cargo_fill() <= 0:
        return _error('kargo boş')
    B.force(bot, 'selling', pay=1.0, duration=900, now=y.now if y else None)
    return _ok()


@tool('enter_mode', 'Açık bir moda (etkinlik / PvE) gir: bedelini öder, modun haritasına geçer.', {'mod': 'string: modun adı'},
      permission='modes')
def enter_mode(y, bot, mod=''):
    from . import modes as MD
    now = y.now if y else None
    s = str(mod or '').strip().lower()
    m = next((m for m in MD.candidates(bot, now) if s in (m.uid.lower(), str(m.name).lower())), None)
    if m is None:
        return _error('bu mod şu an girilebilir değil')
    bot._mode_candidate, bot._mode_next_check = m, (now or 0) + 300
    B.force(bot, 'mod', pay=1.2, duration=900, now=now)
    return _ok(m.name)


@tool('run_gate', 'Kurulu Galaksi Kapısına gir.', {}, permission='gate')
def run_gate(y, bot):
    from . import galaxy_gates as GT
    k = GT.can_run(bot)
    if bot.level < 10 or k is None:
        return _error('geçilebilecek kurulu kapı yok')
    B.force(bot, 'gate', pay=1.2, duration=900, now=y.now if y else None)
    return _ok(GT.KAPI[k]['name'])


@tool('session', 'Oyunda bu kadar dakika daha kal (5-180).', {'minutes': 'integer'})
def session(y, bot, minutes=30):
    d = max(5, min(180, int(minutes)))
    bot.session_end = (y.now if y else 0) + d * 60
    return _ok('%d dk daha' % d)
