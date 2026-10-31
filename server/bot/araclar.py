"""Botun eylemleri (araçlar): karar motoru, sohbet ve LLM (Gelişmiş kip) bota yalnız bu araçlarla iş yaptırır.

Her araç: ad, açıklama, parametreler (JSON şema; LLM'e verilir), izin (paketin erişim ayarı) ve işlev (yonetici, bot, **arg) ->
{'ok': bool, 'mesaj': str}. Hedef değiştiren araçlar botun niyetini kurar (beyin.zorla): bot işi kendi aklıyla sürdürür, yarıda
kalırsa karar motoru devralır. Yeni bir eylem için buraya @arac ile bir işlev eklemek yeter; şema LLM'e kendiliğinden gider.
"""
import harita as H
from . import beyin as B
from . import katalog as K

ARACLAR = {}


def arac(ad, aciklama, parametreler=None, izin=None):
    def kaydet(fn):
        ARACLAR[ad] = dict(ad=ad, aciklama=aciklama, parametreler=parametreler or {}, izin=izin, fn=fn)
        return fn
    return kaydet


def sema(y=None, adlar=None):
    """LLM için araç listesi: [{ad, aciklama, parametreler}] (izni kapalı olanlar hariç)."""
    out = []
    for a in ARACLAR.values():
        if adlar is not None and a['ad'] not in adlar:
            continue
        if a['izin'] and y is not None and not y.izin(a['izin']):
            continue
        out.append({'ad': a['ad'], 'aciklama': a['aciklama'], 'parametreler': a['parametreler']})
    return out


def cagir(y, bot, ad, arg=None):
    """Aracı çalıştır -> {'ok', 'mesaj'}. Bilinmeyen araç, kapalı izin ya da hatalı argüman hata döner (bot bir şey yapmaz)."""
    a = ARACLAR.get(str(ad or ''))
    if a is None:
        return {'ok': False, 'mesaj': 'bilinmeyen araç'}
    if a['izin'] and y is not None and not y.izin(a['izin']):
        return {'ok': False, 'mesaj': 'izin kapalı'}
    try:
        r = a['fn'](y, bot, **{k: v for k, v in (arg or {}).items() if k in a['parametreler']})
    except (TypeError, ValueError, KeyError) as e:
        return {'ok': False, 'mesaj': 'hatalı argüman: %s' % e}
    except Exception as e:                                  # araç içi hata (AttributeError…) sohbet tikinin kalanını düşürmesin
        return {'ok': False, 'mesaj': 'araç hatası: %r' % e}
    bot.olay('arac', y.now if y is not None else None, ad=ad, sonuc=r.get('ok'))
    return r


def _harita(ad):
    from .konusma import HARITA
    ids = {v.lower(): k for k, v in H.NAMES.items()}
    s = str(ad or '').strip().lower()
    r = HARITA.search(s)
    m = ids.get(s) or (ids.get('%s-%s' % (r.group(1), r.group(2))) if r else None)
    return int(m) if m is not None and int(m) in K.HARITALAR else None


def _ok(m=''):
    return {'ok': True, 'mesaj': m}


def _hata(m):
    return {'ok': False, 'mesaj': m}


# ------------------------------------------------------------------------------------------------------------ hedefler
@arac('npc_avla', 'Uzaylı kas (harita verilirse oraya gidip orada).', {'harita': 'string, ör. "1-3" (isteğe bağlı)'})
def npc_avla(y, bot, harita=None):
    m = _harita(harita) if harita else None
    if harita and (m is None or not K.girebilir(m, bot.firma, bot.seviye)):
        return _hata('haritaya girilemez')
    B.zorla(bot, 'kasilma', plan={'harita': m} if m else {}, pay=0.8, now=y.now if y else None)
    return _ok()


@arac('pvp_avla', 'Düşman firmadan oyuncu avına çık.', {}, izin='pvp')
def pvp_avla(y, bot):
    B.zorla(bot, 'pvp', pay=0.8, now=y.now if y else None)
    return _ok()


@arac('gorev_yap', 'Görev zincirine devam et.', {}, izin='gorev')
def gorev_yap(y, bot):
    B.zorla(bot, 'gorev', pay=0.8, now=y.now if y else None)
    return _ok()


@arac('alisveris_yap', 'Parası yetiyorsa en iyi yükseltmeyi al.', {}, izin='magaza')
def alisveris_yap(y, bot):
    from .hedefler import alisveris as ALIS
    c = ALIS.aday(bot)[0]
    if c is None:
        return _hata('alınacak bir şey yok ya da para yetmiyor')
    if bot.ode(c[1], c[2]):
        bot.ekle(c[3])
        bot.olay('alim', y.now if y else None, esya=c[3], fiyat=c[2], para=c[1])
        if c[3].startswith('ship_'):
            bot.olay('yeni_gemi', y.now if y else None, esya=c[3])
        return _ok(c[3])
    return _hata('para yetmedi')


@arac('dinlen', 'Üste dön ve bir süre dinlen / sohbet et.', {})
def dinlen(y, bot):
    B.zorla(bot, 'dinlenme', pay=0.8, sure=900, now=y.now if y else None)
    return _ok()


@arac('yardima_git', 'Yardım isteyen oyuncunun haritasına gidip düşmanlarla savaş.', {'harita': 'string, ör. "2-4"', 'ad': 'string: yardım isteyen'},
      izin='yardim')
def yardima_git(y, bot, harita=None, ad=''):
    m = _harita(harita) if harita else None
    if m is None and ad:
        import topluluk as TP
        k = TP.bul(ad=ad)
        m = int(k.profil.d['konum'].get('mapId', 0)) if k is not None else None
    if m is None or m not in K.HARITALAR or not K.girebilir(m, bot.firma, bot.seviye) or not K.yol(bot.harita, m, bot.firma, bot.seviye):
        return _hata('oraya gidemez')
    B.zorla(bot, 'yardim', plan={'harita': m, 'ad': ad}, pay=1.2, sure=900, now=y.now if y else None)
    if ad:
        bot.hafiza.olay(ad, 'yardim_ettim', y.now if y else None)
    return _ok(H.name(m))


@arac('duello', 'Meydan okuyan oyuncuyu buluşma haritasında bulup savaş.', {'ad': 'string', 'harita': 'string, ör. "4-4"'},
      izin='pvp')
def duello(y, bot, ad='', harita=None):
    m = _harita(harita) if harita else None
    if not ad or m is None or not K.girebilir(m, bot.firma, bot.seviye) or not K.yol(bot.harita, m, bot.firma, bot.seviye):
        return _hata('oraya gidemez')
    B.zorla(bot, 'duello', plan={'harita': m, 'ad': ad}, pay=1.5, sure=900, now=y.now if y else None)
    bot.hafiza.olay(ad, 'meydan', y.now if y else None)
    return _ok(H.name(m))


@arac('cevrimdisi_ol', 'Oyundan çık (oturumu bitir).', {})
def cevrimdisi_ol(y, bot):
    bot.oturum_bitis = y.now if y else 0
    return _ok()


# ------------------------------------------------------------------------------------------------------------ sosyal
@arac('sohbet_yaz', 'Bir kanala yaz.', {'kanal': 'global | firma | klan | grup', 'metin': 'string'}, izin='sohbet')
def sohbet_yaz(y, bot, kanal='firma', metin=''):
    if kanal not in ('global', 'firma', 'klan', 'grup') or not str(metin).strip():
        return _hata('kanal ya da metin geçersiz')
    y.konus(bot, kanal, str(metin).strip()[:200])
    return _ok()


@arac('fisilda', 'Birine özel mesaj yaz.', {'ad': 'string', 'metin': 'string'}, izin='sohbet')
def fisilda(y, bot, ad='', metin=''):
    if not ad or not str(metin).strip():
        return _hata('ad ya da metin yok')
    y.konus(bot, 'fisilti', str(metin).strip()[:200], alici=ad)
    return _ok()


@arac('grup_davet', 'Oyuncuyu grubuna davet et.', {'ad': 'string'}, izin='grup')
def grup_davet(y, bot, ad=''):
    import grup as GR
    from . import toplum
    out = GR.handle(toplum.kisi(bot), 'InvitationCreationRequest', {'name': ad})
    hata = next((m[1].get('error') for m in out or () if m[0] == 'InvitationErrorCommand'), None)
    if hata is not None:                               # oyuncu başka grupta, çevrimdışı, davet sınırı ...: söz olarak kalır
        from . import etkilesim as ET
        ET.soz_ver(bot, 'grup', ad, y.now if y else 0)
        neden = {GR.GROUP_FULL: 'grup dolu', GR.CANDIDATE_IN_GROUP: 'o zaten bir grupta', GR.CANDIDATE_NONEXISTENT: 'o çevrimiçi değil',
                 GR.BOSS_ONLY: 'yalnız grup lideri davet edebilir', GR.MAX_INVITER: 'çok fazla bekleyen davetin var',
                 GR.MAX_CANDIDATE: 'onun çok fazla bekleyen daveti var', GR.CANDIDATE_BLOCKING: 'seni engellemiş',
                 GR.DUPLICATE_INVITATION: 'davetin zaten gitti, yanıtını bekliyor'}.get(hata, 'hata %s' % hata)
        return _hata('davet gitmedi: %s' % neden)
    return _ok()


@arac('gruptan_ayril', 'Gruptan ayrıl.', {}, izin='grup')
def gruptan_ayril(y, bot):
    import grup as GR
    from . import toplum
    if GR.grubu(bot.uid) is None:
        return _hata('grupta değil')
    GR.handle(toplum.kisi(bot), 'LeaveGroupRequest', {})
    return _ok()


@arac('arkadas_ekle', 'Arkadaşlık isteği gönder.', {'ad': 'string'}, izin='arkadas')
def arkadas_ekle(y, bot, ad=''):
    import rehber as RH
    from . import toplum
    RH.handle(toplum.kisi(bot), 'ContactRequest', {'contactRequestType': RH.OLUSTUR, 'userName': ad})
    bot.hafiza.olay(ad, 'arkadas', y.now if y else None)
    return _ok()


@arac('arkadas_kabul', 'Gelen arkadaşlık isteğini kabul et.', {'ad': 'string'}, izin='arkadas')
def arkadas_kabul(y, bot, ad=''):
    import rehber as RH
    from . import toplum
    RH.handle(toplum.kisi(bot), 'ContactRequest', {'contactRequestType': RH.KABUL, 'userName': ad})
    bot.hafiza.olay(ad, 'arkadas', y.now if y else None)
    return _ok()


@arac('posta_gonder', 'Birine oyun içi posta gönder.', {'ad': 'string', 'konu': 'string', 'metin': 'string'}, izin='sohbet')
def posta_gonder(y, bot, ad='', konu='', metin=''):
    import posta as PS
    from . import toplum
    konu, metin = str(konu).strip()[:50], str(metin).strip()[:1500]
    if not ad or len(konu) < 3 or len(metin) < 5:
        return _hata('ad, konu ya da metin eksik')
    out = PS.Posta(toplum.profil(bot), log=lambda *_: None).handle('UserMessageSendRequest', {
        'recipients': [ad], 'subject': konu, 'body': metin, 'recipientType': 'user'})
    return _ok() if out and out[0][1].get('success') else _hata('gönderilemedi')


@arac('takip_et', 'Oyuncunun bulunduğu haritaya git ve yanında avlan.', {'ad': 'string'})
def takip_et(y, bot, ad=''):
    import topluluk as TP
    k = TP.bul(ad=ad)
    if k is None:
        return _hata('böyle biri yok')
    return npc_avla(y, bot, harita=H.name(int(k.profil.d['konum'].get('mapId', bot.harita))))


@arac('klana_basvur', 'Bir klana başvur.', {'klan': 'string: klanın adı ya da etiketi'}, izin='klan')
def klana_basvur(y, bot, klan=''):
    import klan as KL
    from . import toplum
    c = next((c for c in KL.KLANLAR.values() if str(klan).lower() in (c['ad'].lower(), c['etiket'].lower())), None)
    if c is None:
        return _hata('klan yok')
    out = KL.Klan(toplum.profil(bot)).handle('ApplyClanRequest', {'clanId': c['id'], 'message': 'lvl %d' % bot.seviye})
    toplum.guncelle(bot)
    return _ok() if out and out[0][1].get('success') else _hata('başvurulamadı')


# ------------------------------------------------------------------------------------------------------------ klan yönetimi
# (klan_yonetim.py; lider ya da hakkı olan üye: oyunun klan istekleri hakları kendisi denetler)
def _klan(bot):
    import klan as KL
    from . import toplum
    k = KL.klani(toplum.profil(bot))
    return k, (KL.Klan(bot.profil, log=lambda *_: None) if k else None)


def _sonuc(out, ok='', hata='yapılamadı (hakkın yok ya da geçersiz)'):
    if out and out[0][1].get('success'):
        return _ok(ok)
    e = out[0][1].get('errorMsg') if out else None
    return _hata(hata if not isinstance(e, dict) or not e.get('stringBasekey') else '%s: %s' % (hata, e['stringBasekey']))


@arac('klan_aciklama', 'Klanın açıklamasını yaz (yalnız lider).', {'metin': 'string, en çok 2000 karakter'}, izin='klan')
def klan_aciklama(y, bot, metin=''):
    k, kl = _klan(bot)
    if k is None or not str(metin).strip():
        return _hata('klanın yok ya da metin boş')
    return _sonuc(kl.handle('ChangeClanDescriptionRequest', {'desc': str(metin).strip()[:2000]}))


@arac('klan_duyuru', 'Klanın haberlerine duyuru yaz.', {'metin': 'string'}, izin='klan')
def klan_duyuru(y, bot, metin=''):
    k, kl = _klan(bot)
    if k is None or not str(metin).strip():
        return _hata('klanın yok ya da metin boş')
    return _sonuc(kl.handle('ClanAddNewsRequest', {'newsMessage': str(metin).strip()[:500]}))


@arac('klan_postasi', 'Bütün klana posta gönder.', {'konu': 'string', 'metin': 'string'}, izin='klan')
def klan_postasi(y, bot, konu='', metin=''):
    k, kl = _klan(bot)
    if k is None or not str(konu).strip() or not str(metin).strip():
        return _hata('klanın yok ya da konu/metin boş')
    return _sonuc(kl.handle('ClanSendAllMessageRequest', {'subject': str(konu).strip()[:50], 'msgText': str(metin).strip()[:1500]}))


@arac('klan_rutbe', 'Rütbe ekle, sil ya da haklarını değiştir.', {
    'islem': 'ekle | sil | haklar', 'rutbe': 'string: rütbenin adı',
    'haklar': 'string: virgüllü haklar (hiremember, firemember, editranks, news, roundmail, tax, payout, diplo_start, diplo_end, '
              'diplo_war, battle_station_build, battle_station_replace_module, battle_station_deflector)'}, izin='klan')
def klan_rutbe(y, bot, islem='ekle', rutbe='', haklar=''):
    import klan as KL
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None or not str(rutbe).strip():
        return _hata('klanın yok ya da rütbe adı boş')
    hak = [h.strip() for h in str(haklar or '').split(',') if h.strip() in KL.HAKLAR]
    if islem == 'ekle':
        out = kl.handle('ClanNewRankRequest', {'newRank': str(rutbe).strip()[:30]})
        r = KY.rutbe_bul(k, rutbe)
        if out and out[0][1].get('success') and r is not None and hak:
            kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['ad'], 'rights': hak}]})
        return _sonuc(out, 'rütbe eklendi')
    r = KY.rutbe_bul(k, rutbe)
    if r is None:
        return _hata('böyle bir rütbe yok')
    if islem == 'sil':
        return _sonuc(kl.handle('ClanDeleteRankRequest', {'deleteRankId': r['id']}), 'rütbe silindi')
    if islem == 'haklar':
        return _sonuc(kl.handle('EditClanRanksRequest', {'ranks': [{'rankId': r['id'], 'rankName': r['ad'], 'rights': hak}]}),
                      'haklar: %s' % (', '.join(hak) or 'yok'))
    return _hata('islem ekle, sil ya da haklar olmalı')


@arac('uye_rutbe', 'Bir üyeye rütbe ver (boş rütbe: rütbesini al).', {'ad': 'string: üye', 'rutbe': 'string: rütbe adı'}, izin='klan')
def uye_rutbe(y, bot, ad='', rutbe=''):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    a, u = KY.uye_bul(k, ad)
    r = KY.rutbe_bul(k, rutbe) if str(rutbe or '').strip() else {'id': 0}
    if u is None or r is None:
        return _hata('böyle bir üye ya da rütbe yok')
    return _sonuc(kl.handle('EditClanMemberRequest', {'rankId': r['id'], 'memberId': int(u.get('uid', 0))}))


@arac('uyeyi_cikar', 'Bir üyeyi klandan çıkar.', {'ad': 'string'}, izin='klan')
def uyeyi_cikar(y, bot, ad=''):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    sonuc = KY.cikar(y, bot, k, kl, y.now if y else 0, ad=ad)
    return _ok('%s çıkarıldı' % sonuc) if sonuc else _hata('çıkarılamadı (hakkın yok ya da üye değil)')


@arac('liderligi_devret', 'Klanın liderliğini bir üyeye bırak.', {'ad': 'string'}, izin='klan')
def liderligi_devret(y, bot, ad=''):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    sonuc = KY.devret(y, bot, k, kl, y.now if y else 0, ad=ad)
    return _ok('lider artık %s' % sonuc) if sonuc else _hata('devredilemedi (lider değilsin ya da üye değil)')


@arac('klan_vergi', 'Klanın vergisini ayarla (yüzde 0-5).', {'oran': 'integer'}, izin='klan')
def klan_vergi(y, bot, oran=0):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    return _ok('vergi %%%d' % int(oran)) if KY.vergi_ayarla(bot, k, kl, y.now if y else 0, oran=int(oran)) else _hata('vergi hakkın yok')


@arac('klan_butce', 'Kasanın paylarını ayarla (yüzde; toplamı en çok 90, kalanı yedek): istasyon, üyelere ödeme, savaş.',
      {'ksi': 'integer', 'odeme': 'integer', 'savas': 'integer'}, izin='klan')
def klan_butce(y, bot, ksi=None, odeme=None, savas=None):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None or k['lider'] != bot.ad.lower():
        return _hata('yalnız lider')
    b = KY.butce_ayarla(bot, k, y.now if y else 0, *[None if v is None else max(0, int(v)) / 100.0 for v in (ksi, odeme, savas)])
    return _ok('istasyon %d%%, ödeme %d%%, savaş %d%%' % (100 * b['ksi'], 100 * b['odeme'], 100 * b['savas']))


@arac('klan_odeme', 'Kasadan bir üyeye kredi öde.', {'ad': 'string', 'miktar': 'integer'}, izin='klan')
def klan_odeme(y, bot, ad='', miktar=0):
    from . import klan_yonetim as KY
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    a, u = KY.uye_bul(k, ad)
    if u is None:
        return _hata('böyle bir üye yok')
    return _sonuc(kl.handle('PayoutClanRequest', {'amount': int(miktar), 'payoutUserId': int(u.get('uid', 0)), 'reason': 'payout'}),
                  'ödendi', 'ödenemedi (hakkın yok, kasa yetmiyor ya da üyenin haftalık sınırı doldu)')


@arac('klan_istasyon', 'Klanın istasyon kuracağı boş asteroidi seç (adıyla; modüller kasadan, bütçenin istasyon payıyla).',
      {'istasyon': 'string: asteroidin adı'}, izin='klan_ksi')
def klan_istasyon(y, bot, istasyon=''):
    from . import klan_us as KU
    k, kl = _klan(bot)
    if k is None or not KU.acik() or not kl.hak('battle_station_build', k):
        return _hata('istasyon kurma hakkın yok')
    return _ok('hedef: %s' % istasyon) if KU.hedefle(k, istasyon, bot) else _hata('böyle boş bir asteroit yok')


_DIPLO = {'baris': 0, 'peace': 0, 'ittifak': 1, 'alliance': 1, 'saldirmazlik': 2, 'nap': 2, 'savas': 3, 'war': 3}


@arac('klan_diplomasi', 'Başka bir klana ittifak, saldırmazlık, savaş ya da barış teklif et.',
      {'klan': 'string: klanın adı ya da etiketi', 'tur': 'ittifak | saldirmazlik | savas | baris', 'metin': 'string'}, izin='klan_diplomasi')
def klan_diplomasi(y, bot, klan='', tur='', metin=''):
    import klan as KL
    k, kl = _klan(bot)
    c = next((c for c in KL.KLANLAR.values() if str(klan).lower() in (c['ad'].lower(), c['etiket'].lower())), None)
    if k is None or c is None or str(tur).lower() not in _DIPLO:
        return _hata('klanın yok, böyle bir klan yok ya da tür geçersiz')
    return _sonuc(kl.handle('ClanNewDiplomacyRequest', {'diploClanID': c['id'], 'diploForm': _DIPLO[str(tur).lower()],
                                                        'desc': str(metin or '').strip()[:200]}), 'teklif gitti')


@arac('diplomasi_yanit', 'Klanına gelen diplomasi teklifini kabul ya da reddet.', {'klan': 'string', 'kabul': 'boolean'},
      izin='klan_diplomasi')
def diplomasi_yanit(y, bot, klan='', kabul=False):
    import klan as KL
    k, kl = _klan(bot)
    if k is None:
        return _hata('klanın yok')
    s = str(klan).lower()
    r = None
    for x in k.get('diplo_istek', []):
        o = KL.KLANLAR.get(x['kimden']) or {}
        if x['kime'] == k['id'] and s in (str(o.get('ad', '')).lower(), str(o.get('etiket', '')).lower()):
            r = x
            break
    if r is None:
        return _hata('o klandan bekleyen teklif yok')
    return _sonuc(kl.handle('ClanEditDiploOfferRequest', {'diploId': r['id'], 'status': 'allow' if kabul in (True, 'true', 1) else 'deny'}))


@arac('hicbiri', 'Bir şey yapma.', {})
def hicbiri(y, bot):
    return _ok()


# ------------------------------------------------------------------------------------------------------------ ajanın araçları
# (Gelişmiş kip, güçlü sağlayıcı: bot/ajan.py modele sunar; karar motoru da çağırabilir)
def _esya(bot, esya):
    """Mağaza adayı (artis, para, fiyat, loot): tam loot ya da sonu ("lf-2", "goliath") eşleşir."""
    from .hedefler import alisveris as ALIS
    s = str(esya or '').strip().lower()
    if not s:
        return None
    m = bot.oa.carpan('magaza_fiyat')
    for a, p, f, l in ALIS.adaylar(bot):
        if l.lower() == s or l.lower().rsplit('_', 1)[-1] == s:
            return a, p, f * m, l
    return None


@arac('esya_al', 'Mağazadan belirli bir yükseltmeyi al (magaza listesindeki ad).', {'esya': 'string: eşyanın adı'}, izin='magaza')
def esya_al(y, bot, esya=''):
    c = _esya(bot, esya)
    if c is None:
        return _hata('mağaza listesinde yok (ya da yuvası yok / daha iyisi takılı)')
    para = {'C': bot.k['kredi'], 'U': bot.k['uridyum']}[c[1]]
    if para < c[2]:
        return _hata('para yetmiyor: %d %s gerekli, %d var' % (c[2], c[1], para))
    if not bot.ode(c[1], c[2]):
        return _hata('para yetmedi')
    bot.ekle(c[3])
    bot.ist('alim')
    bot.olay('alim', y.now if y else None, esya=c[3], fiyat=c[2], para=c[1])
    if c[3].startswith('ship_'):
        bot.olay('yeni_gemi', y.now if y else None, esya=c[3])
    if bot.k.get('birikim') == c[3]:
        bot.k['birikim'] = None                         # biriktirdiği şeyi aldı
    return _ok('%s alındı (%d %s)' % (c[3], c[2], c[1]))


@arac('biriktir', 'Bir yükseltme için para biriktir (alışveriş başka şeye harcamaz); boş ad hedefi kaldırır.', {'esya': 'string'},
      izin='magaza')
def biriktir(y, bot, esya=''):
    if not str(esya or '').strip():
        bot.k['birikim'] = None
        return _ok('biriktirme hedefi kaldırıldı')
    c = _esya(bot, esya)
    if c is None:
        return _hata('mağaza listesinde yok')
    bot.k['birikim'] = c[3]
    bot._adaylar = None
    bot._birikim_uyandi = False                         # para tamamlanınca ajan bir kez uyanır (ajan.uyandiranlar)
    return _ok('%s için biriktiriliyor (%d %s)' % (c[3], c[2], c[1]))


@arac('gorev_sec', 'Alınabilir görevlerden belirli birini al (görev yoksa).', {'gorev': 'string: görevin adı ya da numarası'},
      izin='gorev')
def gorev_sec(y, bot, gorev=''):
    from .hedefler import gorev as GV
    if bot.k.get('gorev'):
        return _hata('zaten bir görev sürüyor: %s' % GV.gorevler().get(bot.k['gorev']['id'], {}).get('ad', '?'))
    s = str(gorev or '').strip().lower().lstrip('#')
    for qid, q in GV.uygunlar(bot):
        if s in (str(qid), str(q.get('ad', '')).lower()):
            bot.k['gorev'] = dict(id=qid, kosullar={})
            if not (GV.siradaki(bot) or (None, None))[1]:
                bot.k['gorev'] = None
                return _hata('bu görevin yeri şu an gidilebilir değil')
            bot.olay('gorev_aldi', y.now if y else None, ad=q.get('ad'))
            B.zorla(bot, 'gorev', pay=0.9, now=y.now if y else None)
            return _ok('görev alındı: %s' % q.get('ad'))
    return _hata('alınabilir görevlerde yok')


@arac('kargo_sat', 'Kargodaki cevherleri en yakın istasyonda sat.', {}, izin='kargo')
def kargo_sat(y, bot):
    if bot.kargo_dolu() <= 0:
        return _hata('kargo boş')
    B.zorla(bot, 'satis', pay=1.0, sure=900, now=y.now if y else None)
    return _ok()


@arac('mod_gir', 'Açık bir moda (etkinlik / PvE) gir: bedelini öder, modun haritasına geçer.', {'mod': 'string: modun adı'},
      izin='modlar')
def mod_gir(y, bot, mod=''):
    from . import modlar as MD
    now = y.now if y else None
    s = str(mod or '').strip().lower()
    m = next((m for m in MD.adaylar(bot, now) if s in (m.kimlik.lower(), str(m.ad).lower())), None)
    if m is None:
        return _hata('bu mod şu an girilebilir değil')
    bot._mod_aday, bot._mod_bak = m, (now or 0) + 300
    B.zorla(bot, 'mod', pay=1.2, sure=900, now=now)
    return _ok(m.ad)


@arac('kapi_kos', 'Kurulu Galaksi Kapısına gir.', {}, izin='kapi')
def kapi_kos(y, bot):
    from . import kapi as KP
    k = KP.kosulabilir(bot)
    if bot.seviye < 10 or k is None:
        return _hata('geçilebilecek kurulu kapı yok')
    B.zorla(bot, 'kapi', pay=1.2, sure=900, now=y.now if y else None)
    return _ok(KP.KAPI[k]['ad'])


@arac('oturum', 'Oyunda bu kadar dakika daha kal (5-180).', {'dakika': 'integer'})
def oturum(y, bot, dakika=30):
    d = max(5, min(180, int(dakika)))
    bot.oturum_bitis = (y.now if y else 0) + d * 60
    return _ok('%d dk daha' % d)
