"""Yöneticinin sohbet makinesi (Yonetici bundan türer): botların yazdıkları, oyuncunun mesajlarına yanıtlar, yardım çağrıları,
olaylardan doğan sohbet ve kendiliğinden konuşma.

Satırlar insan yazma süresi kadar gecikir (konusma.yazma_suresi), global/firma kanalında dakikada en çok sohbet_dk satır. Oyuncunun
mesajları sohbet iş parçacığından gelen'e eklenir, yöneticinin tick'inde işlenir. Gelişmiş kipte önce LLM (llm.py) denenir;
yetişemezse ya da LLM yoksa speech.py'nin kalıpları.
"""
import random, re, time, traceback

import map_links as H
from . import name_style as NS
from . import brain as B
from . import catalog as K
from . import interaction as IX
from . import speech as SPC
from . import moderation as MOD
from . import admin_warnings as AW

EVENT_SEC = 5.0
RECRUIT_CLAN_SEC = 7200.0                   # aynı klanın alım ilanı arası (iki saat)
RECRUIT_ANY_SEC = 1500.0                  # herhangi bir klanın ilanı arası
COMPLAINT_SEC = 1800.0                     # lag/uridyum sızlanması arası (tüm sohbette)
REPEAT_SEC = 2700.0                      # aynı satır bu süre içinde ikinci kez yazılmaz
BOT_GAP_SEC = 600.0                      # aynı botun kendiliğinden iki lafı arası en az
RUDE_FACTOR = (0.0, 1.0, 1.6, 2.2)      # kaba_sohbet düzeyine göre hakarete karşılık verme olasılığı çarpanı
FIRMA = {1: 'MMO', 2: 'EIC', 3: 'VRU'}


def user(b):
    """Botun sohbetteki gönderen bilgisi (sosyal.Sosyal.chat_user biçimi)."""
    p = b.profile
    tag = p.d['pilot'].get('clanTag', '') if p is not None else ''
    if b.__dict__.get('moderator'):
        # [CM] etiketiyle, "mod" rolünde: istemci yaması (panel/plugin/Yamalar.cs ModeratorRengi) onu kendi rengiyle çizer; yamasız
        # istemcide beyaz (istemci yalnız admin'i renklendirir, o da etiketi gizleyip "Yönetici" yazar)
        return {'userId': b.name, 'id': str(b.uid), 'globalId': str(b.uid), 'role': MOD.CHAT_ROLE, 'clanTag': MOD.TAG,
                'factionId': str(b.firma), 'instanceId': '1'}
    return {'userId': b.name, 'id': str(b.uid), 'globalId': str(b.uid), 'role': 'chatter', 'clanTag': tag, 'factionId': str(b.firma),
            'instanceId': '1'}


def channel_path(b, channel):
    if channel == 'global':
        return '/room/global/yerel/'
    if channel == 'firma':
        return '/room/faction/%d/' % b.firma
    if channel == 'klan':
        return '/room/clan/%d/' % b.k['klan'] if b.k.get('klan') else None
    if channel == 'grup':
        import group as GR
        g = GR.group_of(b.uid)
        return '/room/group/grup_%d/' % g.id if g is not None else None
    return None


def channel_name(route):
    return 'global' if route.startswith('/room/global/') else 'firma' if route.startswith('/room/faction/') else \
        'klan' if route.startswith('/room/clan/') else 'grup' if route.startswith('/room/group/') else None


class ChatEngine:
    def prepare_chat(self):
        self.chat = None             # sohbet.Sohbet (toplum.kaydol)
        self.llm = None                # Gelişmiş kip: llm.Beyin
        self.outgoing = []                # [(an, bot, kanal, metin, alıcı, öncelik, ilk an)]: yazılmayı bekleyen satırlar
        self.incoming = []                # sohbetten gelenler (sohbet iş parçacığı ekler, tick işler)
        self.history = []               # son sohbet satırları [(an, ad, kanal, metin, oda yolu)]: LLM bağlamı (oda yolu: hangi firmanın,
        #                                klanın, grubun kanalı; fısıltıda None)
        self.last_word = 0.0
        self.actions = []             # [(an, bot, (araç, argümanlar))]: kararın eylemi, yanıt yazıldıktan sonra (etkilesim.uygula)
        self._lines = []            # son bir dakikadaki bot satırlarının anları (sohbet_dk)
        self._last_text = []           # [(an, sadeleşmiş metin)]: son kendiliğinden satırlar (tekrar önleme)
        self._last_recruit = {}            # klan anahtarı (None: hepsi) -> son alım ilanı anı
        self._last_complaint = 0.0

    def speak(self, b, channel, text, recipient=None, now=None, immediate=False, priority=False):
        """Bot yazacak: insan yazma süresi kadar sonra gider (fısıltı: alici). oncelik: oyuncuya yanıt; kanal sınırına takılmaz.
        Kuyruğa girerse satırın gideceği anı döndürür (konuşma zinciri bunun üstüne yanıt ekler), girmezse None."""
        if not text or not self.permission('sohbet'):
            return None
        now = now or self.now
        if not priority and AW.active(b, 'sohbet', now) and b.r.random() < 0.75:
            return None                                  # yönetici sohbet uyarısı: yalnız yanıtlar, çoğu kez susar
        t = now + (0 if immediate else SPC.typing_time(text, b))
        self.outgoing.append((t, b, channel, text, recipient, priority, t))
        return t

    def pending_texts(self):
        return [x[3] for x in self.outgoing]

    def chat_tick(self, now):
        """Zamanı gelen satırlar gönderilir; gelen mesajlar ve olaylar sohbete dönüşür; ara sıra kendiliğinden sohbet."""
        if self.incoming:
            incoming, self.incoming = self.incoming, []
            for g in incoming:
                try:
                    self.handle_chat(g, now)
                except Exception:
                    self.log('   botlar: sohbet hatası\n' + traceback.format_exc())
        if now - self.last_word >= EVENT_SEC:
            self.last_word = now
            self.event_tick(now)
            self.spontaneous(now)
            self.throw_banter(now)
            self.start_private(now)
            self.group_banter_line(now)
            AW.sight_tick(self, now)
            MOD.remind_rules(self, now)
        if self.actions:
            is_due = [x for x in self.actions if x[0] <= now]
            self.actions = [x for x in self.actions if x[0] > now]
            from . import agent_tools as TL
            for _, b, (tool, arg) in is_due:
                if b.online:
                    TL.call(self, b, tool, arg)
        if self.outgoing:
            is_due = [x for x in self.outgoing if x[0] <= now]
            self.outgoing = [x for x in self.outgoing if x[0] > now]
            for x in is_due:                              # gonder bekleyeni yeniden ekleyebilir
                self.send(x, now)

    def send(self, x, now):
        t, b, channel, text, recipient, priority, first = x
        if not b.online:
            return
        if channel in ('global', 'firma'):
            if MOD.is_muted(self, b.name, now) > 0:
                return                                   # moderatör susturdu
            self._lines = [s for s in self._lines if now - s < 60]
            if len(self._lines) >= self.setting('sohbet_dk', 6) and not priority:
                if now - first < 60:                       # kanal sınırı: biraz bekler (sohbet sele dönmesin); çok bekleyen düşer
                    self.outgoing.append((now + b.r.uniform(6, 15), b, channel, text, recipient, priority, first))
                return
            self._lines.append(now)
        self.history.append((now, b.name, channel if not recipient else 'fisilti:' + recipient, text, None if recipient else channel_path(b, channel)))
        del self.history[:-600]               # fısıltı bağlamı kalabalık sohbette hemen silinmesin (güçlü sağlayıcı saatlerce geriye bakar)
        b.event('dedim', now, kanal=channel, metin=text, alici=recipient)
        if self.chat is None:
            return
        if recipient:
            self.chat.bot_whisper(recipient, text, 'bot%d' % b.uid, user(b))
            return
        route = channel_path(b, channel)
        if route:
            self.chat.broadcast(route, text, 'bot%d' % b.uid, user(b))
        MOD.moderate(self, b.name, text, channel, now)       # botlar da kurala uyar (kaba bot susturulabilir)

    def incoming_chat(self, route, msg, who):
        """Sohbet iş parçacığından: oyuncunun oda mesajı (işlenmesi tick'te)."""
        self.incoming.append(('oda', route, msg, who))
        self.history.append((time.time(), who.get('userId', '?'), channel_name(route) or route, msg, route))

    def incoming_whisper(self, name, msg, who):
        """Sohbet iş parçacığından: oyuncu bir bota fısıldadı -> alıcı çevrimiçi bot mu (değilse istemci "çevrimdışı" yazar)."""
        b = self.name_index.get(str(name).lower())
        if b is None or not b.online:
            return False
        self.incoming.append(('fisilti', b, msg, who))
        self.history.append((time.time(), who.get('userId', '?'), 'fisilti:' + b.name, msg))
        return True

    def handle_chat(self, g, now):
        if g[0] == 'oda':
            MOD.moderate(self, g[3].get('userId', ''), g[2], channel_name(g[1]), now, g[3].get('role') or 'chatter')
        from . import clan_orders as CO
        if g[0] == 'oda' and channel_name(g[1]) == 'klan' and CO.handle(self, 'klan', g[2], g[3], self.listeners('klan', g[3]), now):
            return                                       # klan emri (odak, git, gel, savun, al, gemi, yapı, dur)
        if g[0] == 'fisilti' and CO.handle(self, 'fisilti', g[2], g[3], [g[1]], now):
            return
        if AW.handle(self, g, now):                        # yöneticinin uyarısı ya da selamı (bot/yonetici_uyari.py)
            return
        if self.llm is not None and self.llm.chat(self, g, now):
            return
        if g[0] == 'fisilti':
            self.template_whisper(g[1], g[2], g[3], now)
        else:
            self.template_room(g[1], g[2], g[3], now)

    def listeners(self, channel, who):
        fac = int(who.get('factionId') or 0)
        out = [b for b in self.bots if b.online and b.dead_until <= self.now]
        if channel == 'firma':
            out = [b for b in out if b.firma == fac]
        elif channel == 'klan':
            out = [b for b in out if b.profile is not None and who.get('clanTag') and b.profile.d['pilot'].get('clanTag') == who['clanTag']]
        elif channel == 'grup':
            import group as GR
            import community as TP
            k = TP.find(name=who.get('userId'))
            g = GR.group_of(k.uid) if k is not None else None
            out = [b for b in out if g is not None and b.uid in g.members]
        return out

    def template_room(self, route, msg, who, now):
        channel = channel_name(route)
        name = who.get('userId', '')
        if channel is None or name.lower() in self.name_index:
            return
        kind, game_map = SPC.intent(msg)
        listener = self.listeners(channel, who)
        mentioned = [b for b in listener if NS.is_mentioned(b.name, msg)]
        for b in mentioned:
            b.memory.event(name, 'sohbet', now)
            if kind in IX.INTENTS and kind != 'yardim':
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
            elif kind == 'hakaret':
                b.memory.event(name, 'hakaret', now)
                if b.r.random() < b.o('saldirganlik') * RUDE_FACTOR[self.rude()]:
                    self.speak(b, channel, SPC.template(b, self.banter(b, 'cevap_hakaret'), ad=name), now=now)
            elif kind == 'yardim':
                self.help_call(name, who, game_map, [b], channel, now)
            elif b.r.random() < 0.85:
                self.speak(b, channel, SPC.template(b, {'selam': 'cevap_selam', 'tesekkur': 'tesekkur'}.get(kind, 'cevap_soru'), ad=name),
                           now=now)
        if mentioned:
            return
        if kind == 'yardim' and game_map:
            self.help_call(name, who, game_map, listener, channel, now)
        elif kind in ('grup', 'klan', 'gorev', 'duello', 'ozel', 'kapi'):
            for b in self.open_call(kind, name, who, game_map, msg, listener, now):
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
        elif kind == 'takip' and channel == 'grup':              # grup sohbetinde "follow me / come 2-4": grubun botları
            for b in listener[:3]:
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
        elif kind == 'selam':
            for b in [b for b in listener if b.r.random() < 0.3 * b.o('sosyallik')][:2]:
                self.speak(b, channel, SPC.template(b, 'cevap_selam', ad=name), now=now)
        elif kind == 'soru' and listener:
            b = max(listener, key=lambda b: b.o('konuskanlik') * b.r.random())
            if b.r.random() < 0.3 + 0.4 * b.o('yardimseverlik'):
                self.speak(b, channel, SPC.template(b, 'cevap_soru'), now=now)

    def help_call(self, name, who, game_map, candidates, channel, now, max_count=None, required=False, silent=False):
        """Yardım çağrısı: aynı firmadan, yardımsever, o haritaya girebilen ve gidebilen botlardan bazıları gelir -> gelenler.
        zorunlu: karar başkasında, olasılık atılmaz; sessiz: kalıp yanıt yazılmaz (Gelişmiş kipte yanıtı model söyler)."""
        if not self.permission('yardim'):
            return []
        fac = int(who.get('factionId') or 0)
        ids = {v: k for k, v in H.NAMES.items()}
        m = ids.get(game_map) if game_map else None
        if m is None:
            # harita yazılmadı: oyuncunun haritası, ama yalnız gerçekten saldırı altındaysa (son 90 sn'de hasar aldı); yoksa
            # "help"in başka anlamı var ("help me with quest", şaka) ve kimse savaşa koşmaz (oyuncu bildirimi 2026-10-30)
            import community as TP
            k = TP.find(name=name)
            w = k.world if k is not None else None
            m = int(k.profile.d['konum'].get('mapId', 0)) if w is not None and now - getattr(w, 'last_hurt', 0) < 90 else None
        if m is None or int(m) not in K.MAPS:
            return []
        incoming = []
        for b in sorted(candidates, key=lambda b: -b.o('yardimseverlik') * b.r.uniform(0.6, 1.4)):
            if len(incoming) >= (max_count or self.setting('yardim_en_cok', 3)):
                break
            if b.firma != fac or not K.can_enter(m, b.firma, b.level) or not K.route(b.game_map, m, b.firma, b.level):
                continue
            p = 0.15 + 0.6 * b.o('yardimseverlik') + 0.5 * b.memory.relation(name, now) - 0.3 * b.mood['yorgunluk']
            if b.target is not None and b.target.name in ('gorev', 'grup'):
                p -= 0.2
            if required or b.r.random() < p:
                incoming.append(b)
                B.force(b, 'yardim', plan={'harita': int(m), 'ad': name}, pay=1.2, duration=900, now=now)
                b.memory.event(name, 'yardim_ettim', now)
                if not required and not silent:
                    self.speak(b, channel, SPC.template(b, 'yardima_gidiyor', harita=H.name(m)), now=now)
        return incoming

    def open_call(self, kind, name, who, game_map, msg, listener, now):
        """Kimseye hitap etmeyen istek ("grup olalım mı", "klan alan var mı"): yanıt verecek botlar. Grup: aynı firmadan sosyal
        botlar sırayla düşünür, kabul eden ilk biri (gerçek sohbette olduğu gibi bir kişi "inv" der). Klan: klanı olan, aynı
        firmadan en çok iki bot (lider önce)."""
        fac = int(who.get('factionId') or 0)
        if kind == 'duello':                               # meydan okumayı başka firmadan biri kabul eder
            for b in sorted([b for b in listener if b.firma != fac], key=lambda b: -b.o('saldirganlik') * b.r.uniform(0.5, 1.5))[:4]:
                k = IX.decision(self, b, 'duello', name, who, game_map, msg, now)
                if k and k['kabul']:
                    b._request_decision = k
                    return [b]
            return []
        candidate = [b for b in listener if not fac or b.firma == fac]
        if kind == 'kapi':                                 # kapı dolgusu: istenen sayıda (yoksa 3) kabul eden
            import re
            m = re.search(r'\b([1-7])\b', msg or '')
            n, out = int(m.group(1)) if m else 3, []
            for b in sorted(candidate, key=lambda b: -(b.o('sosyallik') + b.o('hirs')) * b.r.uniform(0.5, 1.5))[:12]:
                k = IX.decision(self, b, 'kapi', name, who, game_map, msg, now)
                if k and k['kabul']:
                    b._request_decision = k
                    out.append(b)
                    if len(out) >= n:
                        break
            return out
        if kind in ('grup', 'gorev', 'ozel'):
            for b in sorted(candidate, key=lambda b: -b.o('sosyallik') * b.r.uniform(0.5, 1.5))[:4]:
                k = IX.decision(self, b, kind, name, who, game_map, msg, now)
                if k and k['kabul']:
                    b._request_decision = k
                    return [b]
            return []
        import clan as KL
        from . import society
        clan_bots = [b for b in candidate if KL.clan_of(society.profile(b)) is not None]
        return sorted(clan_bots, key=lambda b: (KL.clan_of(b.profile)['lider'] != b.name.lower(), -b.o('konuskanlik')))[:2]

    def answer_request(self, b, kind, name, who, game_map, msg, channel, now):
        """Normal kip: kararı (etkilesim) uygula, kalıpla söyle."""
        k = b.__dict__.pop('_request_decision', None) or IX.decision(self, b, kind, name, who, game_map, msg, now)
        if k is None:
            return
        text = SPC.template(b, k['kalip'][0], **k['kalip'][1]) if k.get('kalip') else None
        IX.apply(self, b, k, delay=SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3))
        if text:
            if k.get('fisilti'):
                channel = 'fisilti'                             # "bana PM at": yanıt özelden
            self.speak(b, channel, text, recipient=name if channel == 'fisilti' else None, now=now)

    def template_whisper(self, b, msg, who, now):
        name = who.get('userId', '')
        kind, game_map = SPC.intent(msg)
        kind = IX.offer_reply(b, name, msg, now) or kind       # "gruplaşalım mı?" -> "sure": grup isteği
        b.memory.event(name, 'sohbet', now)
        if kind in IX.INTENTS and kind != 'yardim':
            self.answer_request(b, kind, name, who, game_map, msg, 'fisilti', now)
        elif kind == 'yardim':
            if self.help_call(name, who, game_map, [b], 'firma', now):
                self.outgoing = [x for x in self.outgoing if not (x[1] is b and x[2] == 'firma')]
                self.speak(b, 'fisilti', SPC.template(b, 'cevap_evet'), recipient=name, now=now)
            else:
                self.speak(b, 'fisilti', SPC.template(b, 'cevap_hayir'), recipient=name, now=now)
        elif kind == 'hakaret':
            b.memory.event(name, 'hakaret', now)
            if b.r.random() < 0.6 * RUDE_FACTOR[self.rude()]:
                self.speak(b, 'fisilti', SPC.template(b, self.banter(b, 'cevap_hakaret'), ad=name), recipient=name, now=now)
        else:
            self.speak(b, 'fisilti', SPC.template(b, {'selam': 'cevap_selam', 'tesekkur': 'tesekkur'}.get(kind, 'cevap_soru'), ad=name),
                       recipient=name, now=now)

    def event_tick(self, now):
        """Botların yeni olayları sohbete dönüşür (seviye, yeni gemi, PvP); Gelişmiş kipte LLM'in bağlamına da gider."""
        for b in self.bots:
            if not b.online:
                continue
            t0 = getattr(b, '_event_time', now)
            new_ = [o for o in b.events if o['t'] > t0]
            b._event_time = now
            for o in new_:
                self.event_chat(b, o, now)

    def event_chat(self, b, o, now):
        if self.llm is not None and self.llm.event(self, b, o, now):
            return
        talk = b.o('konuskanlik')
        kind = o['tur']
        if kind == 'tanik':
            if o.get('alt') == 'patron' and o.get('kim') and str(o['kim']).lower() != b.name.lower():
                self.speak(b, 'firma', SPC.template(b, 'tanik_patron', kim=o['kim']), now=now + b.r.uniform(2, 8))
            elif o.get('alt') == 'oyuncu_oldu' and o.get('ad'):
                self.speak(b, 'firma', SPC.template(b, 'tanik_olum', ad=o['ad']), now=now + b.r.uniform(2, 10))
            return
        if kind == 'diplomasi' and (o.get('kabul') or not o.get('gelen')) and o.get('form') in (0, 1, 3) and b.r.random() < 0.4 + 0.5 * talk:
            durum = {0: 'baris', 1: 'ittifak', 3: 'savas_ilan'}[o['form']]
            if o['form'] == 0 and not o.get('gelen'):
                return                                   # barış isteği: kabul edilmeden ilan edilmez
            self.speak(b, 'global' if o['form'] == 3 else 'firma',
                       SPC.template(b, durum, klan=o.get('klan', ''), etiket=o.get('etiket') or o.get('klan', '')), now=now + b.r.uniform(5, 30))
            return
        if kind == 'patron_oldurdum' and b.r.random() < 0.3 * talk:
            self.speak(b, 'firma', SPC.template(b, 'patron_oldurdum'), now=now + b.r.uniform(2, 8))
            return
        if kind == 'seviye' and b.r.random() < 0.25 * talk:
            self.speak(b, 'firma', SPC.template(b, 'seviye', seviye=o.get('seviye')), now=now)
        elif kind == 'yeni_gemi' and b.r.random() < 0.45 * talk:
            self.speak(b, 'global', SPC.template(b, 'yeni_gemi', gemi=str(o.get('esya', '')).replace('ship_', '').title()), now=now)
        elif kind in ('olum', 'oyuncu_oldurdum') and now - self.__dict__.setdefault('_last_whisper', {}).get(
                str(o.get('katil') or o.get('ad') or '').lower(), 0) < 60:
            pass                                         # aynı oyuncuya dakikada en çok bir fısıltı (art arda öldürmede yağmur olmasın)
        elif kind == 'olum' and o.get('katil') and str(o['katil']).lower() not in self.name_index and b.r.random() < 0.2 + 0.5 * talk:
            self._last_whisper[str(o['katil']).lower()] = now
            rude = self.rude()
            angry = rude and b.mood['ofke'] > 0.55 - 0.1 * rude and b.o('saldirganlik') > 0.6 - 0.1 * rude
            self.speak(b, 'fisilti', SPC.template(b, 'oldum_kizgin' if angry else 'oldum'), recipient=o['katil'], now=now)
        elif kind == 'oyuncu_oldurdum' and b.r.random() < 0.25 + 0.3 * talk:
            self.__dict__.setdefault('_last_whisper', {})[str(o.get('ad') or '').lower()] = now
            rude = self.rude()
            self.speak(b, 'fisilti', SPC.template(b, 'oldurdum') if rude else 'gg', recipient=o.get('ad'), now=now)
            if rude >= 2 and o.get('ad') and b.r.random() < 0.25 * (rude - 1) * b.o('saldirganlik'):
                self.speak(b, 'global', SPC.template(b, 'laf_oldurdum', ad=o['ad'], harita=H.name(b.game_map)), now=now + b.r.uniform(4, 15))
        elif kind == 'klan_kurdu' and self.can_recruit(o.get('ad'), now):
            self.speak(b, 'global', SPC.template(b, 'klan_alim', etiket=o.get('etiket'), klan=o.get('ad'), seviye=max(3, b.level - 4)),
                       now=now + b.r.uniform(20, 120))

    def online_humans(self):
        """Çevrimiçi insan oyuncular (topluluk.Kisi; paketin botları hariç)."""
        import community as TP
        try:
            return [k for k in TP.all_().values() if k.session is not None and k.name.lower() not in self.name_index]
        except Exception:
            return []

    def start_private(self, now):
        """Arkadaş bot oyuncuya kendiliğinden fısıldar: girişinde selam, arada grup teklifi ya da hal hatır (oyuncu başına en çok
        12 dakikada bir; yalnız aynı firmadan, ona ilişkisi iyi botlar). Grup teklifine olumlu yanıt davete dönüşür (teklif_ver)."""
        if not self.permission('sohbet'):
            return
        seen = self.__dict__.setdefault('human_first', {})
        last = self.__dict__.setdefault('human_whisper', {})
        for k in self.online_humans():
            a = k.name.lower()
            first = seen.setdefault(a, now)
            if now - last.get(a, 0) < 720 or now - first < 20:
                continue
            fac = int(k.profile.d['pilot'].get('factionId', 0))
            friendly = [b for b in self.bots if b.online and b.dead_until <= now and b.firma == fac and b.memory.relation(k.name, now) >= 0.3]
            if not friendly:
                continue
            b = max(friendly, key=lambda b: b.memory.relation(k.name, now) * b.r.uniform(0.6, 1.4))
            if now - first < 300 and not last.get(a):
                purpose = 'ozel_selam'                          # yeni girdi
            elif b.r.random() > 0.35 * (0.5 + b.o('sosyallik')):
                last[a] = now - 360                           # bu sefer yazmaz (yarım aralık sonra yine bakar)
                continue
            elif self.permission('grup') and b.target is not None and b.target.name in ('kasilma', 'gorev') and b.r.random() < 0.6:
                purpose = 'ozel_grup'
            else:
                purpose = 'ozel_sohbet'
            last[a] = now
            if purpose == 'ozel_grup':
                IX.make_offer(b, 'grup', k.name, now)
            if self.llm is not None and self.llm.ready and self.llm.special(self, b, k.name, purpose):
                continue
            self.speak(b, 'fisilti', SPC.template(b, purpose, ad=k.name, harita=H.name(b.game_map)), recipient=k.name, now=now + b.r.uniform(2, 10))

    def group_banter_line(self, now):
        """İnsanla grupta olan bot arada grup sohbetine yazar (nereye gidiyoruz, iyi kestik ...): 4-8 dakikada bir."""
        if not self.permission('sohbet'):
            return
        import group as GR
        for k in self.online_humans():
            g = GR.group_of(k.uid)
            if g is None:
                continue
            members = [b for b in self.bots if b.uid in g.members and b.online and b.dead_until <= now]
            if not members or now < g.__dict__.get('_bot_banter', 0):
                continue
            g._bot_banter = now + random.uniform(240, 480)
            if not g.__dict__.get('_bot_banter_first'):
                g._bot_banter_first = True
                continue                                     # grup yeni kuruldu: ilk lafı hemen değil
            b = max(members, key=lambda b: b.o('konuskanlik') * b.r.random())
            if self.llm is not None and self.llm.ready and self.llm.group_banter_line(self, b, k.name):
                continue
            self.speak(b, 'grup', SPC.template(b, 'grup_laf'), now=now)

    def rude(self):
        return int(self.setting('kaba_sohbet', 1) or 0)

    def banter(self, b, durum):
        """Sert düzeyde saldırgan bot hakarete sert karşılık verir."""
        return 'laf_sert' if self.rude() >= 2 and b.o('saldirganlik') > 0.5 and not b.__dict__.get('moderator') else durum

    def throw_banter(self, now):
        """Sert ve çok sert düzeyde saldırgan botlar globalde başka firmaya ya da çevrimiçi düşman oyuncuya laf atar (kinliler önce)."""
        rude = self.rude()
        if rude < 2 or random.random() > 0.05 * (rude - 1):
            return
        is_open = [b for b in self.bots if b.online and b.dead_until <= now and b.o('saldirganlik') > 0.55
                and not b.__dict__.get('moderator')]
        if not is_open:
            return
        b = max(is_open, key=lambda b: b.o('saldirganlik') * b.r.random())
        enemy = [k for k in self.online_humans() if int(k.profile.d['pilot'].get('factionId', 0)) != b.firma]
        grudge = [k for k in enemy if b.memory.relation(k.name, now) < -0.2]
        if (grudge or enemy) and b.r.random() < (0.8 if grudge else 0.3 * (rude - 1)):
            k = b.r.choice(grudge or enemy)
            self.speak(b, 'global', SPC.template(b, 'laf_oyuncu', ad=k.name, harita=H.name(b.game_map)), now=now)
        else:
            self.speak(b, 'global', SPC.template(b, 'laf_firma', firma=b.r.choice([f for f in ('MMO', 'EIC', 'VRU') if f != FIRMA[b.firma]])),
                       now=now)

    def can_recruit(self, clan, now):
        """Klan alım ilanı yazılabilir mi (klan başına iki saatte, hepsi birlikte 25 dakikada en çok bir); yazılabilirse sayar."""
        if now - self._last_recruit.get(None, -1e9) < RECRUIT_ANY_SEC or now - self._last_recruit.get(clan, -1e9) < RECRUIT_CLAN_SEC:
            return False
        self._last_recruit[None] = self._last_recruit[clan] = now
        return True

    def new_text(self, b, durum, now, **f):
        """Durumun kalıbından, son 45 dakikada yazılmamış bir satır (4 denemede yoksa None)."""
        self._last_text = [x for x in self._last_text if now - x[0] < REPEAT_SEC]
        for _ in range(4):
            m = SPC.template(b, durum, **f)
            if m and re.sub(r'\W+', '', m.lower()) not in (x[1] for x in self._last_text):
                return m
        return None

    def wrote(self, b, text, now):
        self._last_text.append((now, re.sub(r'\W+', '', text.lower())))
        b._last_word = now

    def status_line(self, b, now):
        """Botun gerçekten yaptığı ya da az önce yaptığı bir şeyden (kapı bitti, alışveriş, ölüm, görev, dolu kargo, kasma) bir satır
        -> (durum, alanlar) ya da None. Seviye ve yeni gemi zaten olay_sohbet'te yazılır; aynı olay iki kez anlatılmaz."""
        told = b.__dict__.setdefault('_told', set())
        candidates = []
        for o in b.events[-12:]:
            if now - o['t'] > 900 or (o['tur'], o['t']) in told:
                continue
            t = o['tur']
            if t == 'kapi_tamam':
                candidates.append(('durum_kapi', dict(kapi=o['kapi']), o))
            elif t == 'alim' and not str(o.get('esya', '')).startswith('ship_'):
                item = re.sub(r'^(drone|equipment|resource)_', '', str(o.get('esya', ''))).replace('_', ' ')
                candidates.append(('durum_alim', dict(esya=item), o))
            elif t == 'olum' and o.get('neden') == 'npc':
                candidates.append(('durum_olum', dict(harita=o.get('harita', H.name(b.game_map))), o))
            elif t == 'gorev_bitti' and o.get('ad'):
                candidates.append(('durum_gorev', dict(ad=o['ad']), o))
            elif t == 'kacti':
                candidates.append(('durum_kacti', dict(harita=o.get('harita', H.name(b.game_map))), o))
        try:
            if b.cargo_fill() > 0.85:
                candidates.append(('durum_kargo', dict(yuzde=int(b.cargo_fill() * 100)), None))
        except Exception:
            pass
        if b.target is not None and b.target.name == 'kasilma':
            candidates.append(('durum_kasma', dict(harita=H.name(b.game_map)), None))
        npc = b.k['istat'].get('npc', 0)
        if npc >= 50:
            candidates.append(('durum_istat', dict(npc=npc, olum=b.k['istat'].get('olum', 0)), None))
        if not candidates:
            return None
        d, f, o = b.r.choice(candidates)
        if o is not None:
            told.add((o['tur'], o['t']))
            if len(told) > 60:
                told.clear()
        f.setdefault('harita', H.name(b.game_map))
        f.setdefault('seviye', b.level)
        return d, f

    def start_dialog(self, b, is_open, channel, now):
        """b bir soru/laf yazar; başka bir çevrimiçi bot (aynı dil, firma kanalında aynı firma) insan gecikmesiyle yanıtlar, bazen
        b de karşılık verir (en çok 3 satır). Yanıt gelmeyebilir; her satırın gideceği an bir öncekinin üstüne eklenir."""
        chat = SPC.dialogue(b)
        if not chat:
            return False
        take = lambda x, kind: SPC.dialogue_line(x, kind, harita=H.name(x.game_map), seviye=x.level)
        m = take(b, chat[0])
        if not m or re.sub(r'\W+', '', m.lower()) in (x[1] for x in self._last_text):
            return False
        t = self.speak(b, channel, m, now=now)
        if t is None:
            return False
        self.wrote(b, m, now)
        candidates = [c for c in is_open if c is not b and SPC.lang(c) == SPC.lang(b) and (channel == 'global' or c.firma == b.firma)]
        if not candidates:
            return True
        c = max(candidates, key=lambda x: x.o('sosyallik') * x.r.random())
        if b.r.random() > 0.3 + 0.55 * c.o('sosyallik'):
            return True                                  # kimse yanıtlamadı
        for i, kind in enumerate(chat[1:]):
            who = c if i % 2 == 0 else b
            m = next((x for x in (take(who, kind) for _ in range(3)) if x and re.sub(r'\W+', '', x.lower()) not in
                      (y[1] for y in self._last_text)), None)
            if not m:
                break
            t = self.speak(who, channel, m, now=t + who.r.uniform(5, 22))
            if t is None:
                break
            self._last_text.append((now, re.sub(r'\W+', '', m.lower())))
        return True

    def spontaneous(self, now):
        """Ara sıra bir bot kendiliğinden yazar: yaptığı şeyden satır, kısa konuşma, grup arama, ticaret, genel laf, nadiren klan alım
        ilanı ve sızlanma. Kanal sınırı içinde; aynı satır, aynı bot ve aynı klanın ilanı sık tekrarlanmaz."""
        if self.llm is not None and self.llm.ready:
            return                                   # Gelişmiş kipte kendiliğinden sohbeti model yapar (llm.bot_sohbet)
        is_open = [b for b in self.bots if b.online and b.dead_until <= now]
        if not is_open or random.random() > 0.065 * min(1.0, len(is_open) / 10.0):
            return
        available = [b for b in is_open if now - b.__dict__.get('_last_word', -1e9) >= BOT_GAP_SEC]
        if not available:
            return
        b = max(available, key=lambda b: b.o('konuskanlik') * b.r.random())
        k = b.r.random()
        if b.k.get('klan') and b.archetype == 'lider' and k < 0.3:
            import clan as KL
            c = KL.CLANS.get(b.k['klan'])
            if c is not None and c['lider'] == b.name.lower() and self.can_recruit(b.k['klan'], now):
                m = self.new_text(b, 'klan_alim', now, etiket=c['etiket'], klan=c['ad'], seviye=max(3, b.level - 4))
                if m and self.speak(b, 'global', m, now=now) is not None:
                    self.wrote(b, m, now)
                    return
        if b.archetype == 'tuccar' and k < 0.4:
            m, channel = self.new_text(b, 'ticaret', now, esya='LF-3'), 'global'
        elif b.o('sosyallik') > 0.6 and k < 0.35:
            m, channel = self.new_text(b, 'grup_ara', now, harita=H.name(b.game_map)), 'firma'
        else:
            channel, r = b.r.choice(('global', 'firma')), b.r.random()
            m = None
            if r < 0.4:
                d = self.status_line(b, now)
                m = self.new_text(b, d[0], now, **d[1]) if d else None
            elif r < 0.75:
                if self.start_dialog(b, is_open, channel, now):
                    return
            elif r < 0.8 and now - self._last_complaint >= COMPLAINT_SEC:
                self._last_complaint = now
                m = self.new_text(b, 'sikayet', now)
            if m is None:
                m = self.new_text(b, 'genel', now)
        if m and self.speak(b, channel, m, now=now) is not None:
            self.wrote(b, m, now)
