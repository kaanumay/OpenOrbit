"""Bot klanlarının Klan Savaş İstasyonları (kullanıcı isteği 2026-10-31): botlar varken sahte rakip yok (cbs.botlu), asteroitler boş
açılır; bot klanlarının liderleri (ve kurma hakkı olan subaylar) gerçekten yarışır. En hızlı gelişen klan en iyi yeri kapar.

  hedef      en değerli boş asteroit (4-x, X-BL, X-5..7, X-3/4; kendi firmasının haritası öne), önde giden rakip çok öndeyse başkası
  modül      kasadan, bütçenin KSİ payıyla (klan_yonetim.harcanabilir) alınır; fiyatlar cbs.json bot_klan (uyarlama: oyunda
             modüller Assembly ile üretilir). Takım liderin tarzına göre: saldırgan lazer/roket, hırslı ve barışçı booster, temkinli
             onarım modülü
  yarış      asteroide 50 sn'de bir modül (cbs.json kurulum_sn); ilerleme a['yaris'] (pencerede "önde giden klan"). İlk 10/10 olan
             kurar (cbs.bot_kur); oyuncu önce kurarsa ya da başka klan kazanırsa modüller stoğa döner
  gelişme    kurulu istasyonda modüller seviye seviye (0-15) yükselir, yıkılan uydu bütçe yettikçe onarılır: her istasyon başka
  savunma    oyuncu vurunca lider çevrimiçi üyeleri istasyona yollar (klan_emir 'git'), duyuru ve toplu posta, saldırana kin
Klanın kaydında k['ksi'] = {hedef, plan, stok: [modül], son_*}; asteroidin kaydı ortak profilde (cbs.ortak)."""
import random, time

import cbs as CB
import harita as H
import klan as KL
from . import klan_yonetim as KY

VARSAYILAN = {'fiyat': {}, 'seviye_carpani': 0.35, 'onarim_orani': 0.4, 'yukseltme_sn': 3600, 'kurma_dk': [5, 30],
              'savunma_sn': 1800}                     # asıl değerler cbs.json bot_klan
SILAHLAR = ('module_ltm-lr', 'module_ltm-mr', 'module_ltm-hr', 'module_ram-la', 'module_ram-ma')
BOOSTER = ('module_honm-1', 'module_xpm-1', 'module_dmgm-1')


def ayar():
    return dict(VARSAYILAN, **(CB.D.get('bot_klan') or {}))


def acik():
    return CB.botlu()


def fiyat(loot, seviye=0):
    a = ayar()
    f = a['fiyat'].get(loot, 1000000)
    return int(f if seviye <= 0 else f * a['seviye_carpani'] * seviye)


def _kayit():
    """(ortak profil, asteroitler) ya da (None, None): ortak kayıt bir oturumda kurulmuş olmalı (cbs.Cbs.asts: embed)."""
    h = CB.ortak()
    d = (h.d.get('cbs') or {}) if h is not None else {}
    return (h, d['asteroitler']) if h is not None and d.get('ortak') and 'asteroitler' in d else (None, None)


def ksi(k):
    with KL.LOCK:
        s = k.setdefault('ksi', {})
        s.setdefault('stok', [])
        return s


def istasyonlari(k):
    """Klanın kurulu istasyonlarının adları."""
    h, asts = _kayit()
    return [CB.AST[int(aid)]['ad'] for aid, a in (asts or {}).items()
            if a.get('durum') == 'kurulu' and a.get('klan') == k['id'] and int(aid) in CB.AST]


def _benim(asts, k):
    return {int(aid): a for aid, a in asts.items() if a.get('klan') == k['id'] and a.get('durum') in ('kurma', 'kurulu')}


def ihtiyac(k):
    """Sıradaki KSİ hedefinin kalan bedeli: istasyonu yoksa eksik modüllerin fiyatı, varsa bir sonraki yükseltme."""
    s = k.get('ksi') or {}
    h, asts = _kayit()
    if asts is None:
        return 0
    benim = _benim(asts, k)
    if not benim:
        sahip = [m['loot'] for m in s.get('stok', [])]
        yaris = (asts.get(str(s.get('hedef'))) or {}).get('yaris', {}).get(str(k['id']), {}).get('moduller', [])
        sahip += [m['loot'] for m in yaris]
        eksik = list(s.get('plan') or [])
        for l in sahip:
            if l in eksik:
                eksik.remove(l)
        return sum(fiyat(l) for l in eksik)
    y = _yukseltilecek(next(iter(benim.values())), None)
    return fiyat(y['loot'], y['seviye'] + 1) if y else 0


def ozet(k):
    """Ajanın gözlemi: klanın istasyonları (modüller ve seviyeleri), yarışı, stoğu, sıradaki bedel ve boş asteroitler."""
    if not acik():
        return ''
    h, asts = _kayit()
    if asts is None:
        return ''
    satir = []
    for aid, a in _benim(asts, k).items():
        mods = [y.get('modul') for y in a['yuvalar'].values() if y.get('modul')]
        satir.append('Your battle station %s (%s): %s, deflector %s, modules %s.' % (
            CB.AST[aid]['ad'], H.name(CB.AST[aid]['harita']), 'building' if a['durum'] == 'kurma' else 'built',
            'on' if (a.get('deflector') or {}).get('acik') else 'off',
            ', '.join('%s L%d%s' % (CB.MODS[m['loot']]['kod'], m['seviye'] + 1, ' destroyed' if m['can'] <= 0 else '') for m in mods)))
    s = k.get('ksi') or {}
    if s.get('hedef'):
        a = asts.get(str(s['hedef'])) or {}
        biz = len(((a.get('yaris') or {}).get(str(k['id'])) or {}).get('moduller') or ())
        en = CB.yaris_lideri(a)
        satir.append('Building race at %s: you have %d/10 modules%s.' % (CB.AST[int(s['hedef'])]['ad'], biz,
                                                                       ', leader %s %d/10' % (en[0], en[1] * 10) if en and en[0] != k['ad'] else ''))
    if s.get('stok'):
        satir.append('Modules in clan stock: %s.' % ', '.join(sorted(CB.MODS[m['loot']]['kod'] for m in s['stok'])))
    satir.append('Next station cost: about %s credits (the station share of the budget pays it).' % '{:,}'.format(ihtiyac(k)))
    bos = sorted(((deger(aid, k), aid) for aid in CB.AST if (asts.get(str(aid)) or {}).get('durum', 'bos') == 'bos'), reverse=True)[:6]
    if bos:
        satir.append('Free asteroids (best first; klan_istasyon to target one): %s.' % ', '.join(
            '%s (%s)' % (CB.AST[aid]['ad'], H.name(CB.AST[aid]['harita'])) for _, aid in bos))
    return '\n'.join(satir)


def hedefle(k, ad, b):
    """Ajanın seçtiği asteroit (adıyla): boşsa hedef olur; önceki hedefteki modüller stoğa döner."""
    h, asts = _kayit()
    aid = next((i for i, a in CB.AST.items() if a['ad'].lower() == str(ad or '').strip().lower()), None)
    if asts is None or aid is None or (asts.get(str(aid)) or {}).get('durum', 'bos') != 'bos':
        return False
    s = ksi(k)
    eski = s.get('hedef')
    if eski and eski != aid:
        a = asts.get(str(eski)) or {}
        with h.lock:
            r = (a.get('yaris') or {}).pop(str(k['id']), None)
            a['surum'] = a.get('surum', 0) + 1
        if r:
            CB.yarisi_iade(k['id'], r.get('moduller'))
    s['hedef'] = aid
    s['plan'] = s.get('plan') or plan_kur(b)
    return True


# ------------------------------------------------------------------------------------------------------------ karar
def deger(aid, k):
    """Asteroidin klana değeri: 4-x en değerli (PvP bölgesi, her firmaya açık), sonra X-BL, X-5..7, X-3/4; kendi firmasının haritası
    öne, düşman firmanınki geri."""
    m = int(CB.AST[aid]['harita'])
    ad = H.name(m)
    on, _, son = ad.partition('-')
    v = 3.0 if on == '4' else 2.5 if son.upper() == 'BL' else 2.0 if son in ('5', '6', '7') else 1.2
    sahip = H.company(m)
    firma = int(k.get('firma') or 0) or int((k['uyeler'].get(k['lider']) or {}).get('firma') or 0)
    return v + (0.5 if sahip and sahip == firma else -0.6 if sahip else 0)


def plan_kur(b):
    """Takım (merkez + 8 uydu) liderin tarzıyla: saldırgan lazer/roket, hırslı ve barışçı booster, temkinli onarım."""
    sag = b.o('saldirganlik')
    uydu = []
    if b.r.random() < 0.35 + 0.45 * (1 - b.o('risk')):
        uydu.append('module_repm-1')
    for x in BOOSTER:
        if b.r.random() < 0.12 + 0.55 * b.o('hirs') * (1 - sag):
            uydu.append(x)
    agirlik = (2 + 3 * sag, 2 + sag, 1 + sag, 1 + 2 * (1 - b.o('risk')), 1.5)
    while len(uydu) < CB.SLOTS - 2:
        uydu.append(b.r.choices(SILAHLAR, agirlik)[0])
    b.r.shuffle(uydu)
    return ['module_hulm-1', 'module_defm-1'] + uydu


def _yeni_modul(loot):
    hp = CB.level_value(CB.MODS[loot]['can'], 0)
    return {'loot': loot, 'seviye': 0, 'can': hp, 'kalkan': int(hp * CB.D['kalkan_orani'])}


def hedef_sec(k, asts, now):
    """Yeni hedef: klanın istasyon sınırı dolmadıysa en değerli boş asteroit; önde giden rakip 6/10'u geçtiyse ve bizim yoksa o
    asteroit atlanır (yetişemez)."""
    s = ksi(k)
    sinir = 1 + (len(k['uyeler']) >= 20 and k['kasa'] > 40000000)
    if len(_benim(asts, k)) >= sinir:
        return None
    aday = []
    for aid in CB.AST:
        a = asts.get(str(aid)) or {}
        if a.get('durum', 'bos') != 'bos':
            continue
        biz = len(((a.get('yaris') or {}).get(str(k['id'])) or {}).get('moduller') or ())
        en = max([len(r.get('moduller') or ()) for c, r in (a.get('yaris') or {}).items() if int(c) != k['id']] + [0])
        oyuncu = len(a.get('yuvalar') or {})
        if max(en, oyuncu) >= 6 and biz < max(en, oyuncu):
            continue
        aday.append((deger(aid, k) - 0.12 * max(en, oyuncu) + random.uniform(0, 0.4), aid))
    if not aday:
        return None
    s['hedef'] = max(aday)[1]
    return s['hedef']


def _yukseltilecek(a, b):
    """Kurulu istasyonda yükseltilecek modül (en düşük seviyeli; saldırgan lider silahları, temkinli merkezi önce)."""
    adaylar = []
    for s, y in a.get('yuvalar', {}).items():
        m = y.get('modul')
        if not m or m['can'] <= 0 or m['seviye'] >= 15:
            continue
        md = CB.MODS[m['loot']]
        on = 0.0
        if b is not None:
            on = (0.6 * b.o('saldirganlik') if md.get('silah') else 0) + (0.6 * (1 - b.o('risk')) if md['merkez'] else 0)
        adaylar.append((m['seviye'] - on, int(s), m))
    return min(adaylar, key=lambda x: x[:2])[2] if adaylar else None


def _ode(k, alan, bedel):
    if bedel <= 0 or KY.harcanabilir(k, alan) < bedel:
        return False
    with KL.LOCK:
        k['kasa'] -= bedel
        k['kasa_kaydi'].insert(0, {'balanceUserId': 0, 'credits': -bedel, 'insertDate': KL.stamp(), 'toName': '', 'fromName': '',
                                   'moneyType': 'cbs', 'reason': 'battle station'})
        del k['kasa_kaydi'][200:]
    KL.degisti(k)                                        # kasa üyelerin penceresinde ve klanlar.json'da
    return True


def stoga_al(k, d):
    """Yıkılan istasyonun ya da çıkarılan modüllerin (bekleyen '@klan:<kimlik>') klanın stoğuna geçmesi."""
    bekleyen = (d.get('bekleyen') or {}).pop('@klan:%d' % k['id'], None)
    if bekleyen:
        ksi(k)['stok'].extend(bekleyen.values())


def yaris_adimi(y, b, k, h, asts, now):
    """Hedef asteroitte bir adım: stokta sıradaki modül varsa takar (50 sn'de bir), yoksa bütçe yettikçe alır; 10/10 olunca kurar."""
    s = ksi(k)
    aid = s.get('hedef')
    if aid and str(aid) not in asts:
        with h.lock:
            asts.setdefault(str(aid), {'durum': 'bos', 'yuvalar': {}})
    a = asts.get(str(aid)) if aid else None
    if a is None or a.get('durum', 'bos') != 'bos':
        if a is not None and a.get('klan') == k['id']:
            return                                       # kazandık: kuruluyor ya da kurulu
        if aid:
            b.olay('ksi_kaybetti', now, istasyon=CB.AST[int(aid)]['ad'])
        s['hedef'] = None
        aid = hedef_sec(k, asts, now)
        if aid is None:
            return
        with h.lock:
            a = asts.setdefault(str(aid), {'durum': 'bos', 'yuvalar': {}})
        s['plan'] = plan_kur(b)
        KY.duyur(b, KY.kl_of(b), 'klan_duyuru_ksi_yaris', istasyon=CB.AST[aid]['ad'], harita=H.name(CB.AST[aid]['harita']))
        b.olay('ksi_hedef', now, istasyon=CB.AST[aid]['ad'])
    r = (a.get('yaris') or {}).get(str(k['id'])) or {'moduller': [], 't': 0}
    takili = [m['loot'] for m in r['moduller']]
    s['plan'] = s.get('plan') or plan_kur(b)
    eksik = list(s['plan'])
    for l in takili:
        if l in eksik:
            eksik.remove(l)
    if not eksik:
        dk = b.r.randint(*ayar()['kurma_dk'])
        if CB.bot_kur(int(aid), k, r['moduller'], dk, log=y.log):
            s['hedef'] = None
            b.olay('ksi_kuruyor', now, istasyon=CB.AST[int(aid)]['ad'])
        return
    if now - r.get('t', 0) < CB.D['kurulum_sn']:
        return
    loot = eksik[0]
    m = next((x for x in s['stok'] if x['loot'] == loot), None)
    if m is None:
        if not _ode(k, 'ksi', fiyat(loot)):
            return                                       # para birikiyor
        m = _yeni_modul(loot)
    else:
        s['stok'].remove(m)
        if m['can'] <= 0:                                # yıkılıp dönmüş modül: önce onarılır
            if not _ode(k, 'ksi', int(fiyat(loot) * ayar()['onarim_orani'])):
                s['stok'].append(m)
                return
            m.update(_yeni_modul(loot), seviye=m['seviye'])
            m['can'] = CB.level_value(CB.MODS[loot]['can'], m['seviye'])
            m['kalkan'] = int(m['can'] * CB.D['kalkan_orani'])
            m.pop('ksi', None)                           # taban değerler: panelin KSİ can çarpanına cbs.hp_sync ölçekler
    with h.lock:
        r = a.setdefault('yaris', {}).setdefault(str(k['id']), {'moduller': [], 't': 0})
        r['moduller'].append(m)
        r['t'] = now
        a['surum'] = a.get('surum', 0) + 1
        h.d['cbs']['bot_klanlari'] = True
        h.dirty = True


def gelistir(y, b, k, h, asts, now):
    """Kurulu istasyonlar: yıkılan uydu onarılır, sonra bir modül bir seviye yükselir (yükseltme_sn'de bir)."""
    s = ksi(k)
    for aid, a in _benim(asts, k).items():
        if a.get('durum') != 'kurulu' or now - a.get('saldiri', 0) < 600:
            continue
        for y_ in a['yuvalar'].values():
            m = y_.get('modul')
            if m and m['can'] <= 0 and _ode(k, 'ksi', int(fiyat(m['loot']) * ayar()['onarim_orani'])):
                with h.lock:
                    m['can'] = CB.level_value(CB.MODS[m['loot']]['can'], m['seviye'])
                    m['kalkan'] = int(m['can'] * CB.D['kalkan_orani'])
                    m.pop('ksi', None)
                    a['surum'] = a.get('surum', 0) + 1
                    h.dirty = True
                return
        if now - s.get('son_yukseltme', 0) < ayar()['yukseltme_sn']:
            continue
        m = _yukseltilecek(a, b)
        if m is None or not _ode(k, 'ksi', fiyat(m['loot'], m['seviye'] + 1)):
            continue
        with h.lock:
            oran = m['can'] / max(1, CB.hp_max(m))          # ölçekli canın oranı (panelin KSİ can çarpanı)
            m['seviye'] += 1
            m['can'] = int(CB.level_value(CB.MODS[m['loot']]['can'], m['seviye']) * min(1.0, oran))
            m['kalkan'] = int(CB.level_value(CB.MODS[m['loot']]['can'], m['seviye']) * CB.D['kalkan_orani'] * min(1.0, oran))
            m.pop('ksi', None)
            a['surum'] = a.get('surum', 0) + 1
            h.dirty = True
        s['son_yukseltme'] = now
        b.olay('ksi_yukseltti', now, modul=m['loot'], seviye=m['seviye'])
        return


SAVUNMA_ILK = 2                  # saldırı başlar başlamaz yollanan üye sayısı
SAVUNMA_DALGA = 1                # sonraki her dalgadaki üye sayısı
SAVUNMA_ARA_SN = 75.0            # dalgalar arası (sn): üsse yavaş yavaş akarlar, sürü olmaz
SAVUNMA_SON_SN = 90              # saldırı bundan eski ise bitmiş sayılır, sıradakiler yollanmaz


def savunma_kota(saldiranlar):
    """Bir saldırıda yollanacak en çok üye: saldıran sayısıyla büyür (tek oyuncuya 5, her ek saldırana 3 daha; en çok 12)."""
    return min(12, 5 + 3 * max(0, saldiranlar - 1))


def _dalga(y, b, k, st, harita, n, now):
    """Sıradaki üyelerden en çok n tanesini istasyonun haritasına yollar (klan_emir 'git') -> yollanan sayısı."""
    from . import klan_emir as KE
    giden = 0
    while st['sirada'] and giden < n and st['yollanan'] < st['kota']:
        ad = st['sirada'].pop(0)
        o = y.ada.get(ad.lower())
        if o is None or not (o.cevrimici and o.olu_bitis <= now and o.k.get('klan') == k['id']):
            continue
        if KE.uyar_mi(o, b.ad, True, now) and KE.uygula(y, o, {'tur': 'git', 'harita': harita}, b.ad, None, now)[0] == 'geliyorum':
            giden += 1
            st['yollanan'] += 1
    return giden


def savun(y, b, k, asts, now):
    """İstasyona oyuncu saldırıyor: haber ve toplu posta (savunma_sn'de bir), lider saldırana kin duyar. Çevrimiçi üyeler hepsi birden
    değil, kademeli yollanır (klan_emir 'git'): ilk SAVUNMA_ILK hemen, kalanı SAVUNMA_ARA_SN'de bir SAVUNMA_DALGA; toplam
    savunma_kota(saldıran sayısı). Saldırı SAVUNMA_SON_SN'den uzun süredir yoksa sıra bırakılır. Bekleyen sıra klanın kaydında
    (k['ksi']['savunma'], klanlar.json): sunucu yeniden başlasa da süren saldırıda kalanlar yollanır."""
    bek = ksi(k).setdefault('savunma', {})
    for aid, a in _benim(asts, k).items():
        suruyor = now - a.get('son_oyuncu', 0) <= SAVUNMA_SON_SN
        st = bek.get(str(aid))
        if st is not None:
            if not suruyor:
                bek.pop(str(aid), None)                      # saldırı bitti: sıradakiler yollanmaz
                continue
            if a.get('son_saldiran') and a['son_saldiran'] not in st['saldiranlar']:
                st['saldiranlar'].append(a['son_saldiran'])
                st['kota'] = max(st['kota'], savunma_kota(len(st['saldiranlar'])))
            if now >= st['sonraki'] and st['sirada']:
                st['sonraki'] = now + SAVUNMA_ARA_SN
                _dalga(y, b, k, st, st['harita'], SAVUNMA_DALGA, now)
            continue
        if not suruyor or now - ksi(k).get('son_savunma', 0) < ayar()['savunma_sn']:
            continue
        ksi(k)['son_savunma'] = now
        ist, harita = CB.AST[aid]['ad'], H.name(CB.AST[aid]['harita'])
        kim = a.get('son_saldiran') or ''
        if kim:
            b.hafiza.olay(kim, 'hakaret', now, kat=1.0)
        kl = KY.kl_of(b)
        KY.duyur(b, kl, 'klan_duyuru_ksi_saldiri', istasyon=ist, harita=harita)
        if KL.hak(b.profil, 'roundmail'):
            KY.toplu_posta(b, kl, 'klan_posta_ksi', istasyon=ist, harita=harita)
        uyeler = [o for o in y.botlar if o.k.get('klan') == k['id'] and o.cevrimici and o.olu_bitis <= now]
        random.shuffle(uyeler)
        st = bek[str(aid)] = dict(harita=harita, sirada=[o.ad for o in uyeler], yollanan=0, kota=savunma_kota(1),
                                  saldiranlar=[kim] if kim else [], sonraki=now + SAVUNMA_ARA_SN)
        giden = _dalga(y, b, k, st, harita, SAVUNMA_ILK, now)
        y.log('   botlar: [%s] %s istasyonu saldırı altında (%s), %d üye savunmaya (kalan %d kademeli)'
              % (k['etiket'], ist, kim or '?', giden, len(st['sirada'])))
        b.olay('ksi_savunma', now, istasyon=ist, saldiran=kim)
        return


def durumu_duyur(b, k, asts, now):
    """Kuruldu / yıkıldı haberleri (önceki bakıştan bu yana değişenler)."""
    s = ksi(k)
    simdi = {str(aid): a.get('durum') for aid, a in _benim(asts, k).items()}
    once = s.get('gordu') or {}
    kl = None
    for aid, d in simdi.items():
        if d == 'kurulu' and once.get(aid) != 'kurulu':
            kl = kl or KY.kl_of(b)
            KY.duyur(b, kl, 'klan_duyuru_ksi_kuruldu', istasyon=CB.AST[int(aid)]['ad'], harita=H.name(CB.AST[int(aid)]['harita']))
            b.olay('ksi_kuruldu', now, istasyon=CB.AST[int(aid)]['ad'])
    for aid, d in once.items():
        if d == 'kurulu' and aid not in simdi and int(aid) in CB.AST:
            kl = kl or KY.kl_of(b)
            KY.duyur(b, kl, 'klan_duyuru_ksi_yikildi', istasyon=CB.AST[int(aid)]['ad'], harita=H.name(CB.AST[int(aid)]['harita']))
            b.olay('ksi_yikildi', now, istasyon=CB.AST[int(aid)]['ad'])
    s['gordu'] = simdi


def temizle(y, h, asts):
    """Dağılmış klanların istasyonları yıkılır, yarışları ve bekleyen modülleri silinir."""
    d = h.d['cbs']
    for aid, a in list(asts.items()):
        if a.get('sahip') == 'bot' and a.get('klan') not in KL.KLANLAR and a.get('durum') in ('kurma', 'kurulu'):
            CB.bot_yik(int(aid), log=y.log)
        yr = a.get('yaris') or {}
        for cid in [c for c in yr if int(c) not in KL.KLANLAR]:
            with h.lock:
                yr.pop(cid, None)
                a['surum'] = a.get('surum', 0) + 1
    for o in [o for o in (d.get('bekleyen') or {}) if o.startswith('@klan:') and int(o[6:]) not in KL.KLANLAR]:
        d['bekleyen'].pop(o, None)


def yonet(y, b, k, kl, now):
    """Lider (ya da kurma hakkı olan subay) sosyal turunda: savunma, yarış adımı, gelişme, haberler."""
    if not acik() or not kl.hak('battle_station_build', k):
        return
    h, asts = _kayit()
    if h is None:
        return
    if KY.vakti(k, 'ksi_temizlik', now, 600):
        temizle(y, h, asts)
    stoga_al(k, h.d['cbs'])
    savun(y, b, k, asts, now)
    durumu_duyur(b, k, asts, now)
    yaris_adimi(y, b, k, h, asts, now)
    gelistir(y, b, k, h, asts, now)
