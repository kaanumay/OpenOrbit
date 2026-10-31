"""Botun ajanı (Gelişmiş kip, güçlü sağlayıcı: llm.GUCLU): model, Claude Code'un araç döngüsü gibi oyunu araçlarla oynar.

Her düşünme anında (dusun) model adım adım ilerler: kısa düşünce -> bir araç -> aracın sonucu -> sonraki adım; en çok
llm_ajan_adim adım, "bitir" ile biter. Araçlar üç türlü:
  gözlem    salt okunur: durum, haritalar, magaza, gorevler, etkinlikler, cevre, klan, defter, anilar (bakmadan karar vermesin)
  eylem     araclar.py'nin araçları (hedef niyetleri, alışveriş, görev, mod, kapı, sosyal ...): paketin izinleri aynen geçerli
  kendini yönetme: defter (uzun vadeli hedefler), hatirlat (kendini N dakika sonra uyandırır), not_al (anı defterine not)
Karar araçları kurallı karar motoruna güçlü niyet olarak gider (beyin.zorla): uçuş, savaş ve ayrıntı yine govde/soyut'ta.

Ne zaman düşünür (llm.Beyin._ajan_tick): llm_karar_dk'da bir; önemli olayda (öldü, seviye, görev bitti, yeni gemi, kargo doldu,
biriktirdiği para tamam) ve hatırlatıcının vakti gelince. Saatlik istek sınırı (llm_saatlik) aşılınca kurallı motor sürer.
Botun son adımları k['ajan']'da (izlemek için), defter k['defter'], hatırlatıcılar k['hatirlatici'].
"""
import json, time

import harita as H
import profil as PF
from . import ani as ANI
from . import araclar as AR
from . import beyin as B
from . import katalog as K

ADIM = 3                         # düşünme başına en çok istek (adımda birden çok araç)
UYANDIRAN = {'olum': 'you just got shot down', 'seviye': 'you just reached a new level', 'gorev_bitti': 'you just finished a quest',
             'yeni_gemi': 'you just got a new ship', 'oyuncu_oldurdum': 'you just shot down a player'}
DEFTER_EN_COK = 8


# ------------------------------------------------------------------------------------------------------------ gözlem
def _para(n):
    return '{:,}'.format(int(n))


def _kisa(loot):
    return str(loot).rsplit('_', 1)[-1]


def g_durum(y, b, arg):
    from .hedefler import gorev as GV, alisveris as ALIS
    from . import silah as SL
    d = b.deger()
    PF.level_for(0)                                      # seviye eşikleri yüklensin
    sonraki = next((need for lv, need in (PF._LEVELS or []) if lv == b.seviye + 1), None)
    out = ['Level %d (EP %s%s). Ship %s, power %.0f (damage/s %.0f, effective HP %.0f).' % (
        b.seviye, _para(b.k['ep']), (' / next level at %s' % _para(sonraki)) if sonraki else '', _kisa(b.k['ekip']['gemi']), d['guc'],
        d['dps'], d['ehp']),
        'Credits %s, uridium %s, honor %s. Cargo %d%% full.' % (_para(b.k['kredi']), _para(b.k['uridyum']), _para(b.k['onur']),
                                                              100 * b.kargo_dolu()),
        'Ammo: %s.' % ', '.join('%s x%s' % (_kisa(k), _para(v)) for k, v in sorted(SL.stok(b).items(), key=lambda x: -x[1])[:5] if v)]
    hedef = b.hedef.ad if b.hedef is not None else 'nothing'
    out.append('On map %s, doing: %s for %d min.' % (H.name(b.harita), hedef, max(0, y.now - b.hedef_bas) // 60))
    out.append("You fly for %s: %d-x maps are your company's, 4-x maps are shared PvP land, the other companies' maps are enemy "
               "land." % (('MMO', 'EIC', 'VRU')[b.firma - 1], b.firma))
    if not _lazer(b):
        out.append('You have NO laser ammo: you cannot fight until you get some (credits) or sell cargo.')
    g = b.k.get('gorev')
    if g:
        q = GV.gorevler().get(g['id'], {})
        s = GV.siradaki(b)
        out.append('Quest: %s%s.' % (q.get('ad', '?'), (' (next step on %s)' % ', '.join(H.name(m) for m in s[1][:3])) if s and s[1] else ''))
    _, birikim = ALIS.aday(b)
    if b.k.get('birikim') or birikim:
        hedef_l = b.k.get('birikim') or birikim[3]
        out.append('Saving for: %s%s.' % (_kisa(hedef_l), ' (your own choice)' if b.k.get('birikim') else ''))
    out.append('Session: about %d more minutes online.' % max(0, (b.oturum_bitis - y.now) // 60))
    return ' '.join(out)


def g_haritalar(y, b, arg):
    bg = B.Baglam(b, y, y.now)
    satir = []
    for fayda, m, r in bg.harita[:7]:
        risk = 'high' if r['olum_saat'] > 0.5 else 'medium' if r['olum_saat'] > 0.15 else 'low'
        yol = K.yol(b.harita, m, b.firma, b.seviye) or [m]
        adlar = sorted({str(v['ad']) for v, n in K.harita_npcleri(m)})[:4]
        sahip = H.company(m)
        kimin = 'your company' if sahip == b.firma else 'enemy company' if sahip else 'shared PvP'
        satir.append('%s (%s): EP/h %s, credits/h %s, uridium/h %.0f, death risk %s, %d jumps, aliens: %s' % (
            H.name(m), kimin, _para(r['saat_ep']), _para(r['saat_kredi']), r['saat_uridyum'], risk, len(yol) - 1,
            ', '.join(adlar) or '-'))
    if satir:
        return 'Best maps you can reach (best first):\n' + '\n'.join(satir)
    return 'No farmable map reachable: %s' % ('you have no laser ammo, so you cannot kill anything (get ammo or sell cargo first).'
                                             if not _lazer(b) else 'your ship is too weak for any map you can reach.')


def _lazer(b):
    from . import silah as SL
    return any(v > 0 for k, v in SL.stok(b).items() if 'laser' in k)


def g_magaza(y, b, arg):
    from .hedefler import alisveris as ALIS
    if not y.izin('magaza'):
        return 'The shop is closed for you.'
    m = b.oa.carpan('magaza_fiyat')
    guc = max(1.0, b.deger()['guc'])
    para = {'C': b.k['kredi'], 'U': b.k['uridyum']}
    hepsi = ALIS.adaylar(b)
    tum = sorted(hepsi, key=lambda c: -c[0] / max(1.0, c[2] * m * (ALIS.KUR if c[1] == 'U' else 1)))[:7]
    tum += sorted((c for c in hepsi if c not in tum), key=lambda c: -c[0])[:3]       # büyük hedefler (gemi ...): biriktirmeye değer
    if not tum:
        return 'Nothing in the shop would improve your ship right now.'
    satir = ['%s: +%.0f%% power, %s %s, %s' % (_kisa(l), 100 * a / guc, _para(f * m), 'uridium' if p == 'U' else 'credits',
                                               'affordable now' if para[p] >= f * m else 'need %s more' % _para(f * m - para[p]))
             for a, p, f, l in tum]
    return ('Shop upgrades (best value first, the last ones are the biggest upgrades; use the name with esya_al / biriktir):\n'
            + '\n'.join(satir))


def g_gorevler(y, b, arg):
    from .hedefler import gorev as GV
    if not y.izin('gorev'):
        return 'Quests are closed for you.'
    out = []
    g = b.k.get('gorev')
    if g:
        out.append('Active quest: %s.' % GV.gorevler().get(g['id'], {}).get('ad', '?'))
    u = yapilabilir_gorevler(b)[:8]
    if u:
        out.append('Quests you can take: %s.' % '; '.join('%s (#%s, level %s)' % (q.get('ad'), qid, q['seviye']) for qid, q in u))
    return ' '.join(out) or 'No quests available.'


def yapilabilir_gorevler(b):
    """Alınabilir görevlerden şu an yeri gidilebilir olanlar (karar motorunun gorev.basla süzgeciyle aynı)."""
    from .hedefler import gorev as GV
    if b.k.get('gorev'):
        return []
    out = []
    try:
        for qid, q in GV.uygunlar(b):
            b.k['gorev'] = dict(id=qid, kosullar={})
            s = GV.siradaki(b)
            if s and s[1]:
                out.append((qid, q))
            if len(out) >= 8:
                break
    finally:
        b.k['gorev'] = None
    return out


def g_etkinlikler(y, b, arg):
    from . import modlar as MD, kapi as KP
    out = []
    if y.izin('modlar') and b.seviye >= 8:
        a = sorted(MD.adaylar(b, y.now), key=lambda m: -MD.deger(b, m))[:6]
        if a:
            out.append('Open modes you can enter (mod_gir): %s.' % '; '.join('%s (worth ~%s credits/h)' % (m.ad, _para(MD.deger(b, m)))
                                                                             for m in a))
    if y.izin('kapi') and b.seviye >= 10:
        k = KP.kosulabilir(b)
        if k:
            out.append('Galaxy gate ready to run (kapi_kos): %s.' % KP.KAPI[k]['ad'])
    return ' '.join(out) or 'No mode or gate open for you right now.'


def g_cevre(y, b, arg):
    out = []
    try:
        insan = y.cevrimici_insanlar()
    except Exception:
        insan = []
    if insan:
        out.append('Real players online: %s.' % '; '.join('%s (%s, on %s, you feel %s)' % (
            k.ad, ('MMO', 'EIC', 'VRU')[int(k.profil.d['pilot'].get('factionId', 1)) - 1],
            H.name(int(k.profil.d['konum'].get('mapId', 0))), _his(b.hafiza.iliski(k.ad, y.now))) for k in insan[:6]))
    dost = [x for x in y.botlar if x is not b and x.cevrimici and b.hafiza.iliski(x.ad, y.now) >= 0.3][:5]
    if dost:
        out.append('Friends online: %s.' % ', '.join('%s (on %s)' % (x.ad, H.name(x.harita)) for x in dost))
    kin = [x for x in y.botlar if x is not b and x.cevrimici and b.hafiza.iliski(x.ad, y.now) <= -0.3][:4]
    if kin:
        out.append('People you hold a grudge against online: %s.' % ', '.join('%s (on %s)' % (x.ad, H.name(x.harita)) for x in kin))
    burada = [x for x in y.haritada.get(b.harita, ()) if x is not b][:8]
    if burada:
        out.append('Pilots on your map: %s.' % ', '.join('%s (%s)' % (x.ad, ('MMO', 'EIC', 'VRU')[x.firma - 1]) for x in burada))
    return ' '.join(out) or 'Nobody you know is around.'


def _his(d):
    return 'friendly' if d >= 0.3 else 'hostile' if d <= -0.3 else 'neutral'


def g_klan(y, b, arg):
    try:
        import klan as KL
        k = KL.klani(b.profil) if b.profil is not None else None
    except Exception:
        k = None
    if not k:
        return 'You are in no clan.' + (' Clans are closed for you.' if not y.izin('klan') else
                                       ' You can apply with klana_basvur (clan name or tag).')
    from . import klan_yonetim as KY, klan_us as KU
    lider = k['lider'] == b.ad.lower()
    out = [KY.bilgi_ozeti(k), 'You are the LEADER: you manage everything (klan_* tools).' if lider else
           'Your rights: %s.' % (', '.join(h for h in KL.HAKLAR if KL.hak(b.profil, h)) or 'none')]
    if lider or KL.hak(b.profil, 'battle_station_build'):
        out.append(KU.ozet(k))
    return '\n'.join(x for x in out if x)


def g_defter(y, b, arg):
    d = [x for x in b.k.get('defter') or [] if not x.get('bitti')]
    h = b.k.get('hatirlatici') or []
    out = ['Your goals: %s.' % ('; '.join('#%d %s' % (i + 1, x['metin']) for i, x in enumerate(d)) if d else 'none written')]
    if h:
        out.append('Reminders: %s.' % '; '.join('in %d min: %s' % (max(0, x['vade'] - y.now) // 60, x['metin']) for x in h))
    return ' '.join(out)


def g_anilar(y, b, arg):
    kim = str(arg.get('ad') or arg.get('kim') or '').strip()
    if kim:
        return ANI.metin(b, kim, y.now).strip() or 'You remember nothing about %s.' % kim
    la = ANI.onemli(b, y.now, 6)
    return ('Strongest memories: %s.' % '; '.join('%s (%s)' % (a['ozet'], ANI.ne_zaman(y.now - a['t'])) for a in la)) if la else \
        'No strong memories.'


GOZLEM = {
    'durum': (g_durum, 'your level, ship, power, money, cargo, ammo, current activity, quest, saving goal, session time', ''),
    'haritalar': (g_haritalar, 'the best maps you can reach for farming: EP/credits/uridium per hour, death risk, jumps, aliens', ''),
    'magaza': (g_magaza, 'shop upgrades that improve your ship, with price and whether you can afford them', ''),
    'gorevler': (g_gorevler, 'your active quest and the quests you can take', ''),
    'etkinlikler': (g_etkinlikler, 'open event / PvE modes and galaxy gates you can run', ''),
    'cevre': (g_cevre, 'who is online: real players, your friends, your enemies, pilots on your map', ''),
    'klan': (g_klan, 'your clan: members, ranks, treasury, budget, diplomacy, battle stations (look before managing it)', ''),
    'defter': (g_defter, 'your written goals and reminders', ''),
    'anilar': (g_anilar, 'your memories (of one person if ad is given)', 'ad?'),
}


# ------------------------------------------------------------------------------------------------------------ kendini yönetme
def k_defter(y, b, arg):
    d = b.k.setdefault('defter', [])
    islem = str(arg.get('islem') or 'ekle')
    if islem == 'ekle':
        metin = ' '.join(str(arg.get('metin') or '').split())[:160]
        if not metin:
            return 'failed: metin is empty'
        acik = [x for x in d if not x.get('bitti')]
        if len(acik) >= DEFTER_EN_COK:
            return 'failed: you already have %d goals; finish or delete one first' % len(acik)
        d.append({'metin': metin, 't': y.now})
        del d[:-20]
        return 'ok: goal added'
    acik = [x for x in d if not x.get('bitti')]
    try:
        x = acik[int(arg.get('no')) - 1]
    except (TypeError, ValueError, IndexError):
        return 'failed: no such goal number'
    if islem == 'bitir':
        x['bitti'] = True
        ANI.ekle(b, b.ad, 'I reached my goal: %s' % x['metin'], 'hedef', 0.5, 2, y.now)
        return 'ok: goal done'
    if islem == 'sil':
        d.remove(x)
        return 'ok: goal deleted'
    return 'failed: islem must be ekle, bitir or sil'


def k_hatirlat(y, b, arg):
    try:
        dk = max(1, min(240, int(arg.get('dakika') or 0)))
    except (TypeError, ValueError):
        return 'failed: dakika must be a number'
    metin = ' '.join(str(arg.get('metin') or '').split())[:160]
    h = b.k.setdefault('hatirlatici', [])
    ayni = next((x for x in h if x['metin'] == (metin or 'check how things are going')), None)
    if ayni is not None:                               # aynı hatırlatıcı: yalnız vakti güncellenir
        ayni['vade'] = y.now + dk * 60
        return 'ok: reminder moved to %d min from now' % dk
    if len(h) >= 5:
        return 'failed: you already have 5 reminders'
    h.append({'vade': y.now + dk * 60, 'metin': metin or 'check how things are going'})
    return 'ok: you will think again in %d min' % dk


def k_not(y, b, arg):
    metin = ' '.join(str(arg.get('metin') or '').split())[:200]
    if not metin:
        return 'failed: metin is empty'
    ANI.ekle(b, str(arg.get('ad') or b.ad), metin, 'not', 0.0, 2, y.now, birlestir=False)
    return 'ok: noted'


KENDI = {
    'defter': (k_defter, 'manage your long-term goals: islem ekle (metin), bitir (no) or sil (no)', 'islem, metin?, no?'),
    'hatirlat': (k_hatirlat, 'wake yourself up later to think again: in dakika minutes, about metin', 'dakika, metin'),
    'not_al': (k_not, 'write a private note into your memory (about ad, optional)', 'metin, ad?'),
}

# eylem araçları: araclar.py'deki ad -> (İngilizce açıklama, argümanlar); izinler araclar.cagir'da
EYLEM = {
    'npc_avla': ('go farm aliens (on harita if given, one of the maps from haritalar)', 'harita?'),
    'gorev_yap': ('continue your active quest', ''),
    'gorev_sec': ('take a specific quest from gorevler (name or #number)', 'gorev'),
    'pvp_avla': ('go hunt enemy-company players', ''),
    'esya_al': ('buy a specific upgrade from magaza (by its name)', 'esya'),
    'biriktir': ('save money for one upgrade from magaza (shopping then buys only that); empty esya clears it', 'esya'),
    'alisveris_yap': ('buy the best upgrade you can afford', ''),
    'kargo_sat': ('fly to a station and sell your cargo ore', ''),
    'mod_gir': ('enter an open mode from etkinlikler (by name)', 'mod'),
    'kapi_kos': ('run your ready galaxy gate', ''),
    'dinlen': ('go back to base and take a break', ''),
    'oturum': ('decide to stay online dakika more minutes (5-180)', 'dakika'),
    'cevrimdisi_ol': ('log off now', ''),
    'takip_et': ('fly to the map where player ad is', 'ad'),
    'yardima_git': ('go help player ad (on harita)', 'ad, harita?'),
    'duello': ('go fight player ad on harita', 'ad, harita'),
    'grup_davet': ('invite player ad to your group', 'ad'),
    'gruptan_ayril': ('leave your group', ''),
    'arkadas_ekle': ('send a friend request to ad', 'ad'),
    'klana_basvur': ('apply to a clan (name or tag)', 'klan'),
    'klan_aciklama': ('leader: rewrite your clan description (who you are, rules, recruiting)', 'metin'),
    'klan_duyuru': ('post clan news', 'metin'),
    'klan_postasi': ('send a mail to all clan members', 'konu, metin'),
    'klan_rutbe': ('create (ekle), delete (sil) or set the rights (haklar) of a clan rank', 'islem, rutbe, haklar?'),
    'uye_rutbe': ('give a member a rank (empty rutbe removes it)', 'ad, rutbe'),
    'uyeyi_cikar': ('kick a member from the clan', 'ad'),
    'liderligi_devret': ('hand the clan leadership to a member', 'ad'),
    'klan_vergi': ('set the clan tax, 0-5 percent', 'oran'),
    'klan_butce': ('leader: split the treasury in percent: station, payouts, war (sum at most 90)', 'ksi, odeme, savas'),
    'klan_odeme': ('pay a member from the treasury', 'ad, miktar'),
    'klan_istasyon': ('target a free asteroid for your clan battle station (its name)', 'istasyon'),
    'klan_diplomasi': ('offer alliance (ittifak), non-aggression (saldirmazlik), war (savas) or peace (baris) to a clan', 'klan, tur, metin?'),
    'diplomasi_yanit': ('accept (kabul true) or refuse a diplomacy offer from a clan', 'klan, kabul'),
    'fisilda': ('send a private chat message to ad', 'ad, metin'),
    'sohbet_yaz': ('write in a chat channel (kanal: global, firma, klan or grup)', 'kanal, metin'),
    'posta_gonder': ('send an in-game mail to ad', 'ad, konu, metin'),
}
ADLAR = list(GOZLEM) + [k for k in KENDI if k not in GOZLEM] + list(EYLEM) + ['bitir']


def katalog(y):
    """Modelin araç listesi (paketin izni kapalı olanlar hariç)."""
    # durum her düşünmenin başında zaten verilir (Right now): listede yok, model boşuna adım harcamasın
    out = ['Look (free, use before deciding):'] + ['- %s(%s): %s' % (k, a, d) for k, (f, d, a) in GOZLEM.items() if k != 'durum']
    out.append('Plan yourself:')
    out += ['- %s(%s): %s' % ('defter' if k == 'defter' else k, a, d) for k, (f, d, a) in KENDI.items()]
    out.append('Act:')
    for k, (d, a) in EYLEM.items():
        izin = AR.ARACLAR[k]['izin']
        if izin and not y.izin(izin):
            continue
        out.append('- %s(%s): %s' % (k, a, d))
    out.append('- bitir(): you are done thinking for now')
    return '\n'.join(out)


def calistir(br, y, b, arac, arg):
    """Bir adımı yürüt (y.lock altında) -> modele dönen sonuç metni."""
    arg = arg if isinstance(arg, dict) else {}
    if arac == 'defter' and arg.get('islem') in ('ekle', 'bitir', 'sil'):
        return k_defter(y, b, arg)
    if arac in GOZLEM:
        return GOZLEM[arac][0](y, b, arg)
    if arac in KENDI:
        return KENDI[arac][0](y, b, arg)
    if arac not in EYLEM:
        return 'failed: unknown tool %s' % arac
    if arac in ('fisilda', 'sohbet_yaz'):
        # art arda yazmaz: aynı kişiye yanıtını beklemeden 2 dk'da bir, aynı kanala dakikada bir (sohbet denemesi 2026-10-30: bot
        # oyuncuya 6 sn arayla iki kez "geliyorum" fısıldadı; bir adımda iki araç ya da yakın iki uyanma)
        hedef = ('fisilti', str(arg.get('ad') or '').lower()) if arac == 'fisilda' else ('kanal', str(arg.get('kanal') or 'firma'))
        son = b.__dict__.setdefault('_ajan_yazdi', {})
        t = son.get(hedef)
        if t is not None and y.now - t < (120 if arac == 'fisilda' else 60) and not (arac == 'fisilda' and any(
                x[0] > t and str(x[1]).lower() == hedef[1] and x[2] == 'fisilti:' + b.ad for x in y.gecmis[-40:])):
            return 'failed: you just wrote there; wait for an answer before writing again'
    if arac in ('fisilda', 'sohbet_yaz', 'posta_gonder'):
        metin = br._metin(b, arg.get('metin')) if arac != 'posta_gonder' else ' '.join(str(arg.get('metin') or '').split())
        if not metin:
            return 'failed: the message was not sent (too long, stats or numbers, or repeats what was said)'
        arg = dict(arg, metin=metin)
        if arac == 'fisilda':
            br._konustu(b, arg.get('ad'), y.now)
        if arac != 'posta_gonder':
            b.__dict__.setdefault('_ajan_yazdi', {})[hedef] = y.now
    r = AR.cagir(y, b, arac, {k: v for k, v in arg.items() if v not in (None, '')} if arac != 'biriktir' else arg)
    return ('ok' if r.get('ok') else 'failed') + (': %s' % r['mesaj'] if r.get('mesaj') else '')


# ------------------------------------------------------------------------------------------------------------ döngü
# Maliyet (kullanıcı 2026-10-30: ajan saatte 1,2M token yaktı): bir adımda birden çok araç; döngü yalnız bir bakma aracı istenince
# sürer (çoğu düşünme 1-2 istek). Sistem istemi + araç listesi sabit önek, adımlar çok turlu konuşma: sağlayıcının önek önbelleğine
# girer (DeepSeek'te önbellekteki girdi 50 kat ucuz).
SISTEM = ("You are the mind of one pilot in a DarkOrbit-like space MMO: you decide what he does next, exactly like a real human "
          "player with his personality, mood and history would. You act only through tools. Reply with ONE JSON object per step: "
          "{\"dusunce\": a few words of private thought in English, \"araclar\": [up to 4 tool calls {\"arac\": name, \"arg\": "
          "{arguments}}]}. Look tools are free and their results come back in your next step; a step with only actions ends your "
          "thinking, so put everything you decided into that step (actions, goals, a reminder). Usually: one step to look (only if "
          "you need facts beyond what you are given), one step to act; if nothing should change, just bitir. Use names exactly as "
          "the tools list them; never invent maps, items or players. Play like a person, not an optimizer: keep at what you started "
          "unless there is a reason, follow your written goals, save up for things you want, rest when tired, avoid maps that kill "
          "you, help friends, settle scores. Write long-term decisions into defter and set a reminder (hatirlat) to check on "
          "something later. Chat messages are short (at most 12 words), in your own chat language and style, never stats; do not "
          "keep messaging or inviting the same person when he does not answer. Output only the JSON.")


def sistem(y):
    """Sabit önek: kurallar ve araç listesi (paketin izinleriyle; bütün botlarda aynı -> önbellekte)."""
    from . import yonetici_uyari as YU
    return SISTEM + YU.sistem_notu() + '\n\nTOOLS:\n' + katalog(y)


def sema():
    s = {'type': 'string'}
    cagri = {'type': 'object', 'properties': {
        'arac': {'type': 'string', 'enum': ADLAR},
        'arg': {'type': 'object', 'properties': {
            'harita': s, 'ad': s, 'esya': s, 'gorev': s, 'mod': s, 'klan': s, 'kanal': s, 'metin': s, 'konu': s, 'islem': s,
            'rutbe': s, 'haklar': s, 'tur': s, 'istasyon': s, 'kabul': {'type': 'boolean'}, 'oran': {'type': 'integer'},
            'miktar': {'type': 'integer'}, 'ksi': {'type': 'integer'}, 'odeme': {'type': 'integer'}, 'savas': {'type': 'integer'},
            'dakika': {'type': 'integer'}, 'no': {'type': 'integer'}}}},
        'required': ['arac', 'arg']}
    return {'type': 'object', 'properties': {
        'dusunce': {'type': 'string', 'maxLength': 160}, 'araclar': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': cagri}},
        'required': ['dusunce', 'araclar']}


def _cagrilar(r):
    """Modelin yanıtı -> [(araç, arg)] (eski tek araçlı biçim de)."""
    xs = r.get('araclar') if isinstance(r.get('araclar'), list) else [r] if r.get('arac') else []
    return [(str(x.get('arac') or 'bitir'), x.get('arg') if isinstance(x.get('arg'), dict) else {}) for x in xs[:4] if isinstance(x, dict)]


def _bakma(arac, arg):
    return arac in GOZLEM and not (arac == 'defter' and arg.get('islem') in ('ekle', 'bitir', 'sil'))


def dusun(br, b, sebep, en_cok=ADIM):
    """Bir düşünme anı: adım adım araç döngüsü (adımda en çok 4 araç). -> [(düşünce, araç, arg, sonuç)]."""
    from . import llm
    y = br.y
    with y.lock:
        sis = sistem(y)
        ilk = '%s\nYour chat style: %s.\n\nWHY YOU ARE THINKING NOW: %s\n\nRight now: %s\n%s\n\nYour step as JSON.' % (
            llm.persona(b, y), llm.tarz(b), sebep, g_durum(y, b, {}), g_defter(y, b, {}))
    mesaj = [{'role': 'user', 'content': ilk}]
    adimlar = []
    for i in range(max(1, en_cok)):
        r = br.sor(mesaj, sema(), en_cok=200, sicaklik=0.5, sistem=sis)
        dus = ' '.join(str(r.get('dusunce') or '').split())[:160]
        cagri = _cagrilar(r)
        sonuclar, bakti, bitti = [], False, not cagri
        for arac, arg in cagri:
            if arac == 'bitir':
                bitti = True
                break
            with y.lock:
                try:
                    sonuc = str(calistir(br, y, b, arac, arg))
                except Exception as e:                     # araç hatası modele söylenir, döngü sürer
                    sonuc = 'failed: %s' % e
            bakti = bakti or _bakma(arac, arg)
            adimlar.append((dus, arac, arg, sonuc[:900]))
            sonuclar.append('%s -> %s' % (arac, sonuc[:700]))
        if bitti and not sonuclar:
            adimlar.append((dus, 'bitir', {}, ''))
        if bitti or not bakti or i == en_cok - 1:
            break                                          # yalnız eylem: düşünme biter (ek istek yok)
        mesaj += [{'role': 'assistant', 'content': json.dumps(r, ensure_ascii=False)},
                  {'role': 'user', 'content': 'Results:\n%s\n\n%s' % ('\n'.join(sonuclar), 'This is your LAST step: act now or bitir.'
                                                                    if i == en_cok - 2 else 'Your next step as JSON.')}]
    with y.lock:
        iz = b.k.setdefault('ajan', [])
        iz.extend({'t': y.now, 'sebep': sebep[:120], 'dusunce': d, 'arac': a, 'arg': g, 'sonuc': s[:200]} for d, a, g, s in adimlar)
        del iz[:-20]
    return adimlar


def uyandirma_durumu(b):
    """uyandiranlar'ın tükettiği durum -> geri yükleyen işlev (iş kuyruğa giremezse ya da bayatlarsa hatırlatıcı, kargo/birikim
    uyarısı ve olaylar kaybolmasın)."""
    d = {k: b.__dict__[k] for k in ('_ajan_olay_t', '_kargo_uyandi', '_birikim_uyandi') if k in b.__dict__}
    h = b.k.get('hatirlatici')
    h = list(h) if h is not None else None

    def geri():
        for k in ('_ajan_olay_t', '_kargo_uyandi', '_birikim_uyandi'):
            if k in d:
                b.__dict__[k] = d[k]
            else:
                b.__dict__.pop(k, None)
        if h is not None:
            b.k['hatirlatici'] = h + [x for x in b.k.get('hatirlatici') or [] if x not in h]    # arada kurulan yenisi de kalsın
    return geri


def uyandiranlar(y, b, now, olaylar=True):
    """Botu şimdi düşündürecek sebep (olay, hatırlatıcı, biriktirmenin tamamlanması) ya da None. olaylar=False: oyuncudan uzak bot
    yalnız kendi kurduğu hatırlatıcıyla ve birikimiyle uyanır (ajan seyrek; olaylarını kurallı motor karşılar)."""
    son = b.__dict__.get('_ajan_olay_t', now)
    b._ajan_olay_t = now
    for o in reversed(b.olaylar[-8:]) if olaylar else ():
        if o['t'] > son and o['tur'] in UYANDIRAN:
            if o['tur'] == 'olum' and o.get('katil'):
                return 'you just got shot down by %s' % o['katil']
            return UYANDIRAN[o['tur']]
    h = b.k.get('hatirlatici') or []
    vakti = [x for x in h if x['vade'] <= now]
    if vakti:
        b.k['hatirlatici'] = [x for x in h if x['vade'] > now]
        return 'your reminder: %s' % vakti[0]['metin']
    if olaylar and b.kargo_dolu() >= 0.97 and not b.__dict__.get('_kargo_uyandi'):      # uzak botun kargosunu kurallı motor satar
        b._kargo_uyandi = True
        return 'your cargo is full'
    if b.kargo_dolu() < 0.5:
        b._kargo_uyandi = False
    hedef = b.k.get('birikim')
    if hedef:
        c = AR._esya(b, hedef)
        if c is not None and {'C': b.k['kredi'], 'U': b.k['uridyum']}[c[1]] >= c[2] and not b.__dict__.get('_birikim_uyandi'):
            b._birikim_uyandi = True
            return 'you now have enough money for %s, which you were saving for' % _kisa(hedef)
    return None
