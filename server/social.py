"""Session level of the social part (roadmap stage 10): chat (chat.py; its server runs in the game process, game.py starts it), mail,
notes, contact list and blacklist (mail.py), clan (clan.py; the clans shared by the players on the server), local auction (auction.py), ship
warp (ship_warp.py).

Session bindings: requests (REQUESTS, handle), the profile's messages in place of the saved ones at login (login_replace: chat address,
unread mail count), timed jobs (tick: auction period ends), ChatAuthenticateUserRequest (joining chat and the rooms).
The window button notification (UIButtonTriggerRequest) only says "opened" (client code: UIMainCenterNewSystem.SendButtonTriggerRequest
at the end of the opening animation); there is no handler for a command that opens a window from the server. The window's open/closed state, position and size
come with UIWindowUpdateRequest (maximized=false when closed) and are stored in the profile (profile.apply): a closed window is not
opened at the next login (live trial 2026-10-17).
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
        self.clan_rooms = self.clan.rooms()  # the clan room it joined in chat (clan_changed)
        self.world = None
        self.send = None                   # the session's send function (warp that ends with a countdown)
        self.reload = None                 # reloading the map when the ship changes (world.reload_ship)
        self.ep = None                     # chat endpoint id (ChatAuthenticateUserRequest)
        self.chat_host = None              # guest of a friend server: the chat server's address (host:port; game.bind_login)
        self.welcomed = False
        self.last_window = (None, 0.0)     # last window notification (the client sends it twice at startup)

    def attach(self, world):
        self.world = world
        self.warp.busy = None     # the countdown belonged to the old world's timer: after a map change the warp always stayed "busy"

    # -------------------------------------------------------- requests
    def handle(self, name, f, now):
        if name == 'ChatAuthenticateUserRequest':
            if self.m:
                self.m.lang = f.get('language')          # the client's language: raw rejection texts (shop.reason)
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
        """UIButtonTriggerRequest: reply by the window opened (the warp window). The client sends the notification twice at startup,
        the real server replies once (save); the second goes unanswered (live trial 2026-10-17: the rejection text appeared twice)."""
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
            self.send(msgs, 'ship teleport')
        if changed and self.reload:
            self.reload()

    def tick(self, now):
        return self.auction.settle(now) + self.auction.auto(now)     # the panel's auto bids and alarms

    # -------------------------------------------------------- login
    def login_replace(self, name, f):
        """In place of the saved message in the login bundle (None if none): the chat address to the local server, unread mail from the profile."""
        if name == 'ChatParamCommand':
            port = self.chat.port if self.chat else 7771
            return [(name, {'moduleList': [dict(m, param1=(self.chat_host or CHAT_HOST % port) if m.get('param0') == 'chat_ip' else
                                                ('http://127.0.0.1/crossdomain.xml' if m.get('param0') == 'chat_cross_ip'
                                                 else m.get('param1', '')))
                                           for m in f.get('moduleList', [])]})]
        if name == 'UserMessageNewCommand':
            return [(name, {'userMessageInfoCommand': None, 'unreadCount': self.mailer.unread()})]
        return None

    # -------------------------------------------------------- chat
    def chat_user(self):
        import admin_mode as YM
        pl = self.p.d['pilot']
        return {'userId': pl.get('userName', ''), 'id': str(self.p.user_id), 'globalId': str(self.p.user_id),
                'role': YM.chat_role(self.p),                      # admin mode: "admin" (the client's admin color)
                'clanTag': pl.get('clanTag', ''), 'factionId': str(pl.get('factionId', 0)), 'instanceId': '1'}

    def rooms(self):
        fac = self.p.d['pilot'].get('factionId', 0)
        g = GR.group_of(self.p.user_id)               # on the friend server the group's room (the client reconnects to chat when it joins a group)
        return [('global', 'global', 'local'), ('faction', 'faction', str(fac))] + self.clan.rooms() + \
            ([GR.room(g.id)] if g is not None else [])

    def chat_login(self, ep, lang):
        if not self.chat:
            self.log('   no chat server')
            return False
        self.ep = ep
        ok = self.chat.authenticate(ep, self.chat_user(), self.rooms(), lang)
        if ok and not self.welcomed:                  # on a map change the client may reconnect: the announcement once per session
            self.welcomed = True
            mode = 'single' if not CO.is_open() else 'friend' if CO.SETTINGS['guest'] else 'multi'    # multi: multi-client (this computer)
            text = {'single': '%s, yerel sunucuya hoş geldin. Burada sohbet, posta, klan ve müzayede tek oyunculudur.',
                    'friend': '%s, arkadaş sunucusuna hoş geldin. Sohbet, posta, grup, rehber, klanlar ve sıralamalar ortak; '
                               'müzayede her oyuncunun kendisinin.',
                    'multi': '%s, yerel sunucuya hoş geldin. Bu bilgisayardaki öteki kayıtlarınla aynı evrendesin: sohbet, posta, grup, '
                             'rehber, klanlar ve sıralamalar ortak; müzayede her oyuncunun kendisinin.'}[mode] if lang == 'tr' else {
                    'single': '%s, welcome to your local server. Chat, mail, clan and auction are single-player here.',
                    'friend': "%s, welcome to your friend's server. Chat, mail, groups, contacts, clans and rankings are shared; "
                               "auction is each player's own.",
                    'multi': '%s, welcome to your local server. You share this universe with your other saves on this computer: chat, '
                             "mail, groups, contacts, clans and rankings are shared; auction is each player's own."}[mode]
            self.chat.announcement(text % self.p.d['pilot'].get('userName', ''), who=str(self.p.user_id))
        return ok

    def clan_changed(self):
        """Joined or left a clan, or the tag changed: the tag in chat and the clan room (the old clan's room is left; before, a player who left a clan
        kept receiving its clan chat because only joining was handled)."""
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
