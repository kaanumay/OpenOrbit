"""Sosyal bölümün oturum düzeyi (yol haritası Aşama 10): sohbet (sohbet.py; sunucusu oyun sürecinde, game.py başlatır), posta,
notlar, rehber ve kara liste (posta.py), klan (klan.py; sunucudaki oyuncuların ortak klanları), yerel müzayede (muzayede.py), gemi
ışınlama (isinlama.py).

Oturum bağları: istekler (REQUESTS, handle), girişteki kayıtlı mesajların yerine profildekiler (login_replace: sohbet adresi,
okunmamış posta sayısı), zamanlı işler (tick: müzayede dönem sonları), ChatAuthenticateUserRequest (sohbete giriş ve odalar).
Pencere düğmesi bildirimi (UIButtonTriggerRequest) yalnız "açıldı" der (istemci kodu: UIMainCenterNewSystem.SendButtonTriggerRequest
açılış animasyonunun sonunda); sunucudan pencere açan bir komutun işleyicisi yok. Pencerenin açık/kapalı durumu, konumu ve boyutu
UIWindowUpdateRequest ile gelir (kapatınca maximized=false) ve profilde saklanır (profil.apply): kapatılan pencere sonraki girişte
açılmaz (canlı deneme 2026-10-17).
"""
import cok_oyunculu as CO
import grup as GR
import isinlama as IS
import klan as KL
import muzayede as MZ
import posta as PS

REQUESTS = PS.REQUESTS | KL.REQUESTS | MZ.REQUESTS | IS.REQUESTS | {'ChatAuthenticateUserRequest'}
CHAT_HOST = '127.0.0.1:%d'


class Sosyal:
    def __init__(self, profil, magaza, log=print, sohbet=None):
        self.p, self.log, self.m = profil, log, magaza
        self.sohbet = sohbet
        self.posta = PS.Posta(profil, log)
        self.klan = KL.Klan(profil, log)
        self.muzayede = MZ.Muzayede(profil, log)
        self.isinlama = IS.Isinlama(profil, log)
        for x in (self.posta, self.klan, self.muzayede, self.isinlama):
            x.m = magaza
        self.muzayede.posta = self.posta
        self.klan.on_change = self.clan_changed
        self.clan_rooms = self.klan.rooms()  # sohbette katıldığı klan odası (clan_changed)
        self.world = None
        self.send = None                   # oturumun gönderme işlevi (geri sayımla biten ışınlama)
        self.reload = None                 # gemi değişince haritayı yeniden yükletme (dunya.reload_ship)
        self.ep = None                     # sohbet uç kimliği (ChatAuthenticateUserRequest)
        self.chat_host = None              # arkadaş sunucusunun misafiri: sohbet sunucusunun adresi (host:port; game.giris_bagla)
        self.welcomed = False
        self.last_window = (None, 0.0)     # son pencere bildirimi (istemci açılışta iki kez gönderiyor)

    def attach(self, world):
        self.world = world
        self.isinlama.busy = None     # geri sayım eski dünyanın zamanlayıcısıydı: harita değişince ışınlama hep "meşgul" kalıyordu

    # -------------------------------------------------------- istekler
    def handle(self, name, f, now):
        if name == 'ChatAuthenticateUserRequest':
            if self.m:
                self.m.dil = f.get('language')          # istemcinin dili: ham ret metinleri (magaza.neden)
            self.chat_login(f.get('endpointId', ''), f.get('language'))
            return []
        if name in PS.REQUESTS:
            return self.posta.handle(name, f)
        if name in KL.REQUESTS:
            return self.klan.handle(name, f)
        if name in MZ.REQUESTS:
            return self.muzayede.handle(name, f, now)
        if name in IS.REQUESTS:
            return self.isinlama.warp(f, self.world, now, self.warp_done)
        return []

    def window(self, item, now=None):
        """UIButtonTriggerRequest: açılan pencereye göre yanıt (ışınlama penceresi). İstemci açılışta bildirimi iki kez gönderiyor,
        gerçek sunucu bir kez yanıtlıyor (kayıt); ikincisi yanıtsız (canlı deneme 2026-10-17: ret metni iki kez çıkıyordu)."""
        import time as _t
        now = _t.time() if now is None else now
        last, at = self.last_window
        self.last_window = (item, now)
        if item == last and now - at < 1.0:
            return []
        if item == 'ship_warp':
            return self.isinlama.window(self.world)
        return []

    def warp_done(self, msgs, changed):
        if self.send:
            self.send(msgs, 'gemi ışınlama')
        if changed and self.reload:
            self.reload()

    def tick(self, now):
        return self.muzayede.settle(now) + self.muzayede.oto(now)     # panelin otomatik teklifleri ve alarmları

    # -------------------------------------------------------- giriş
    def login_replace(self, name, f):
        """Giriş demetindeki kayıtlı mesajın yerine (yoksa None): sohbet adresi yerel sunucuya, okunmamış posta profilden."""
        if name == 'ChatParamCommand':
            port = self.sohbet.port if self.sohbet else 7771
            return [(name, {'moduleList': [dict(m, param1=(self.chat_host or CHAT_HOST % port) if m.get('param0') == 'chat_ip' else
                                                ('http://127.0.0.1/crossdomain.xml' if m.get('param0') == 'chat_cross_ip'
                                                 else m.get('param1', '')))
                                           for m in f.get('moduleList', [])]})]
        if name == 'UserMessageNewCommand':
            return [(name, {'userMessageInfoCommand': None, 'unreadCount': self.posta.unread()})]
        return None

    # -------------------------------------------------------- sohbet
    def chat_user(self):
        import yonetici_modu as YM
        pl = self.p.d['pilot']
        return {'userId': pl.get('userName', ''), 'id': str(self.p.user_id), 'globalId': str(self.p.user_id),
                'role': YM.sohbet_rolu(self.p),                      # yönetici modu: "admin" (istemcinin yönetici rengi)
                'clanTag': pl.get('clanTag', ''), 'factionId': str(pl.get('factionId', 0)), 'instanceId': '1'}

    def rooms(self):
        fac = self.p.d['pilot'].get('factionId', 0)
        g = GR.grubu(self.p.user_id)               # arkadaş sunucusunda grubun odası (istemci gruba girince sohbete yeniden bağlanır)
        return [('global', 'global', 'yerel'), ('faction', 'faction', str(fac))] + self.klan.rooms() + \
            ([GR.oda(g.id)] if g is not None else [])

    def chat_login(self, ep, lang):
        if not self.sohbet:
            self.log('   sohbet sunucusu yok')
            return False
        self.ep = ep
        ok = self.sohbet.authenticate(ep, self.chat_user(), self.rooms(), lang)
        if ok and not self.welcomed:                  # harita değişiminde istemci yeniden bağlanabilir: duyuru oturumda bir kez
            self.welcomed = True
            kip = 'tek' if not CO.acik() else 'arkadas' if CO.AYAR['misafir'] else 'coklu'    # coklu: çoklu istemci (bu bilgisayar)
            text = {'tek': '%s, yerel sunucuya hoş geldin. Burada sohbet, posta, klan ve müzayede tek oyunculudur.',
                    'arkadas': '%s, arkadaş sunucusuna hoş geldin. Sohbet, posta, grup, rehber, klanlar ve sıralamalar ortak; '
                               'müzayede her oyuncunun kendisinin.',
                    'coklu': '%s, yerel sunucuya hoş geldin. Bu bilgisayardaki öteki kayıtlarınla aynı evrendesin: sohbet, posta, grup, '
                             'rehber, klanlar ve sıralamalar ortak; müzayede her oyuncunun kendisinin.'}[kip] if lang == 'tr' else {
                    'tek': '%s, welcome to your local server. Chat, mail, clan and auction are single-player here.',
                    'arkadas': "%s, welcome to your friend's server. Chat, mail, groups, contacts, clans and rankings are shared; "
                               "auction is each player's own.",
                    'coklu': '%s, welcome to your local server. You share this universe with your other saves on this computer: chat, '
                             "mail, groups, contacts, clans and rankings are shared; auction is each player's own."}[kip]
            self.sohbet.duyuru(text % self.p.d['pilot'].get('userName', ''), kim=str(self.p.user_id))
        return ok

    def clan_changed(self):
        """Klana girdi, çıktı ya da etiket değişti: sohbetteki etiket ve klan odası (eski klanın odası bırakılır; yalnız katılınca
        ayrılan oyuncu klan sohbetini almaya devam ediyordu)."""
        if self.sohbet:
            kim = str(self.p.user_id)
            self.sohbet.update_user(kim, clanTag=self.p.d['pilot'].get('clanTag', ''))
            rooms = self.klan.rooms()
            for old in self.clan_rooms:
                if old not in rooms:
                    self.sohbet.oda_birak(kim, old[1], old[2])
            self.sohbet.update_rooms(rooms, kim)
            self.clan_rooms = rooms

    def duyuru(self, text, room='global'):
        return self.sohbet.duyuru(text, room, kim=str(self.p.user_id)) if self.sohbet else 0
