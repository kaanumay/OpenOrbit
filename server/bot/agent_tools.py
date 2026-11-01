"""Botun eylemleri (araçlar): karar motoru, sohbet ve LLM (Gelişmiş kip) bota yalnız bu araçlarla iş yaptırır.

Her araç: ad, açıklama, parametreler (JSON şema; LLM'e verilir), izin (paketin erişim ayarı) ve işlev (yonetici, bot, **arg) ->
{'ok': bool, 'mesaj': str}. Hedef değiştiren araçlar botun niyetini kurar (beyin.zorla): bot işi kendi aklıyla sürdürür, yarıda
kalırsa karar motoru devralır. Yeni bir eylem için buraya @arac ile bir işlev eklemek yeter; şema LLM'e kendiliğinden gider.
"""
import map_links as H
from . import brain as B
from . import catalog as K

TOOLS = {}


def tool(ad, aciklama, parametreler=None, izin=None):
    def save(fn):
        TOOLS[ad] = dict(ad=ad, aciklama=aciklama, parametreler=parametreler or {}, izin=izin, fn=fn)
        return fn
    return save


def schema(y=None, adlar=None):
    """LLM için araç listesi: [{ad, aciklama, parametreler}] (izni kapalı olanlar hariç)."""
    out = []
    for a in TOOLS.values():
        if adlar is not None and a['ad'] not in adlar:
            continue
        if a['izin'] and y is not None and not y.permission(a['izin']):
            continue
        out.append({'ad': a['ad'], 'aciklama': a['aciklama'], 'parametreler': a['parametreler']})
    return out


def call(y, bot, ad, arg=None):
    """Aracı çalıştır -> {'ok', 'mesaj'}. Bilinmeyen araç, kapalı izin ya da hatalı argüman hata döner (bot bir şey yapmaz)."""
    a = TOOLS.get(str(ad or ''))
    if a is None:
        return {'ok': False, 'mesaj': 'bilinmeyen araç'}
    if a['izin'] and y is not None and not y.permission(a['izin']):
        return {'ok': False, 'mesaj': 'izin kapalı'}
    try:
        r = a['fn'](y, bot, **{k: v for k, v in (arg or {}).items() if k in a['parametreler']})
    except (TypeError, ValueError, KeyError) as e:
        return {'ok': False, 'mesaj': 'hatalı argüman: %s' % e}
    except Exception as e:                                  # araç içi hata (AttributeError…) sohbet tikinin kalanını düşürmesin
        return {'ok': False, 'mesaj': 'araç hatası: %r' % e}
    bot.event('arac', y.now if y is not None else None, ad=ad, sonuc=r.get('ok'))
    return r


def _game_map(ad):
    from .speech import MAP_RE
    ids = {v.lower(): k for k, v in H.NAMES.items()}
    s = str(ad or '').strip().lower()
    r = MAP_RE.search(s)
    m = ids.get(s) or (ids.get('%s-%s' % (r.group(1), r.group(2))) if r else None)
    return int(m) if m is not None and int(m) in K.MAPS else None


def _ok(m=''):
    return {'ok': True, 'mesaj': m}


def _error(m):
    return {'ok': False, 'mesaj': m}


# ------------------------------------------------------------------------------------------------------------ hedefler
@tool('npc_avla', 'Uzaylı kas (harita verilirse oraya gidip orada).', {'harita': 'string, ör. "1-3" (isteğe bağlı)'})
def hunt_npcs(y, bot, harita=None):
    m = _game_map(harita) if harita else None
    if harita and (m is None or not K.can_enter(m, bot.firma, bot.level)):
        return _error('haritaya girilemez')
    B.force(bot, 'kasilma', plan={'harita': m} if m else {}, pay=0.8, now=y.now if y else None)
    return _ok()


@tool('pvp_avla', 'Düşman firmadan oyuncu avına çık.', {}, izin='pvp')
def hunt_pvp(y, bot):
    B.force(bot, 'pvp', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('gorev_yap', 'Görev zincirine devam et.', {}, izin='gorev')
def do_quest(y, bot):
    B.force(bot, 'gorev', pay=0.8, now=y.now if y else None)
    return _ok()


@tool('alisveris_yap', 'Parası yetiyorsa en iyi yükseltmeyi al.', {}, izin='magaza')
def go_shopping(y, bot):
    from .goals import shopping as SHOP
    c = SHOP.candidate(bot)[0]
    if c is None:
        return _error('alınacak bir şey yok ya da para yetmiyor')
    if bot.pay(c[1], c[2]):
        bot.add(c[3])
        bot.event('alim', y.now if y else None, esya=c[3], fiyat=c[2], para=c[1])
        if c[3].startswith('ship_'):
            bot.event('yeni_gemi', y.now if y else None, esya=c[3])
        return _ok(c[3])
    return _error('para yetmedi')


@tool('dinlen', 'Üste dön ve bir süre dinlen / sohbet et.', {})
def rest(y, bot):
    B.force(bot, 'dinlenme', pay=0.8, duration=900, now=y.now if y else None)
    return _ok()


@tool('yardima_git', 'Yardım isteyen oyuncunun haritasına gidip düşmanlarla savaş.', {'harita': 'string, ör. "2-4"', 'ad': 'string: yardım isteyen'},
      izin='yardim')
def go_help(y, bot, harita=None, ad=''):
    m = _game_map(harita) if harita else None
    if m is None and ad:
        import community as TP
        k = TP.find(name=ad)
        m = int(k.profile.d['konum'].get('mapId', 0)) if k is not None else None
    if m is None or m not in K.MAPS or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
        return _error('oraya gidemez')
    B.force(bot, 'yardim', plan={'harita': m, 'ad': ad}, pay=1.2, duration=900, now=y.now if y else None)
    if ad:
        bot.memory.event(ad, 'yardim_ettim', y.now if y else None)
    return _ok(H.name(m))


@tool('duello', 'Meydan okuyan oyuncuyu buluşma haritasında bulup savaş.', {'ad': 'string', 'harita': 'string, ör. "4-4"'},
      izin='pvp')
def duel(y, bot, ad='', harita=None):
    m = _game_map(harita) if harita else None
    if not ad or m is None or not K.can_enter(m, bot.firma, bot.level) or not K.route(bot.game_map, m, bot.firma, bot.level):
        return _error('oraya gidemez')
    B.force(bot, 'duello', plan={'harita': m, 'ad': ad}, pay=1.5, duration=900, now=y.now if y else None)
    bot.memory.event(ad, 'meydan', y.now if y else None)
    return _ok(H.name(m))


@tool('cevrimdisi_ol', 'Oyundan çık (oturumu bitir).', {})
def go_offline(y, bot):
    bot.session_end = y.now if y else 0
    return _ok()


# ------------------------------------------------------------------------------------------------------------ sosyal
@tool('sohbet_yaz', 'Bir kanala yaz.', {'kanal': 'global | firma | klan | grup', 'metin': 'string'}, izin='sohbet')
def write_chat(y, bot, kanal='firma', metin=''):
    if kanal not in ('global', 'firma', 'klan', 'grup') or not str(metin).strip():
        return _error('kanal ya da metin geçersiz')
    y.speak(bot, kanal, str(metin).strip()[:200])
    return _ok()


@tool('fisilda', 'Birine özel mesaj yaz.', {'ad': 'string', 'metin': 'string'}, izin='sohbet')
def whisper(y, bot, ad='', metin=''):
    if not ad or not str(metin).strip():
        return _error('ad ya da metin yok')
    y.speak(bot, 'fisilti', str(metin).strip()[:200], recipient=ad)
    return _ok()


@tool('grup_davet', 'Oyuncuyu grubuna davet et.', {'ad': 'string'}, izin='grup')
def group_invite(y, bot, ad=''):
    import group as GR
    from . import society
    out = GR.handle(society.person(bot), 'InvitationCreationRequest', {'name': ad})
    hata = next((m[1].get('error') for m in out or () if m[0] == 'InvitationErrorCommand'), None)
    if hata is not None:                               # oyuncu başka grupta, çevrimdışı, davet sınırı ...: söz olarak kalır
        from . import interaction as IX
        IX.make_promise(bot, 'grup', ad, y.now if y else 0)
        reason = {GR.GROUP_FULL: 'grup dolu', GR.CANDIDATE_IN_GROUP: 'o zaten bir grupta', GR.CANDIDATE_NONEXISTENT: 'o çevrimiçi değil',
                 GR.BOSS_ONLY: 'yalnız grup lideri davet edebilir', GR.MAX_INVITER: 'çok fazla bekleyen davetin var',
                 GR.MAX_CANDIDATE: 'onun çok fazla bekleyen daveti var', GR.CANDIDATE_BLOCKING: 'seni engellemiş',
                 GR.DUPLICATE_INVITATION: 'davetin zaten gitti, yanıtını bekliyor'}.get(hata, 'hata %s' % hata)
        return _error('davet gitmedi: %s' % reason)
    return _ok()


@tool('gruptan_ayril', 'Gruptan ayrıl.', {}, izin='grup')
def leave_group(y, bot):
    import group as GR
    from . import society
    if GR.group_of(bot.uid) is None:
        return _error('grupta değil')
    GR.handle(society.person(bot), 'LeaveGroupRequest', {})
    return _ok()


@tool('arkadas_ekle', 'Arkadaşlık isteği gönder.', {'ad': 'string'}, izin='arkadas')
def add_friend(y, bot, ad=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.CREATE, 'userName': ad})
    bot.memory.event(ad, 'arkadas', y.now if y else None)
    return _ok()


@tool('arkadas_kabul', 'Gelen arkadaşlık isteğini kabul et.', {'ad': 'string'}, izin='arkadas')
def accept_friend(y, bot, ad=''):
    import contacts as CT
    from . import society
    CT.handle(society.person(bot), 'ContactRequest', {'contactRequestType': CT.ACCEPT, 'userName': ad})
    bot.memory.event(ad, 'arkadas', y.now if y else None)
    return _ok()


@tool('posta_gonder', 'Birine oyun içi posta gönder.', {'ad': 'string', 'konu': 'string', 'metin': 'string'}, izin='sohbet')
def send_mail(y, bot, ad='', konu='', metin=''):
    import mail as PS
    from . import society
    konu, metin = str(konu).strip()[:50], str(metin).strip()[:1500]
    if not ad or len(konu) < 3 or len(metin) < 5:
        return _error('ad, konu ya da metin eksik')
    out = PS.Mail(society.profile(bot), log=lambda *_: None).handle('UserMessageSendRequest', {
        'recipients': [ad], 'subject': konu, 'body': metin, 'recipientType': 'user'})
    return _ok() if out and out[0][1].get('success') else _error('gönderilemedi')


@tool('takip_et', 'Oyuncunun bulunduğu haritaya git ve yanında avlan.', {'ad': 'string'})
def follow(y, bot, ad=''):
    import community as TP
    k = TP.find(name=ad)
    if k is None:
        return _error('böyle biri yok')
    return hunt_npcs(y, bot, harita=H.name(int(k.profile.d['konum'].get('mapId', bot.game_map))))


@tool('klana_basvur', 'Bir klana başvur.', {'klan': 'string: klanın adı ya da etiketi'}, izin='klan')
def apply_to_clan(y, bot, klan=''):
    import clan as KL
    from . import society
    c = next((c for c in KL.CLANS.values() if str(klan).lower() in (c['ad'].lower(), c['etiket'].lower())), None)
    if c is None:
        return _error('klan yok')
    out = KL.Clan(society.profile(bot)).handle('ApplyClanRequest', {'clanId': c['id'], 'message': 'lvl %d' % bot.level})
    society.update(bot)
    return _ok() if out and out[0][1].get('success') else _error('başvurulamadı')


# ------------------------------------------------------------------------------------------------------------ klan yönetimi
# (klan_yonetim.py; lider ya da hakkı olan üye: oyunun klan istekleri hakları kendisi denetler)
def _clan(bot):
    import clan as KL
    from . import society
    k = KL.clan_of(society.profile(bot))
    return k, (KL.Clan(bot.profile, log=lambda *_: None) if k else None)


def _result(out, ok='', hata='yapılamadı (hakkın yok ya da geçersiz)'):
    if out and out[0][1].get('success'):
        return _ok(ok)
    e = out[0][1].get('errorMsg') if out else None
    return _error(hata if not isinstance(e, dict) or not e.get('stringBasekey') else '%s: %s' % (hata, e['stringBasekey']))


@tool('klan_aciklama', 'Klanın açıklamasını yaz (yalnız lider).', {'metin': 'string, en çok 2000 karakter'}, izin='klan')
def clan_description(y, bot, metin=''):
    k, kl = _clan(bot)
    if k is None or not str(metin).strip():
        return _error('klanın yok ya da metin boş')
    return _result(kl.handle('ChangeClanDescriptionRequest', {'desc': str(metin).strip()[:2000]}))


@tool('klan_duyuru', 'Klanın haberlerine duyuru yaz.', {'metin': 'string'}, izin='klan')
def clan_announce(y, bot, metin=''):
    k, kl = _clan(bot)
    if k is None or not str(metin).strip():
        return _error('klanın yok ya da metin boş')
    return _result(kl.handle('ClanAddNewsRequest', {'newsMessage': str(metin).strip()[:500]}))


@tool('klan_postasi', 'Bütün klana posta gönder.', {'konu': 'string', 'metin': 'string'}, izin='klan')
def clan_mail(y, bot, konu='', metin=''):
    k, kl = _clan(bot)
    if k is None or not str(konu).strip() or not str(metin).strip():
        return _error('klanın yok ya da konu/metin boş')
    return _result(kl.handle('ClanSendAllMessageRequest', {'subject': str(konu).strip()[:50], 'msgText': str(metin).strip()[:1500]}))


@tool('klan_rutbe', 'Rütbe ekle, sil ya da haklarını değiştir.', {
    'islem': 'ekle | sil | haklar', 'rutbe': 'string: rütbenin adı',
    'haklar': 'string: virgüllü haklar (hiremember, firemember, editranks, news, roundmail, tax, payout, diplo_start, diplo_end, '
              'diplo_war, battle_station_build, battle_station_replace_module, battle_station_deflector)'}, izin='klan')
def clan_rank(y, bot, islem='ekle', rutbe='', haklar=''):
    import clan as KL
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or not str(rutbe).strip():
        return _error('klanın yok ya da rütbe adı boş')
    right = [h.strip() for h in str(haklar or '').split(',') if h.strip() in KL.RIGHTS]
    if islem == 'ekle':
        out = kl.handle('ClanNewRankRequest', {'newRank': str(rutbe).strip()[:30]})
        r = CMG.find_rank(k, rutbe)
        if out and out[0][1].get('success') and r is not None and right:
            kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['ad'], 'rights': right}]})
        return _result(out, 'rütbe eklendi')
    r = CMG.find_rank(k, rutbe)
    if r is None:
        return _error('böyle bir rütbe yok')
    if islem == 'sil':
        return _result(kl.handle('ClanDeleteRankRequest', {'deleteRankId': r['id']}), 'rütbe silindi')
    if islem == 'haklar':
        return _result(kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['ad'], 'rights': right}]}),
                      'haklar: %s' % (', '.join(right) or 'yok'))
    return _error('islem ekle, sil ya da haklar olmalı')


@tool('uye_rutbe', 'Bir üyeye rütbe ver (boş rütbe: rütbesini al).', {'ad': 'string: üye', 'rutbe': 'string: rütbe adı'}, izin='klan')
def member_rank(y, bot, ad='', rutbe=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    a, u = CMG.find_member(k, ad)
    r = CMG.find_rank(k, rutbe) if str(rutbe or '').strip() else {'id': 0}
    if u is None or r is None:
        return _error('böyle bir üye ya da rütbe yok')
    return _result(kl.handle('EditClanMemberRequest', {'rankId': r['id'], 'memberId': int(u.get('uid', 0))}))


@tool('uyeyi_cikar', 'Bir üyeyi klandan çıkar.', {'ad': 'string'}, izin='klan')
def kick_member(y, bot, ad=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    result = CMG.kick(y, bot, k, kl, y.now if y else 0, name=ad)
    return _ok('%s çıkarıldı' % result) if result else _error('çıkarılamadı (hakkın yok ya da üye değil)')


@tool('liderligi_devret', 'Klanın liderliğini bir üyeye bırak.', {'ad': 'string'}, izin='klan')
def transfer_leadership(y, bot, ad=''):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    result = CMG.hand_over(y, bot, k, kl, y.now if y else 0, name=ad)
    return _ok('lider artık %s' % result) if result else _error('devredilemedi (lider değilsin ya da üye değil)')


@tool('klan_vergi', 'Klanın vergisini ayarla (yüzde 0-5).', {'oran': 'integer'}, izin='klan')
def clan_tax(y, bot, oran=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    return _ok('vergi %%%d' % int(oran)) if CMG.set_tax(bot, k, kl, y.now if y else 0, ratio=int(oran)) else _error('vergi hakkın yok')


@tool('klan_butce', 'Kasanın paylarını ayarla (yüzde; toplamı en çok 90, kalanı yedek): istasyon, üyelere ödeme, savaş.',
      {'ksi': 'integer', 'odeme': 'integer', 'savas': 'integer'}, izin='klan')
def clan_budget(y, bot, ksi=None, odeme=None, savas=None):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None or k['lider'] != bot.name.lower():
        return _error('yalnız lider')
    b = CMG.set_budget(bot, k, y.now if y else 0, *[None if v is None else max(0, int(v)) / 100.0 for v in (ksi, odeme, savas)])
    return _ok('istasyon %d%%, ödeme %d%%, savaş %d%%' % (100 * b['ksi'], 100 * b['odeme'], 100 * b['savas']))


@tool('klan_odeme', 'Kasadan bir üyeye kredi öde.', {'ad': 'string', 'miktar': 'integer'}, izin='klan')
def clan_payout(y, bot, ad='', miktar=0):
    from . import clan_management as CMG
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    a, u = CMG.find_member(k, ad)
    if u is None:
        return _error('böyle bir üye yok')
    return _result(kl.handle('PayoutClanRequest', {'amount': int(miktar), 'payoutUserId': int(u.get('uid', 0)), 'reason': 'payout'}),
                  'ödendi', 'ödenemedi (hakkın yok, kasa yetmiyor ya da üyenin haftalık sınırı doldu)')


@tool('klan_istasyon', 'Klanın istasyon kuracağı boş asteroidi seç (adıyla; modüller kasadan, bütçenin istasyon payıyla).',
      {'istasyon': 'string: asteroidin adı'}, izin='klan_ksi')
def clan_station(y, bot, istasyon=''):
    from . import clan_stations as CBA
    k, kl = _clan(bot)
    if k is None or not CBA.is_open() or not kl.right('battle_station_build', k):
        return _error('istasyon kurma hakkın yok')
    return _ok('hedef: %s' % istasyon) if CBA.set_target(k, istasyon, bot) else _error('böyle boş bir asteroit yok')


_DIPLO = {'baris': 0, 'peace': 0, 'ittifak': 1, 'alliance': 1, 'saldirmazlik': 2, 'nap': 2, 'savas': 3, 'war': 3}


@tool('klan_diplomasi', 'Başka bir klana ittifak, saldırmazlık, savaş ya da barış teklif et.',
      {'klan': 'string: klanın adı ya da etiketi', 'tur': 'ittifak | saldirmazlik | savas | baris', 'metin': 'string'}, izin='klan_diplomasi')
def clan_diplomacy(y, bot, klan='', tur='', metin=''):
    import clan as KL
    k, kl = _clan(bot)
    c = next((c for c in KL.CLANS.values() if str(klan).lower() in (c['ad'].lower(), c['etiket'].lower())), None)
    if k is None or c is None or str(tur).lower() not in _DIPLO:
        return _error('klanın yok, böyle bir klan yok ya da tür geçersiz')
    return _result(kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': _DIPLO[str(tur).lower()],
                                                        'desc': str(metin or '').strip()[:200]}), 'teklif gitti')


@tool('diplomasi_yanit', 'Klanına gelen diplomasi teklifini kabul ya da reddet.', {'klan': 'string', 'kabul': 'boolean'},
      izin='klan_diplomasi')
def diplomacy_reply(y, bot, klan='', kabul=False):
    import clan as KL
    k, kl = _clan(bot)
    if k is None:
        return _error('klanın yok')
    s = str(klan).lower()
    r = None
    for x in k.get('diplo_istek', []):
        o = KL.CLANS.get(x['kimden']) or {}
        if x['kime'] == k['id'] and s in (str(o.get('ad', '')).lower(), str(o.get('etiket', '')).lower()):
            r = x
            break
    if r is None:
        return _error('o klandan bekleyen teklif yok')
    return _result(kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if kabul in (True, 'true', 1) else 'deny'}))


@tool('hicbiri', 'Bir şey yapma.', {})
def none_(y, bot):
    return _ok()


# ------------------------------------------------------------------------------------------------------------ ajanın araçları
# (Gelişmiş kip, güçlü sağlayıcı: bot/ajan.py modele sunar; karar motoru da çağırabilir)
def _item(bot, esya):
    """Mağaza adayı (artis, para, fiyat, loot): tam loot ya da sonu ("lf-2", "goliath") eşleşir."""
    from .goals import shopping as SHOP
    s = str(esya or '').strip().lower()
    if not s:
        return None
    m = bot.game_settings.multiplier('magaza_fiyat')
    for a, p, f, l in SHOP.candidates(bot):
        if l.lower() == s or l.lower().rsplit('_', 1)[-1] == s:
            return a, p, f * m, l
    return None


@tool('esya_al', 'Mağazadan belirli bir yükseltmeyi al (magaza listesindeki ad).', {'esya': 'string: eşyanın adı'}, izin='magaza')
def buy_item(y, bot, esya=''):
    c = _item(bot, esya)
    if c is None:
        return _error('mağaza listesinde yok (ya da yuvası yok / daha iyisi takılı)')
    currency = {'C': bot.k['kredi'], 'U': bot.k['uridyum']}[c[1]]
    if currency < c[2]:
        return _error('para yetmiyor: %d %s gerekli, %d var' % (c[2], c[1], currency))
    if not bot.pay(c[1], c[2]):
        return _error('para yetmedi')
    bot.add(c[3])
    bot.ist('alim')
    bot.event('alim', y.now if y else None, esya=c[3], fiyat=c[2], para=c[1])
    if c[3].startswith('ship_'):
        bot.event('yeni_gemi', y.now if y else None, esya=c[3])
    if bot.k.get('birikim') == c[3]:
        bot.k['birikim'] = None                         # biriktirdiği şeyi aldı
    return _ok('%s alındı (%d %s)' % (c[3], c[2], c[1]))


@tool('biriktir', 'Bir yükseltme için para biriktir (alışveriş başka şeye harcamaz); boş ad hedefi kaldırır.', {'esya': 'string'},
      izin='magaza')
def save_up(y, bot, esya=''):
    if not str(esya or '').strip():
        bot.k['birikim'] = None
        return _ok('biriktirme hedefi kaldırıldı')
    c = _item(bot, esya)
    if c is None:
        return _error('mağaza listesinde yok')
    bot.k['birikim'] = c[3]
    bot._candidates = None
    bot._savings_woke = False                         # para tamamlanınca ajan bir kez uyanır (ajan.uyandiranlar)
    return _ok('%s için biriktiriliyor (%d %s)' % (c[3], c[2], c[1]))


@tool('gorev_sec', 'Alınabilir görevlerden belirli birini al (görev yoksa).', {'gorev': 'string: görevin adı ya da numarası'},
      izin='gorev')
def pick_quest(y, bot, gorev=''):
    from .goals import quest as QU
    if bot.k.get('gorev'):
        return _error('zaten bir görev sürüyor: %s' % QU.quests().get(bot.k['gorev']['id'], {}).get('ad', '?'))
    s = str(gorev or '').strip().lower().lstrip('#')
    for qid, q in QU.eligible(bot):
        if s in (str(qid), str(q.get('ad', '')).lower()):
            bot.k['gorev'] = dict(id=qid, kosullar={})
            if not (QU.next_up(bot) or (None, None))[1]:
                bot.k['gorev'] = None
                return _error('bu görevin yeri şu an gidilebilir değil')
            bot.event('gorev_aldi', y.now if y else None, ad=q.get('ad'))
            B.force(bot, 'gorev', pay=0.9, now=y.now if y else None)
            return _ok('görev alındı: %s' % q.get('ad'))
    return _error('alınabilir görevlerde yok')


@tool('kargo_sat', 'Kargodaki cevherleri en yakın istasyonda sat.', {}, izin='kargo')
def sell_cargo(y, bot):
    if bot.cargo_fill() <= 0:
        return _error('kargo boş')
    B.force(bot, 'satis', pay=1.0, duration=900, now=y.now if y else None)
    return _ok()


@tool('mod_gir', 'Açık bir moda (etkinlik / PvE) gir: bedelini öder, modun haritasına geçer.', {'mod': 'string: modun adı'},
      izin='modlar')
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


@tool('kapi_kos', 'Kurulu Galaksi Kapısına gir.', {}, izin='kapi')
def run_gate(y, bot):
    from . import galaxy_gates as GT
    k = GT.can_run(bot)
    if bot.level < 10 or k is None:
        return _error('geçilebilecek kurulu kapı yok')
    B.force(bot, 'kapi', pay=1.2, duration=900, now=y.now if y else None)
    return _ok(GT.KAPI[k]['ad'])


@tool('oturum', 'Oyunda bu kadar dakika daha kal (5-180).', {'dakika': 'integer'})
def session(y, bot, dakika=30):
    d = max(5, min(180, int(dakika)))
    bot.session_end = (y.now if y else 0) + d * 60
    return _ok('%d dk daha' % d)
