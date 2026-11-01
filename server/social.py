"""Sosyal bölümün oturum düzeyi (yol haritası Aşama 10): sohbet (chat.py; sunucusu oyun sürecinde, game.py başlatır), posta,
notlar, rehber ve kara liste (mail.py), klan (clan.py; sunucudaki oyuncuların ortak klanları), yerel müzayede (auction.py), gemi
ışınlama (ship_warp.py).

Oturum bağları: istekler (REQUESTS, handle), girişteki kayıtlı mesajların yerine profildekiler (login_replace: sohbet adresi,
okunmamış posta sayısı), zamanlı işler (tick: müzayede dönem sonları), ChatAuthenticateUserRequest (sohbete giriş ve odalar).
Pencere düğmesi bildirimi (UIButtonTriggerRequest) yalnız "açıldı" der (istemci kodu: UIMainCenterNewSystem.SendButtonTriggerRequest
açılış animasyonunun sonunda); sunucudan pencere açan bir komutun işleyicisi yok. Pencerenin açık/kapalı durumu, konumu ve boyutu
UIWindowUpdateRequest ile gelir (kapatınca maximized=false) ve profilde saklanır (profil.apply): kapatılan pencere sonraki girişte
açılmaz (canlı deneme 2026-10-17).
"""
import multiplayer as CO
import group as GR
import ship_warp as IS
import clan as KL
import auction as MZ
import mail as PS

REQUESTS = PS.REQUESTS | KL.REQUESTS | MZ.REQUESTS | IS.REQUESTS | {'ChatAuthenticateUserRequest'}
CHAT_HOST = '127.0.0.1:%d'


class Social:
    def __init__(self, profile, shop, log=print, chat=None):
        self.p, self.log, self.m = profile, log, shop
        self.chat = chat
        self.mailer = PS.Mail(profile, log)
        self.clan = KL.Clan(profile, log)
        self.auction = MZ.Auction(profile, log)
        self.warp = IS.Warp(profile, log)
        for x in (self.mailer, self.clan, self.auction, self.warp):
            x.m = shop
        self.auction.mailer = self.mailer
        self.clan.on_change = self.clan_changed
        self.clan_rooms = self.clan.rooms()  # sohbette katıldığı klan odası (clan_changed)
        self.world = None
        self.send = None                   # oturumun gönderme işlevi (geri sayımla biten ışınlama)
        self.reload = None                 # gemi değişince haritayı yeniden yükletme (dunya.reload_ship)
        self.ep = None                     # sohbet uç kimliği (ChatAuthenticateUserRequest)
        self.chat_host = None              # arkadaş sunucusunun misafiri: sohbet sunucusunun adresi (host:port; game.giris_bagla)
        self.welcomed = False
        self.last_window = (None, 0.0)     # son pencere bildirimi (istemci açılışta iki kez gönderiyor)

    def attach(self, world):
        self.world = world
        self.warp.busy = None     # geri sayım eski dünyanın zamanlayıcısıydı: harita değişince ışınlama hep "meşgul" kalıyordu

    # -------------------------------------------------------- istekler
    def handle(self, name, f, now):
        if name == 'ChatAuthenticateUserRequest':
            if self.m:
                self.m.lang = f.get('language')          # istemcinin dili: ham ret metinleri (magaza.neden)
            self.chat_login(f.get('endpointId', ''), f.get('language'))
            return []
        if name in PS.REQUESTS:
            return self.mailer.handle(name, f)
        if name in KL.REQUESTS:
            return self.clan.handle(name, f)
        if name in MZ.REQUESTS:
            return self.auction.handle(name, f, now)
        if name in IS.REQUESTS:
            return self.warp.warp(f, self.world, now, self.warp_done)
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
            return self.warp.window(self.world)
        return []

    def warp_done(self, msgs, changed):
        if self.send:
            self.send(msgs, 'gemi ışınlama')
        if changed and self.reload:
            self.reload()

    def tick(self, now):
        return self.auction.settle(now) + self.auction.auto(now)     # panelin otomatik teklifleri ve alarmları

    # -------------------------------------------------------- giriş
    def login_replace(self, name, f):
        """Giriş demetindeki kayıtlı mesajın yerine (yoksa None): sohbet adresi yerel sunucuya, okunmamış posta profilden."""
        if name == 'ChatParamCommand':
            port = self.chat.port if self.chat else 7771
            return [(name, {'moduleList': [dict(m, param1=(self.chat_host or CHAT_HOST % port) if m.get('param0') == 'chat_ip' else
                                                ('http://127.0.0.1/crossdomain.xml' if m.get('param0') == 'chat_cross_ip'
                                                 else m.get('param1', '')))
                                           for m in f.get('moduleList', [])]})]
        if name == 'UserMessageNewCommand':
            return [(name, {'userMessageInfoCommand': None, 'unreadCount': self.mailer.unread()})]
        return None

    # -------------------------------------------------------- sohbet
    def chat_user(self):
        import admin_mode as YM
        pl = self.p.d['pilot']
        return {'userId': pl.get('userName', ''), 'id': str(self.p.user_id), 'globalId': str(self.p.user_id),
                'role': YM.chat_role(self.p),                      # yönetici modu: "admin" (istemcinin yönetici rengi)
                'clanTag': pl.get('clanTag', ''), 'factionId': str(pl.get('factionId', 0)), 'instanceId': '1'}

    def rooms(self):
        fac = self.p.d['pilot'].get('factionId', 0)
        g = GR.group_of(self.p.user_id)               # arkadaş sunucusunda grubun odası (istemci gruba girince sohbete yeniden bağlanır)
        return [('global', 'global', 'yerel'), ('faction', 'faction', str(fac))] + self.clan.rooms() + \
            ([GR.room(g.id)] if g is not None else [])

    def chat_login(self, ep, lang):
        if not self.chat:
            self.log('   sohbet sunucusu yok')
            return False
        self.ep = ep
        ok = self.chat.authenticate(ep, self.chat_user(), self.rooms(), lang)
        if ok and not self.welcomed:                  # harita değişiminde istemci yeniden bağlanabilir: duyuru oturumda bir kez
            self.welcomed = True
            mode = 'tek' if not CO.is_open() else 'arkadas' if CO.SETTINGS['misafir'] else 'coklu'    # coklu: çoklu istemci (bu bilgisayar)
            text = {'tek': '%s, yerel sunucuya hoş geldin. Burada sohbet, posta, klan ve müzayede tek oyunculudur.',
                    'arkadas': '%s, arkadaş sunucusuna hoş geldin. Sohbet, posta, grup, rehber, klanlar ve sıralamalar ortak; '
                               'müzayede her oyuncunun kendisinin.',
                    'coklu': '%s, yerel sunucuya hoş geldin. Bu bilgisayardaki öteki kayıtlarınla aynı evrendesin: sohbet, posta, grup, '
                             'rehber, klanlar ve sıralamalar ortak; müzayede her oyuncunun kendisinin.'}[mode] if lang == 'tr' else {
                    'tek': '%s, welcome to your local server. Chat, mail, clan and auction are single-player here.',
                    'arkadas': "%s, welcome to your friend's server. Chat, mail, groups, contacts, clans and rankings are shared; "
                               "auction is each player's own.",
                    'coklu': '%s, welcome to your local server. You share this universe with your other saves on this computer: chat, '
                             "mail, groups, contacts, clans and rankings are shared; auction is each player's own."}[mode]
            self.chat.announcement(text % self.p.d['pilot'].get('userName', ''), who=str(self.p.user_id))
        return ok

    def clan_changed(self):
        """Klana girdi, çıktı ya da etiket değişti: sohbetteki etiket ve klan odası (eski klanın odası bırakılır; yalnız katılınca
        ayrılan oyuncu klan sohbetini almaya devam ediyordu)."""
        if self.chat:
            who = str(self.p.user_id)
            self.chat.update_user(who, clanTag=self.p.d['pilot'].get('clanTag', ''))
            rooms = self.clan.rooms()
            for old in self.clan_rooms:
                if old not in rooms:
                    self.chat.room_drop(who, old[1], old[2])
            self.chat.update_rooms(rooms, who)
            self.clan_rooms = rooms

    def announcement(self, text, room='global'):
        return self.chat.announcement(text, room, who=str(self.p.user_id)) if self.chat else 0
