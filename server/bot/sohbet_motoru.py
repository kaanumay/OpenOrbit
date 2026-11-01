"""Yöneticinin sohbet makinesi (Yonetici bundan türer): botların yazdıkları, oyuncunun mesajlarına yanıtlar, yardım çağrıları,
olaylardan doğan sohbet ve kendiliğinden konuşma.

Satırlar insan yazma süresi kadar gecikir (konusma.yazma_suresi), global/firma kanalında dakikada en çok sohbet_dk satır. Oyuncunun
mesajları sohbet iş parçacığından gelen'e eklenir, yöneticinin tick'inde işlenir. Gelişmiş kipte önce LLM (llm.py) denenir;
yetişemezse ya da LLM yoksa konusma.py'nin kalıpları.
"""
import random, re, time, traceback

import harita as H
from . import ad_uslup as AU
from . import beyin as B
from . import katalog as K
from . import etkilesim as ET
from . import konusma as KN
from . import moderasyon as MOD
from . import yonetici_uyari as YU

OLAY_SN = 5.0
ALIM_KLAN_SN = 7200.0                   # aynı klanın alım ilanı arası (iki saat)
ALIM_GENEL_SN = 1500.0                  # herhangi bir klanın ilanı arası
SIKAYET_SN = 1800.0                     # lag/uridyum sızlanması arası (tüm sohbette)
TEKRAR_SN = 2700.0                      # aynı satır bu süre içinde ikinci kez yazılmaz
BOT_ARA_SN = 600.0                      # aynı botun kendiliğinden iki lafı arası en az
KABA_CARPAN = (0.0, 1.0, 1.6, 2.2)      # kaba_sohbet düzeyine göre hakarete karşılık verme olasılığı çarpanı
FIRMA = {1: 'MMO', 2: 'EIC', 3: 'VRU'}


def kullanici(b):
    """Botun sohbetteki gönderen bilgisi (sosyal.Sosyal.chat_user biçimi)."""
    p = b.profil
    tag = p.d['pilot'].get('clanTag', '') if p is not None else ''
    if b.__dict__.get('moderator'):
        # [CM] etiketiyle, "mod" rolünde: istemci yaması (panel/eklenti/Yamalar.cs ModeratorRengi) onu kendi rengiyle çizer; yamasız
        # istemcide beyaz (istemci yalnız admin'i renklendirir, o da etiketi gizleyip "Yönetici" yazar)
        return {'userId': b.ad, 'id': str(b.uid), 'globalId': str(b.uid), 'role': MOD.SOHBET_ROLU, 'clanTag': MOD.ETIKET,
                'factionId': str(b.firma), 'instanceId': '1'}
    return {'userId': b.ad, 'id': str(b.uid), 'globalId': str(b.uid), 'role': 'chatter', 'clanTag': tag, 'factionId': str(b.firma),
            'instanceId': '1'}


def kanal_yolu(b, kanal):
    if kanal == 'global':
        return '/room/global/yerel/'
    if kanal == 'firma':
        return '/room/faction/%d/' % b.firma
    if kanal == 'klan':
        return '/room/clan/%d/' % b.k['klan'] if b.k.get('klan') else None
    if kanal == 'grup':
        import grup as GR
        g = GR.grubu(b.uid)
        return '/room/group/grup_%d/' % g.id if g is not None else None
    return None


def kanal_adi(yol):
    return 'global' if yol.startswith('/room/global/') else 'firma' if yol.startswith('/room/faction/') else \
        'klan' if yol.startswith('/room/clan/') else 'grup' if yol.startswith('/room/group/') else None


class SohbetMotoru:
    def sohbet_hazirla(self):
        self.sohbet = None             # sohbet.Sohbet (toplum.kaydol)
        self.llm = None                # Gelişmiş kip: llm.Beyin
        self.giden = []                # [(an, bot, kanal, metin, alıcı, öncelik, ilk an)]: yazılmayı bekleyen satırlar
        self.gelen = []                # sohbetten gelenler (sohbet iş parçacığı ekler, tick işler)
        self.gecmis = []               # son sohbet satırları [(an, ad, kanal, metin, oda yolu)]: LLM bağlamı (oda yolu: hangi firmanın,
        #                                klanın, grubun kanalı; fısıltıda None)
        self.son_soz = 0.0
        self.eylemler = []             # [(an, bot, (araç, argümanlar))]: kararın eylemi, yanıt yazıldıktan sonra (etkilesim.uygula)
        self._satirlar = []            # son bir dakikadaki bot satırlarının anları (sohbet_dk)
        self._son_metin = []           # [(an, sadeleşmiş metin)]: son kendiliğinden satırlar (tekrar önleme)
        self._alim_son = {}            # klan anahtarı (None: hepsi) -> son alım ilanı anı
        self._sikayet_son = 0.0

    def konus(self, b, kanal, metin, alici=None, now=None, hemen=False, oncelik=False):
        """Bot yazacak: insan yazma süresi kadar sonra gider (fısıltı: alici). oncelik: oyuncuya yanıt; kanal sınırına takılmaz.
        Kuyruğa girerse satırın gideceği anı döndürür (konuşma zinciri bunun üstüne yanıt ekler), girmezse None."""
        if not metin or not self.izin('sohbet'):
            return None
        now = now or self.now
        if not oncelik and YU.etkin(b, 'sohbet', now) and b.r.random() < 0.75:
            return None                                  # yönetici sohbet uyarısı: yalnız yanıtlar, çoğu kez susar
        t = now + (0 if hemen else KN.yazma_suresi(metin, b))
        self.giden.append((t, b, kanal, metin, alici, oncelik, t))
        return t

    def bekleyen_metinler(self):
        return [x[3] for x in self.giden]

    def sohbet_tick(self, now):
        """Zamanı gelen satırlar gönderilir; gelen mesajlar ve olaylar sohbete dönüşür; ara sıra kendiliğinden sohbet."""
        if self.gelen:
            gelen, self.gelen = self.gelen, []
            for g in gelen:
                try:
                    self.sohbet_isle(g, now)
                except Exception:
                    self.log('   botlar: sohbet hatası\n' + traceback.format_exc())
        if now - self.son_soz >= OLAY_SN:
            self.son_soz = now
            self.olay_tick(now)
            self.kendiliginden(now)
            self.laf_at(now)
            self.ozel_baslat(now)
            self.grup_lafi(now)
            YU.gorus_tick(self, now)
            MOD.kurallari_hatirlat(self, now)
        if self.eylemler:
            vakti = [x for x in self.eylemler if x[0] <= now]
            self.eylemler = [x for x in self.eylemler if x[0] > now]
            from . import araclar as AR
            for _, b, (arac, arg) in vakti:
                if b.cevrimici:
                    AR.cagir(self, b, arac, arg)
        if self.giden:
            vakti = [x for x in self.giden if x[0] <= now]
            self.giden = [x for x in self.giden if x[0] > now]
            for x in vakti:                              # gonder bekleyeni yeniden ekleyebilir
                self.gonder(x, now)

    def gonder(self, x, now):
        t, b, kanal, metin, alici, oncelik, ilk = x
        if not b.cevrimici:
            return
        if kanal in ('global', 'firma'):
            if MOD.susturulu(self, b.ad, now) > 0:
                return                                   # moderatör susturdu
            self._satirlar = [s for s in self._satirlar if now - s < 60]
            if len(self._satirlar) >= self.ayar('sohbet_dk', 6) and not oncelik:
                if now - ilk < 60:                       # kanal sınırı: biraz bekler (sohbet sele dönmesin); çok bekleyen düşer
                    self.giden.append((now + b.r.uniform(6, 15), b, kanal, metin, alici, oncelik, ilk))
                return
            self._satirlar.append(now)
        self.gecmis.append((now, b.ad, kanal if not alici else 'fisilti:' + alici, metin, None if alici else kanal_yolu(b, kanal)))
        del self.gecmis[:-600]               # fısıltı bağlamı kalabalık sohbette hemen silinmesin (güçlü sağlayıcı saatlerce geriye bakar)
        b.olay('dedim', now, kanal=kanal, metin=metin, alici=alici)
        if self.sohbet is None:
            return
        if alici:
            self.sohbet.bot_fisildar(alici, metin, 'bot%d' % b.uid, kullanici(b))
            return
        yol = kanal_yolu(b, kanal)
        if yol:
            self.sohbet.broadcast(yol, metin, 'bot%d' % b.uid, kullanici(b))
        MOD.denetle(self, b.ad, metin, kanal, now)       # botlar da kurala uyar (kaba bot susturulabilir)

    def sohbet_gelen(self, yol, msg, kim):
        """Sohbet iş parçacığından: oyuncunun oda mesajı (işlenmesi tick'te)."""
        self.gelen.append(('oda', yol, msg, kim))
        self.gecmis.append((time.time(), kim.get('userId', '?'), kanal_adi(yol) or yol, msg, yol))

    def fisilti_gelen(self, ad, msg, kim):
        """Sohbet iş parçacığından: oyuncu bir bota fısıldadı -> alıcı çevrimiçi bot mu (değilse istemci "çevrimdışı" yazar)."""
        b = self.ada.get(str(ad).lower())
        if b is None or not b.cevrimici:
            return False
        self.gelen.append(('fisilti', b, msg, kim))
        self.gecmis.append((time.time(), kim.get('userId', '?'), 'fisilti:' + b.ad, msg))
        return True

    def sohbet_isle(self, g, now):
        if g[0] == 'oda':
            MOD.denetle(self, g[3].get('userId', ''), g[2], kanal_adi(g[1]), now, g[3].get('role') or 'chatter')
        from . import klan_emir as KE
        if g[0] == 'oda' and kanal_adi(g[1]) == 'klan' and KE.isle(self, 'klan', g[2], g[3], self.dinleyenler('klan', g[3]), now):
            return                                       # klan emri (odak, git, gel, savun, al, gemi, yapı, dur)
        if g[0] == 'fisilti' and KE.isle(self, 'fisilti', g[2], g[3], [g[1]], now):
            return
        if YU.isle(self, g, now):                        # yöneticinin uyarısı ya da selamı (bot/yonetici_uyari.py)
            return
        if self.llm is not None and self.llm.sohbet(self, g, now):
            return
        if g[0] == 'fisilti':
            self.kalip_fisilti(g[1], g[2], g[3], now)
        else:
            self.kalip_oda(g[1], g[2], g[3], now)

    def dinleyenler(self, kanal, kim):
        fac = int(kim.get('factionId') or 0)
        out = [b for b in self.botlar if b.cevrimici and b.olu_bitis <= self.now]
        if kanal == 'firma':
            out = [b for b in out if b.firma == fac]
        elif kanal == 'klan':
            out = [b for b in out if b.profil is not None and kim.get('clanTag') and b.profil.d['pilot'].get('clanTag') == kim['clanTag']]
        elif kanal == 'grup':
            import grup as GR
            import topluluk as TP
            k = TP.bul(ad=kim.get('userId'))
            g = GR.grubu(k.uid) if k is not None else None
            out = [b for b in out if g is not None and b.uid in g.uyeler]
        return out

    def kalip_oda(self, yol, msg, kim, now):
        kanal = kanal_adi(yol)
        ad = kim.get('userId', '')
        if kanal is None or ad.lower() in self.ada:
            return
        tur, harita = KN.niyet(msg)
        dinleyen = self.dinleyenler(kanal, kim)
        anilan = [b for b in dinleyen if AU.anildi_mi(b.ad, msg)]
        for b in anilan:
            b.hafiza.olay(ad, 'sohbet', now)
            if tur in ET.NIYETLER and tur != 'yardim':
                self.istek_yanitla(b, tur, ad, kim, harita, msg, kanal, now)
            elif tur == 'hakaret':
                b.hafiza.olay(ad, 'hakaret', now)
                if b.r.random() < b.o('saldirganlik') * KABA_CARPAN[self.kaba()]:
                    self.konus(b, kanal, KN.kalip(b, self.laf(b, 'cevap_hakaret'), ad=ad), now=now)
            elif tur == 'yardim':
                self.yardim_cagrisi(ad, kim, harita, [b], kanal, now)
            elif b.r.random() < 0.85:
                self.konus(b, kanal, KN.kalip(b, {'selam': 'cevap_selam', 'tesekkur': 'tesekkur'}.get(tur, 'cevap_soru'), ad=ad),
                           now=now)
        if anilan:
            return
        if tur == 'yardim' and harita:
            self.yardim_cagrisi(ad, kim, harita, dinleyen, kanal, now)
        elif tur in ('grup', 'klan', 'gorev', 'duello', 'ozel', 'kapi'):
            for b in self.acik_cagri(tur, ad, kim, harita, msg, dinleyen, now):
                self.istek_yanitla(b, tur, ad, kim, harita, msg, kanal, now)
        elif tur == 'takip' and kanal == 'grup':              # grup sohbetinde "follow me / come 2-4": grubun botları
            for b in dinleyen[:3]:
                self.istek_yanitla(b, tur, ad, kim, harita, msg, kanal, now)
        elif tur == 'selam':
            for b in [b for b in dinleyen if b.r.random() < 0.3 * b.o('sosyallik')][:2]:
                self.konus(b, kanal, KN.kalip(b, 'cevap_selam', ad=ad), now=now)
        elif tur == 'soru' and dinleyen:
            b = max(dinleyen, key=lambda b: b.o('konuskanlik') * b.r.random())
            if b.r.random() < 0.3 + 0.4 * b.o('yardimseverlik'):
                self.konus(b, kanal, KN.kalip(b, 'cevap_soru'), now=now)

    def yardim_cagrisi(self, ad, kim, harita, adaylar, kanal, now, en_cok=None, zorunlu=False, sessiz=False):
        """Yardım çağrısı: aynı firmadan, yardımsever, o haritaya girebilen ve gidebilen botlardan bazıları gelir -> gelenler.
        zorunlu: karar başkasında, olasılık atılmaz; sessiz: kalıp yanıt yazılmaz (Gelişmiş kipte yanıtı model söyler)."""
        if not self.izin('yardim'):
            return []
        fac = int(kim.get('factionId') or 0)
        ids = {v: k for k, v in H.NAMES.items()}
        m = ids.get(harita) if harita else None
        if m is None:
            # harita yazılmadı: oyuncunun haritası, ama yalnız gerçekten saldırı altındaysa (son 90 sn'de hasar aldı); yoksa
            # "help"in başka anlamı var ("help me with quest", şaka) ve kimse savaşa koşmaz (oyuncu bildirimi 2026-10-30)
            import topluluk as TP
            k = TP.bul(ad=ad)
            w = k.world if k is not None else None
            m = int(k.profil.d['konum'].get('mapId', 0)) if w is not None and now - getattr(w, 'last_hurt', 0) < 90 else None
        if m is None or int(m) not in K.HARITALAR:
            return []
        gelen = []
        for b in sorted(adaylar, key=lambda b: -b.o('yardimseverlik') * b.r.uniform(0.6, 1.4)):
            if len(gelen) >= (en_cok or self.ayar('yardim_en_cok', 3)):
                break
            if b.firma != fac or not K.girebilir(m, b.firma, b.seviye) or not K.yol(b.harita, m, b.firma, b.seviye):
                continue
            p = 0.15 + 0.6 * b.o('yardimseverlik') + 0.5 * b.hafiza.iliski(ad, now) - 0.3 * b.ruh['yorgunluk']
            if b.hedef is not None and b.hedef.ad in ('gorev', 'grup'):
                p -= 0.2
            if zorunlu or b.r.random() < p:
                gelen.append(b)
                B.zorla(b, 'yardim', plan={'harita': int(m), 'ad': ad}, pay=1.2, sure=900, now=now)
                b.hafiza.olay(ad, 'yardim_ettim', now)
                if not zorunlu and not sessiz:
                    self.konus(b, kanal, KN.kalip(b, 'yardima_gidiyor', harita=H.name(m)), now=now)
        return gelen

    def acik_cagri(self, tur, ad, kim, harita, msg, dinleyen, now):
        """Kimseye hitap etmeyen istek ("grup olalım mı", "klan alan var mı"): yanıt verecek botlar. Grup: aynı firmadan sosyal
        botlar sırayla düşünür, kabul eden ilk biri (gerçek sohbette olduğu gibi bir kişi "inv" der). Klan: klanı olan, aynı
        firmadan en çok iki bot (lider önce)."""
        fac = int(kim.get('factionId') or 0)
        if tur == 'duello':                               # meydan okumayı başka firmadan biri kabul eder
            for b in sorted([b for b in dinleyen if b.firma != fac], key=lambda b: -b.o('saldirganlik') * b.r.uniform(0.5, 1.5))[:4]:
                k = ET.karar(self, b, 'duello', ad, kim, harita, msg, now)
                if k and k['kabul']:
                    b._istek_karari = k
                    return [b]
            return []
        aday = [b for b in dinleyen if not fac or b.firma == fac]
        if tur == 'kapi':                                 # kapı dolgusu: istenen sayıda (yoksa 3) kabul eden
            import re
            m = re.search(r'\b([1-7])\b', msg or '')
            n, out = int(m.group(1)) if m else 3, []
            for b in sorted(aday, key=lambda b: -(b.o('sosyallik') + b.o('hirs')) * b.r.uniform(0.5, 1.5))[:12]:
                k = ET.karar(self, b, 'kapi', ad, kim, harita, msg, now)
                if k and k['kabul']:
                    b._istek_karari = k
                    out.append(b)
                    if len(out) >= n:
                        break
            return out
        if tur in ('grup', 'gorev', 'ozel'):
            for b in sorted(aday, key=lambda b: -b.o('sosyallik') * b.r.uniform(0.5, 1.5))[:4]:
                k = ET.karar(self, b, tur, ad, kim, harita, msg, now)
                if k and k['kabul']:
                    b._istek_karari = k
                    return [b]
            return []
        import klan as KL
        from . import toplum
        klanli = [b for b in aday if KL.klani(toplum.profil(b)) is not None]
        return sorted(klanli, key=lambda b: (KL.klani(b.profil)['lider'] != b.ad.lower(), -b.o('konuskanlik')))[:2]

    def istek_yanitla(self, b, tur, ad, kim, harita, msg, kanal, now):
        """Normal kip: kararı (etkilesim) uygula, kalıpla söyle."""
        k = b.__dict__.pop('_istek_karari', None) or ET.karar(self, b, tur, ad, kim, harita, msg, now)
        if k is None:
            return
        metin = KN.kalip(b, k['kalip'][0], **k['kalip'][1]) if k.get('kalip') else None
        ET.uygula(self, b, k, gecikme=KN.yazma_suresi(metin or 'ok', b) + b.r.uniform(1, 3))
        if metin:
            if k.get('fisilti'):
                kanal = 'fisilti'                             # "bana PM at": yanıt özelden
            self.konus(b, kanal, metin, alici=ad if kanal == 'fisilti' else None, now=now)

    def kalip_fisilti(self, b, msg, kim, now):
        ad = kim.get('userId', '')
        tur, harita = KN.niyet(msg)
        tur = ET.teklif_cevabi(b, ad, msg, now) or tur       # "gruplaşalım mı?" -> "sure": grup isteği
        b.hafiza.olay(ad, 'sohbet', now)
        if tur in ET.NIYETLER and tur != 'yardim':
            self.istek_yanitla(b, tur, ad, kim, harita, msg, 'fisilti', now)
        elif tur == 'yardim':
            if self.yardim_cagrisi(ad, kim, harita, [b], 'firma', now):
                self.giden = [x for x in self.giden if not (x[1] is b and x[2] == 'firma')]
                self.konus(b, 'fisilti', KN.kalip(b, 'cevap_evet'), alici=ad, now=now)
            else:
                self.konus(b, 'fisilti', KN.kalip(b, 'cevap_hayir'), alici=ad, now=now)
        elif tur == 'hakaret':
            b.hafiza.olay(ad, 'hakaret', now)
            if b.r.random() < 0.6 * KABA_CARPAN[self.kaba()]:
                self.konus(b, 'fisilti', KN.kalip(b, self.laf(b, 'cevap_hakaret'), ad=ad), alici=ad, now=now)
        else:
            self.konus(b, 'fisilti', KN.kalip(b, {'selam': 'cevap_selam', 'tesekkur': 'tesekkur'}.get(tur, 'cevap_soru'), ad=ad),
                       alici=ad, now=now)

    def olay_tick(self, now):
        """Botların yeni olayları sohbete dönüşür (seviye, yeni gemi, PvP); Gelişmiş kipte LLM'in bağlamına da gider."""
        for b in self.botlar:
            if not b.cevrimici:
                continue
            t0 = getattr(b, '_olay_t', now)
            yeni = [o for o in b.olaylar if o['t'] > t0]
            b._olay_t = now
            for o in yeni:
                self.olay_sohbet(b, o, now)

    def olay_sohbet(self, b, o, now):
        if self.llm is not None and self.llm.olay(self, b, o, now):
            return
        kon = b.o('konuskanlik')
        tur = o['tur']
        if tur == 'tanik':
            if o.get('alt') == 'patron' and o.get('kim') and str(o['kim']).lower() != b.ad.lower():
                self.konus(b, 'firma', KN.kalip(b, 'tanik_patron', kim=o['kim']), now=now + b.r.uniform(2, 8))
            elif o.get('alt') == 'oyuncu_oldu' and o.get('ad'):
                self.konus(b, 'firma', KN.kalip(b, 'tanik_olum', ad=o['ad']), now=now + b.r.uniform(2, 10))
            return
        if tur == 'diplomasi' and (o.get('kabul') or not o.get('gelen')) and o.get('form') in (0, 1, 3) and b.r.random() < 0.4 + 0.5 * kon:
            durum = {0: 'baris', 1: 'ittifak', 3: 'savas_ilan'}[o['form']]
            if o['form'] == 0 and not o.get('gelen'):
                return                                   # barış isteği: kabul edilmeden ilan edilmez
            self.konus(b, 'global' if o['form'] == 3 else 'firma',
                       KN.kalip(b, durum, klan=o.get('klan', ''), etiket=o.get('etiket') or o.get('klan', '')), now=now + b.r.uniform(5, 30))
            return
        if tur == 'patron_oldurdum' and b.r.random() < 0.3 * kon:
            self.konus(b, 'firma', KN.kalip(b, 'patron_oldurdum'), now=now + b.r.uniform(2, 8))
            return
        if tur == 'seviye' and b.r.random() < 0.25 * kon:
            self.konus(b, 'firma', KN.kalip(b, 'seviye', seviye=o.get('seviye')), now=now)
        elif tur == 'yeni_gemi' and b.r.random() < 0.45 * kon:
            self.konus(b, 'global', KN.kalip(b, 'yeni_gemi', gemi=str(o.get('esya', '')).replace('ship_', '').title()), now=now)
        elif tur in ('olum', 'oyuncu_oldurdum') and now - self.__dict__.setdefault('_fisilti_son', {}).get(
                str(o.get('katil') or o.get('ad') or '').lower(), 0) < 60:
            pass                                         # aynı oyuncuya dakikada en çok bir fısıltı (art arda öldürmede yağmur olmasın)
        elif tur == 'olum' and o.get('katil') and str(o['katil']).lower() not in self.ada and b.r.random() < 0.2 + 0.5 * kon:
            self._fisilti_son[str(o['katil']).lower()] = now
            kaba = self.kaba()
            kizgin = kaba and b.ruh['ofke'] > 0.55 - 0.1 * kaba and b.o('saldirganlik') > 0.6 - 0.1 * kaba
            self.konus(b, 'fisilti', KN.kalip(b, 'oldum_kizgin' if kizgin else 'oldum'), alici=o['katil'], now=now)
        elif tur == 'oyuncu_oldurdum' and b.r.random() < 0.25 + 0.3 * kon:
            self.__dict__.setdefault('_fisilti_son', {})[str(o.get('ad') or '').lower()] = now
            kaba = self.kaba()
            self.konus(b, 'fisilti', KN.kalip(b, 'oldurdum') if kaba else 'gg', alici=o.get('ad'), now=now)
            if kaba >= 2 and o.get('ad') and b.r.random() < 0.25 * (kaba - 1) * b.o('saldirganlik'):
                self.konus(b, 'global', KN.kalip(b, 'laf_oldurdum', ad=o['ad'], harita=H.name(b.harita)), now=now + b.r.uniform(4, 15))
        elif tur == 'klan_kurdu' and self.alim_serbest(o.get('ad'), now):
            self.konus(b, 'global', KN.kalip(b, 'klan_alim', etiket=o.get('etiket'), klan=o.get('ad'), seviye=max(3, b.seviye - 4)),
                       now=now + b.r.uniform(20, 120))

    def cevrimici_insanlar(self):
        """Çevrimiçi insan oyuncular (topluluk.Kisi; paketin botları hariç)."""
        import topluluk as TP
        try:
            return [k for k in TP.hepsi().values() if k.oturum is not None and k.ad.lower() not in self.ada]
        except Exception:
            return []

    def ozel_baslat(self, now):
        """Arkadaş bot oyuncuya kendiliğinden fısıldar: girişinde selam, arada grup teklifi ya da hal hatır (oyuncu başına en çok
        12 dakikada bir; yalnız aynı firmadan, ona ilişkisi iyi botlar). Grup teklifine olumlu yanıt davete dönüşür (teklif_ver)."""
        if not self.izin('sohbet'):
            return
        gorulen = self.__dict__.setdefault('insan_ilk', {})
        son = self.__dict__.setdefault('insan_fisilti', {})
        for k in self.cevrimici_insanlar():
            a = k.ad.lower()
            ilk = gorulen.setdefault(a, now)
            if now - son.get(a, 0) < 720 or now - ilk < 20:
                continue
            fac = int(k.profil.d['pilot'].get('factionId', 0))
            dost = [b for b in self.botlar if b.cevrimici and b.olu_bitis <= now and b.firma == fac and b.hafiza.iliski(k.ad, now) >= 0.3]
            if not dost:
                continue
            b = max(dost, key=lambda b: b.hafiza.iliski(k.ad, now) * b.r.uniform(0.6, 1.4))
            if now - ilk < 300 and not son.get(a):
                amac = 'ozel_selam'                          # yeni girdi
            elif b.r.random() > 0.35 * (0.5 + b.o('sosyallik')):
                son[a] = now - 360                           # bu sefer yazmaz (yarım aralık sonra yine bakar)
                continue
            elif self.izin('grup') and b.hedef is not None and b.hedef.ad in ('kasilma', 'gorev') and b.r.random() < 0.6:
                amac = 'ozel_grup'
            else:
                amac = 'ozel_sohbet'
            son[a] = now
            if amac == 'ozel_grup':
                ET.teklif_ver(b, 'grup', k.ad, now)
            if self.llm is not None and self.llm.hazir and self.llm.ozel(self, b, k.ad, amac):
                continue
            self.konus(b, 'fisilti', KN.kalip(b, amac, ad=k.ad, harita=H.name(b.harita)), alici=k.ad, now=now + b.r.uniform(2, 10))

    def grup_lafi(self, now):
        """İnsanla grupta olan bot arada grup sohbetine yazar (nereye gidiyoruz, iyi kestik ...): 4-8 dakikada bir."""
        if not self.izin('sohbet'):
            return
        import grup as GR
        for k in self.cevrimici_insanlar():
            g = GR.grubu(k.uid)
            if g is None:
                continue
            uyeler = [b for b in self.botlar if b.uid in g.uyeler and b.cevrimici and b.olu_bitis <= now]
            if not uyeler or now < g.__dict__.get('_bot_laf', 0):
                continue
            g._bot_laf = now + random.uniform(240, 480)
            if not g.__dict__.get('_bot_laf_ilk'):
                g._bot_laf_ilk = True
                continue                                     # grup yeni kuruldu: ilk lafı hemen değil
            b = max(uyeler, key=lambda b: b.o('konuskanlik') * b.r.random())
            if self.llm is not None and self.llm.hazir and self.llm.grup_lafi(self, b, k.ad):
                continue
            self.konus(b, 'grup', KN.kalip(b, 'grup_laf'), now=now)

    def kaba(self):
        return int(self.ayar('kaba_sohbet', 1) or 0)

    def laf(self, b, durum):
        """Sert düzeyde saldırgan bot hakarete sert karşılık verir."""
        return 'laf_sert' if self.kaba() >= 2 and b.o('saldirganlik') > 0.5 and not b.__dict__.get('moderator') else durum

    def laf_at(self, now):
        """Sert ve çok sert düzeyde saldırgan botlar globalde başka firmaya ya da çevrimiçi düşman oyuncuya laf atar (kinliler önce)."""
        kaba = self.kaba()
        if kaba < 2 or random.random() > 0.05 * (kaba - 1):
            return
        acik = [b for b in self.botlar if b.cevrimici and b.olu_bitis <= now and b.o('saldirganlik') > 0.55
                and not b.__dict__.get('moderator')]
        if not acik:
            return
        b = max(acik, key=lambda b: b.o('saldirganlik') * b.r.random())
        dusman = [k for k in self.cevrimici_insanlar() if int(k.profil.d['pilot'].get('factionId', 0)) != b.firma]
        kin = [k for k in dusman if b.hafiza.iliski(k.ad, now) < -0.2]
        if (kin or dusman) and b.r.random() < (0.8 if kin else 0.3 * (kaba - 1)):
            k = b.r.choice(kin or dusman)
            self.konus(b, 'global', KN.kalip(b, 'laf_oyuncu', ad=k.ad, harita=H.name(b.harita)), now=now)
        else:
            self.konus(b, 'global', KN.kalip(b, 'laf_firma', firma=b.r.choice([f for f in ('MMO', 'EIC', 'VRU') if f != FIRMA[b.firma]])),
                       now=now)

    def alim_serbest(self, klan, now):
        """Klan alım ilanı yazılabilir mi (klan başına iki saatte, hepsi birlikte 25 dakikada en çok bir); yazılabilirse sayar."""
        if now - self._alim_son.get(None, -1e9) < ALIM_GENEL_SN or now - self._alim_son.get(klan, -1e9) < ALIM_KLAN_SN:
            return False
        self._alim_son[None] = self._alim_son[klan] = now
        return True

    def yeni_metin(self, b, durum, now, **f):
        """Durumun kalıbından, son 45 dakikada yazılmamış bir satır (4 denemede yoksa None)."""
        self._son_metin = [x for x in self._son_metin if now - x[0] < TEKRAR_SN]
        for _ in range(4):
            m = KN.kalip(b, durum, **f)
            if m and re.sub(r'\W+', '', m.lower()) not in (x[1] for x in self._son_metin):
                return m
        return None

    def yazdi(self, b, metin, now):
        self._son_metin.append((now, re.sub(r'\W+', '', metin.lower())))
        b._soz_son = now

    def durum_lafi(self, b, now):
        """Botun gerçekten yaptığı ya da az önce yaptığı bir şeyden (kapı bitti, alışveriş, ölüm, görev, dolu kargo, kasma) bir satır
        -> (durum, alanlar) ya da None. Seviye ve yeni gemi zaten olay_sohbet'te yazılır; aynı olay iki kez anlatılmaz."""
        anlatilan = b.__dict__.setdefault('_anlatilan', set())
        adaylar = []
        for o in b.olaylar[-12:]:
            if now - o['t'] > 900 or (o['tur'], o['t']) in anlatilan:
                continue
            t = o['tur']
            if t == 'kapi_tamam':
                adaylar.append(('durum_kapi', dict(kapi=o['kapi']), o))
            elif t == 'alim' and not str(o.get('esya', '')).startswith('ship_'):
                esya = re.sub(r'^(drone|equipment|resource)_', '', str(o.get('esya', ''))).replace('_', ' ')
                adaylar.append(('durum_alim', dict(esya=esya), o))
            elif t == 'olum' and o.get('neden') == 'npc':
                adaylar.append(('durum_olum', dict(harita=o.get('harita', H.name(b.harita))), o))
            elif t == 'gorev_bitti' and o.get('ad'):
                adaylar.append(('durum_gorev', dict(ad=o['ad']), o))
            elif t == 'kacti':
                adaylar.append(('durum_kacti', dict(harita=o.get('harita', H.name(b.harita))), o))
        try:
            if b.kargo_dolu() > 0.85:
                adaylar.append(('durum_kargo', dict(yuzde=int(b.kargo_dolu() * 100)), None))
        except Exception:
            pass
        if b.hedef is not None and b.hedef.ad == 'kasilma':
            adaylar.append(('durum_kasma', dict(harita=H.name(b.harita)), None))
        npc = b.k['istat'].get('npc', 0)
        if npc >= 50:
            adaylar.append(('durum_istat', dict(npc=npc, olum=b.k['istat'].get('olum', 0)), None))
        if not adaylar:
            return None
        d, f, o = b.r.choice(adaylar)
        if o is not None:
            anlatilan.add((o['tur'], o['t']))
            if len(anlatilan) > 60:
                anlatilan.clear()
        f.setdefault('harita', H.name(b.harita))
        f.setdefault('seviye', b.seviye)
        return d, f

    def diyalog_baslat(self, b, acik, kanal, now):
        """b bir soru/laf yazar; başka bir çevrimiçi bot (aynı dil, firma kanalında aynı firma) insan gecikmesiyle yanıtlar, bazen
        b de karşılık verir (en çok 3 satır). Yanıt gelmeyebilir; her satırın gideceği an bir öncekinin üstüne eklenir."""
        sohbet = KN.diyalog(b)
        if not sohbet:
            return False
        al = lambda x, tur: KN.diyalog_satiri(x, tur, harita=H.name(x.harita), seviye=x.seviye)
        m = al(b, sohbet[0])
        if not m or re.sub(r'\W+', '', m.lower()) in (x[1] for x in self._son_metin):
            return False
        t = self.konus(b, kanal, m, now=now)
        if t is None:
            return False
        self.yazdi(b, m, now)
        adaylar = [c for c in acik if c is not b and KN.dil(c) == KN.dil(b) and (kanal == 'global' or c.firma == b.firma)]
        if not adaylar:
            return True
        c = max(adaylar, key=lambda x: x.o('sosyallik') * x.r.random())
        if b.r.random() > 0.3 + 0.55 * c.o('sosyallik'):
            return True                                  # kimse yanıtlamadı
        for i, tur in enumerate(sohbet[1:]):
            kim = c if i % 2 == 0 else b
            m = next((x for x in (al(kim, tur) for _ in range(3)) if x and re.sub(r'\W+', '', x.lower()) not in
                      (y[1] for y in self._son_metin)), None)
            if not m:
                break
            t = self.konus(kim, kanal, m, now=t + kim.r.uniform(5, 22))
            if t is None:
                break
            self._son_metin.append((now, re.sub(r'\W+', '', m.lower())))
        return True

    def kendiliginden(self, now):
        """Ara sıra bir bot kendiliğinden yazar: yaptığı şeyden satır, kısa konuşma, grup arama, ticaret, genel laf, nadiren klan alım
        ilanı ve sızlanma. Kanal sınırı içinde; aynı satır, aynı bot ve aynı klanın ilanı sık tekrarlanmaz."""
        if self.llm is not None and self.llm.hazir:
            return                                   # Gelişmiş kipte kendiliğinden sohbeti model yapar (llm.bot_sohbet)
        acik = [b for b in self.botlar if b.cevrimici and b.olu_bitis <= now]
        if not acik or random.random() > 0.065 * min(1.0, len(acik) / 10.0):
            return
        musait = [b for b in acik if now - b.__dict__.get('_soz_son', -1e9) >= BOT_ARA_SN]
        if not musait:
            return
        b = max(musait, key=lambda b: b.o('konuskanlik') * b.r.random())
        k = b.r.random()
        if b.k.get('klan') and b.arketip == 'lider' and k < 0.3:
            import klan as KL
            c = KL.KLANLAR.get(b.k['klan'])
            if c is not None and c['lider'] == b.ad.lower() and self.alim_serbest(b.k['klan'], now):
                m = self.yeni_metin(b, 'klan_alim', now, etiket=c['etiket'], klan=c['ad'], seviye=max(3, b.seviye - 4))
                if m and self.konus(b, 'global', m, now=now) is not None:
                    self.yazdi(b, m, now)
                    return
        if b.arketip == 'tuccar' and k < 0.4:
            m, kanal = self.yeni_metin(b, 'ticaret', now, esya='LF-3'), 'global'
        elif b.o('sosyallik') > 0.6 and k < 0.35:
            m, kanal = self.yeni_metin(b, 'grup_ara', now, harita=H.name(b.harita)), 'firma'
        else:
            kanal, r = b.r.choice(('global', 'firma')), b.r.random()
            m = None
            if r < 0.4:
                d = self.durum_lafi(b, now)
                m = self.yeni_metin(b, d[0], now, **d[1]) if d else None
            elif r < 0.75:
                if self.diyalog_baslat(b, acik, kanal, now):
                    return
            elif r < 0.8 and now - self._sikayet_son >= SIKAYET_SN:
                self._sikayet_son = now
                m = self.yeni_metin(b, 'sikayet', now)
            if m is None:
                m = self.yeni_metin(b, 'genel', now)
        if m and self.konus(b, kanal, m, now=now) is not None:
            self.yazdi(b, m, now)
