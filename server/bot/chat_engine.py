"""The Manager's chat engine (Manager derives from it): what the bots write, replies to the player's messages, calls for help,
chat arising from events and spontaneous talk.

Lines are delayed by a human typing time (speech.typing_time), and at most chat_min lines per minute go to the global/company channel.
The player's messages are added to incoming from the chat thread and processed on the manager's tick. In Advanced mode the LLM (llm.py)
is tried first; if it cannot keep up or there is no LLM, the templates of speech.py are used.
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
RECRUIT_CLAN_SEC = 7200.0                   # between recruitment ads of the same clan (two hours)
RECRUIT_ANY_SEC = 1500.0                  # between ads of any clan
COMPLAINT_SEC = 1800.0                     # between lag/uridium complaints (in the whole chat)
REPEAT_SEC = 2700.0                      # the same line is not written a second time within this period
BOT_GAP_SEC = 600.0                      # minimum gap between two spontaneous remarks of the same bot
RUDE_FACTOR = (0.0, 1.0, 1.6, 2.2)      # multiplier of the probability of answering an insult, by rude_chat level
COMPANY = {1: 'MMO', 2: 'EIC', 3: 'VRU'}


def user(b):
    """The bot's sender info in the chat (the social.Social.chat_user format)."""
    p = b.profile
    tag = p.d['pilot'].get('clanTag', '') if p is not None else ''
    if b.__dict__.get('moderator'):
        # with the [CM] tag, in the "mod" role: the client patch (panel/plugin/Patches.cs ModeratorColor) draws it in its own color; on an
        # unpatched client it is white (the client colors only the admin, and that one hides the tag and writes "Manager")
        return {'userId': b.name, 'id': str(b.uid), 'globalId': str(b.uid), 'role': MOD.CHAT_ROLE, 'clanTag': MOD.TAG,
                'factionId': str(b.company), 'instanceId': '1'}
    return {'userId': b.name, 'id': str(b.uid), 'globalId': str(b.uid), 'role': 'chatter', 'clanTag': tag, 'factionId': str(b.company),
            'instanceId': '1'}


def channel_path(b, channel):
    if channel == 'global':
        return '/room/global/yerel/'
    if channel == 'company':
        return '/room/faction/%d/' % b.company
    if channel == 'clan':
        return '/room/clan/%d/' % b.k['clan'] if b.k.get('clan') else None
    if channel == 'group':
        import group as GR
        g = GR.group_of(b.uid)
        return '/room/group/group_%d/' % g.id if g is not None else None
    return None


def channel_name(route):
    return 'global' if route.startswith('/room/global/') else 'company' if route.startswith('/room/faction/') else \
        'clan' if route.startswith('/room/clan/') else 'group' if route.startswith('/room/group/') else None


class ChatEngine:
    def prepare_chat(self):
        self.chat = None             # chat.Chat (society.register)
        self.llm = None                # Advanced mode: llm.Brain
        self.outgoing = []                # [(time, bot, channel, text, recipient, priority, first time)]: lines waiting to be written
        self.incoming = []                # arrivals from the chat (the chat thread adds, tick processes)
        self.history = []               # recent chat lines [(time, name, channel, text, room path)]: LLM context (room path: which company's,
        #                                clan's, group's channel; None for a whisper)
        self.last_word = 0.0
        self.actions = []             # [(time, bot, (tool, arguments))]: the decision's action, after the reply is written (interaction.apply)
        self._lines = []            # times of the bot lines in the last minute (chat_min)
        self._last_text = []           # [(time, simplified text)]: recent spontaneous lines (repeat prevention)
        self._last_recruit = {}            # clan key (None: all) -> time of the last recruitment ad
        self._last_complaint = 0.0

    def speak(self, b, channel, text, recipient=None, now=None, immediate=False, priority=False):
        """A bot will write: it goes out after a human typing time (whisper: recipient). priority: a reply to the player; not subject to the channel limit.
        If queued, returns the time the line will go out (the conversation chain adds replies on top of it), otherwise None."""
        if not text or not self.permission('chat'):
            return None
        now = now or self.now
        if not priority and AW.active(b, 'chat', now) and b.r.random() < 0.75:
            return None                                  # manager's chat warning: only replies, mostly stays silent
        t = now + (0 if immediate else SPC.typing_time(text, b))
        self.outgoing.append((t, b, channel, text, recipient, priority, t))
        return t

    def pending_texts(self):
        return [x[3] for x in self.outgoing]

    def chat_tick(self, now):
        """Due lines are sent; incoming messages and events turn into chat; occasional spontaneous chat."""
        if self.incoming:
            incoming, self.incoming = self.incoming, []
            for g in incoming:
                try:
                    self.handle_chat(g, now)
                except Exception:
                    self.log('   bots: chat error\n' + traceback.format_exc())
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
            for x in is_due:                              # send may re-add a pending one
                self.send(x, now)

    def send(self, x, now):
        t, b, channel, text, recipient, priority, first = x
        if not b.online:
            return
        if channel in ('global', 'company'):
            if MOD.is_muted(self, b.name, now) > 0:
                return                                   # a moderator muted
            self._lines = [s for s in self._lines if now - s < 60]
            if len(self._lines) >= self.setting('chat_min', 6) and not priority:
                if now - first < 60:                       # channel limit: waits a little (so the chat does not flood); those waiting too long are dropped
                    self.outgoing.append((now + b.r.uniform(6, 15), b, channel, text, recipient, priority, first))
                return
            self._lines.append(now)
        self.history.append((now, b.name, channel if not recipient else 'whisper:' + recipient, text, None if recipient else channel_path(b, channel)))
        del self.history[:-600]               # so the whisper context is not deleted right away in a crowded chat (the strong provider looks back for hours)
        b.event('said', now, channel=channel, text=text, recipient=recipient)
        if self.chat is None:
            return
        if recipient:
            self.chat.bot_whisper(recipient, text, 'bot%d' % b.uid, user(b))
            return
        route = channel_path(b, channel)
        if route:
            self.chat.broadcast(route, text, 'bot%d' % b.uid, user(b))
        MOD.moderate(self, b.name, text, channel, now)       # bots obey the rule too (a rude bot can be muted)

    def incoming_chat(self, route, msg, who):
        """From the chat thread: the player's room message (processed on the tick)."""
        self.incoming.append(('room', route, msg, who))
        self.history.append((time.time(), who.get('userId', '?'), channel_name(route) or route, msg, route))

    def incoming_whisper(self, name, msg, who):
        """From the chat thread: the player whispered to a bot -> is the recipient an online bot (if not, the client writes "offline")."""
        b = self.name_index.get(str(name).lower())
        if b is None or not b.online:
            return False
        self.incoming.append(('whisper', b, msg, who))
        self.history.append((time.time(), who.get('userId', '?'), 'whisper:' + b.name, msg))
        return True

    def handle_chat(self, g, now):
        if g[0] == 'room':
            MOD.moderate(self, g[3].get('userId', ''), g[2], channel_name(g[1]), now, g[3].get('role') or 'chatter')
        from . import clan_orders as CO
        if g[0] == 'room' and channel_name(g[1]) == 'clan' and CO.handle(self, 'clan', g[2], g[3], self.listeners('clan', g[3]), now):
            return                                       # clan order (focus, go, come, defend, take, ship, build, stop)
        if g[0] == 'whisper' and CO.handle(self, 'whisper', g[2], g[3], [g[1]], now):
            return
        if AW.handle(self, g, now):                        # the manager's warning or greeting (bot/admin_warnings.py)
            return
        if self.llm is not None and self.llm.chat(self, g, now):
            return
        if g[0] == 'whisper':
            self.template_whisper(g[1], g[2], g[3], now)
        else:
            self.template_room(g[1], g[2], g[3], now)

    def listeners(self, channel, who):
        fac = int(who.get('factionId') or 0)
        out = [b for b in self.bots if b.online and b.dead_until <= self.now]
        if channel == 'company':
            out = [b for b in out if b.company == fac]
        elif channel == 'clan':
            out = [b for b in out if b.profile is not None and who.get('clanTag') and b.profile.d['pilot'].get('clanTag') == who['clanTag']]
        elif channel == 'group':
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
            b.memory.event(name, 'chat', now)
            if kind in IX.INTENTS and kind != 'assist':
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
            elif kind == 'insult':
                b.memory.event(name, 'insult', now)
                if b.r.random() < b.o('aggression') * RUDE_FACTOR[self.rude()]:
                    self.speak(b, channel, SPC.template(b, self.banter(b, 'reply_insult'), name=name), now=now)
            elif kind == 'assist':
                self.help_call(name, who, game_map, [b], channel, now)
            elif b.r.random() < 0.85:
                self.speak(b, channel, SPC.template(b, {'greeting': 'reply_greeting', 'thanks': 'thanks'}.get(kind, 'reply_question'), name=name),
                           now=now)
        if mentioned:
            return
        if kind == 'assist' and game_map:
            self.help_call(name, who, game_map, listener, channel, now)
        elif kind in ('group', 'clan', 'quest', 'duel', 'special', 'gate'):
            for b in self.open_call(kind, name, who, game_map, msg, listener, now):
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
        elif kind == 'followup' and channel == 'group':              # in a group chat "follow me / come 2-4": the group's bots
            for b in listener[:3]:
                self.answer_request(b, kind, name, who, game_map, msg, channel, now)
        elif kind == 'greeting':
            for b in [b for b in listener if b.r.random() < 0.3 * b.o('sociability')][:2]:
                self.speak(b, channel, SPC.template(b, 'reply_greeting', name=name), now=now)
        elif kind == 'question' and listener:
            b = max(listener, key=lambda b: b.o('talkativeness') * b.r.random())
            if b.r.random() < 0.3 + 0.4 * b.o('helpfulness'):
                self.speak(b, channel, SPC.template(b, 'reply_question'), now=now)

    def help_call(self, name, who, game_map, candidates, channel, now, max_count=None, required=False, silent=False):
        """Call for help: some of the helpful bots from the same company that can enter and reach that map come -> those who come.
        required: the decision is someone else's, no probability roll; silent: no template reply is written (in Advanced mode the model says the reply)."""
        if not self.permission('assist'):
            return []
        fac = int(who.get('factionId') or 0)
        ids = {v: k for k, v in H.NAMES.items()}
        m = ids.get(game_map) if game_map else None
        if m is None:
            # map not written: the player's map, but only if really under attack (took damage in the last 90 s); otherwise
            # "help" has another meaning ("help me with quest", a joke) and nobody rushes to the fight (player report 2026-10-30)
            import community as TP
            k = TP.find(name=name)
            w = k.world if k is not None else None
            m = int(k.profile.d['position'].get('mapId', 0)) if w is not None and now - getattr(w, 'last_hurt', 0) < 90 else None
        if m is None or int(m) not in K.MAPS:
            return []
        incoming = []
        for b in sorted(candidates, key=lambda b: -b.o('helpfulness') * b.r.uniform(0.6, 1.4)):
            if len(incoming) >= (max_count or self.setting('help_max', 3)):
                break
            if b.company != fac or not K.can_enter(m, b.company, b.level) or not K.route(b.game_map, m, b.company, b.level):
                continue
            p = 0.15 + 0.6 * b.o('helpfulness') + 0.5 * b.memory.relation(name, now) - 0.3 * b.mood['fatigue']
            if b.target is not None and b.target.name in ('quest', 'group'):
                p -= 0.2
            if required or b.r.random() < p:
                incoming.append(b)
                B.force(b, 'assist', plan={'map': int(m), 'name': name}, pay=1.2, duration=900, now=now)
                b.memory.event(name, 'i_helped', now)
                if not required and not silent:
                    self.speak(b, channel, SPC.template(b, 'going_to_help', map=H.name(m)), now=now)
        return incoming

    def open_call(self, kind, name, who, game_map, msg, listener, now):
        """A request addressed to no one ("shall we group", "anyone recruiting for a clan"): the bots that will reply. Group: social bots from the
        same company think in turn, the first one that accepts (as in a real chat one person says "inv"). Clan: at most two bots from the
        same company that have a clan (leader first)."""
        fac = int(who.get('factionId') or 0)
        if kind == 'duel':                               # a challenge is accepted by someone from another company
            for b in sorted([b for b in listener if b.company != fac], key=lambda b: -b.o('aggression') * b.r.uniform(0.5, 1.5))[:4]:
                k = IX.decision(self, b, 'duel', name, who, game_map, msg, now)
                if k and k['accept']:
                    b._request_decision = k
                    return [b]
            return []
        candidate = [b for b in listener if not fac or b.company == fac]
        if kind == 'gate':                                 # gate filler: the requested number (3 if none) who accept
            import re
            m = re.search(r'\b([1-7])\b', msg or '')
            n, out = int(m.group(1)) if m else 3, []
            for b in sorted(candidate, key=lambda b: -(b.o('sociability') + b.o('ambition')) * b.r.uniform(0.5, 1.5))[:12]:
                k = IX.decision(self, b, 'gate', name, who, game_map, msg, now)
                if k and k['accept']:
                    b._request_decision = k
                    out.append(b)
                    if len(out) >= n:
                        break
            return out
        if kind in ('group', 'quest', 'special'):
            for b in sorted(candidate, key=lambda b: -b.o('sociability') * b.r.uniform(0.5, 1.5))[:4]:
                k = IX.decision(self, b, kind, name, who, game_map, msg, now)
                if k and k['accept']:
                    b._request_decision = k
                    return [b]
            return []
        import clan as KL
        from . import society
        clan_bots = [b for b in candidate if KL.clan_of(society.profile(b)) is not None]
        return sorted(clan_bots, key=lambda b: (KL.clan_of(b.profile)['leader'] != b.name.lower(), -b.o('talkativeness')))[:2]

    def answer_request(self, b, kind, name, who, game_map, msg, channel, now):
        """Normal mode: apply the decision (interaction), say it with a template."""
        k = b.__dict__.pop('_request_decision', None) or IX.decision(self, b, kind, name, who, game_map, msg, now)
        if k is None:
            return
        text = SPC.template(b, k['template'][0], **k['template'][1]) if k.get('template') else None
        IX.apply(self, b, k, delay=SPC.typing_time(text or 'ok', b) + b.r.uniform(1, 3))
        if text:
            if k.get('whisper'):
                channel = 'whisper'                             # "pm me": the reply goes by whisper
            self.speak(b, channel, text, recipient=name if channel == 'whisper' else None, now=now)

    def template_whisper(self, b, msg, who, now):
        name = who.get('userId', '')
        kind, game_map = SPC.intent(msg)
        kind = IX.offer_reply(b, name, msg, now) or kind       # "shall we group?" -> "sure": group request
        b.memory.event(name, 'chat', now)
        if kind in IX.INTENTS and kind != 'assist':
            self.answer_request(b, kind, name, who, game_map, msg, 'whisper', now)
        elif kind == 'assist':
            if self.help_call(name, who, game_map, [b], 'company', now):
                self.outgoing = [x for x in self.outgoing if not (x[1] is b and x[2] == 'company')]
                self.speak(b, 'whisper', SPC.template(b, 'reply_yes'), recipient=name, now=now)
            else:
                self.speak(b, 'whisper', SPC.template(b, 'reply_no'), recipient=name, now=now)
        elif kind == 'insult':
            b.memory.event(name, 'insult', now)
            if b.r.random() < 0.6 * RUDE_FACTOR[self.rude()]:
                self.speak(b, 'whisper', SPC.template(b, self.banter(b, 'reply_insult'), name=name), recipient=name, now=now)
        else:
            self.speak(b, 'whisper', SPC.template(b, {'greeting': 'reply_greeting', 'thanks': 'thanks'}.get(kind, 'reply_question'), name=name),
                       recipient=name, now=now)

    def event_tick(self, now):
        """The bots' new events turn into chat (level, new ship, PvP); in Advanced mode they also go into the LLM's context."""
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
        talk = b.o('talkativeness')
        kind = o['type']
        if kind == 'witness':
            if o.get('sub') == 'boss' and o.get('who') and str(o['who']).lower() != b.name.lower():
                self.speak(b, 'company', SPC.template(b, 'witness_boss', who=o['who']), now=now + b.r.uniform(2, 8))
            elif o.get('sub') == 'player_died' and o.get('name'):
                self.speak(b, 'company', SPC.template(b, 'witness_death', name=o['name']), now=now + b.r.uniform(2, 10))
            return
        if kind == 'diplomacy' and (o.get('accept') or not o.get('incoming')) and o.get('form') in (0, 1, 3) and b.r.random() < 0.4 + 0.5 * talk:
            state = {0: 'peace', 1: 'alliance', 3: 'war_declared'}[o['form']]
            if o['form'] == 0 and not o.get('incoming'):
                return                                   # peace request: not announced until accepted
            self.speak(b, 'global' if o['form'] == 3 else 'company',
                       SPC.template(b, state, clan=o.get('clan', ''), tag=o.get('tag') or o.get('clan', '')), now=now + b.r.uniform(5, 30))
            return
        if kind == 'i_killed_boss' and b.r.random() < 0.3 * talk:
            self.speak(b, 'company', SPC.template(b, 'i_killed_boss'), now=now + b.r.uniform(2, 8))
            return
        if kind == 'level' and b.r.random() < 0.25 * talk:
            self.speak(b, 'company', SPC.template(b, 'level', level=o.get('level')), now=now)
        elif kind == 'new_ship' and b.r.random() < 0.45 * talk:
            self.speak(b, 'global', SPC.template(b, 'new_ship', ship=str(o.get('item', '')).replace('ship_', '').title()), now=now)
        elif kind in ('death', 'i_killed_player') and now - self.__dict__.setdefault('_last_whisper', {}).get(
                str(o.get('killer') or o.get('name') or '').lower(), 0) < 60:
            pass                                         # at most one whisper per minute to the same player (so consecutive kills do not rain whispers)
        elif kind == 'death' and o.get('killer') and str(o['killer']).lower() not in self.name_index and b.r.random() < 0.2 + 0.5 * talk:
            self._last_whisper[str(o['killer']).lower()] = now
            rude = self.rude()
            angry = rude and b.mood['anger'] > 0.55 - 0.1 * rude and b.o('aggression') > 0.6 - 0.1 * rude
            self.speak(b, 'whisper', SPC.template(b, 'died_angry' if angry else 'died'), recipient=o['killer'], now=now)
        elif kind == 'i_killed_player' and b.r.random() < 0.25 + 0.3 * talk:
            self.__dict__.setdefault('_last_whisper', {})[str(o.get('name') or '').lower()] = now
            rude = self.rude()
            self.speak(b, 'whisper', SPC.template(b, 'i_killed') if rude else 'gg', recipient=o.get('name'), now=now)
            if rude >= 2 and o.get('name') and b.r.random() < 0.25 * (rude - 1) * b.o('aggression'):
                self.speak(b, 'global', SPC.template(b, 'banter_kill', name=o['name'], map=H.name(b.game_map)), now=now + b.r.uniform(4, 15))
        elif kind == 'clan_founded' and self.can_recruit(o.get('name'), now):
            self.speak(b, 'global', SPC.template(b, 'clan_recruit', tag=o.get('tag'), clan=o.get('name'), level=max(3, b.level - 4)),
                       now=now + b.r.uniform(20, 120))

    def online_humans(self):
        """Online human players (community.Person; except the pack's bots)."""
        import community as TP
        try:
            return [k for k in TP.all_().values() if k.session is not None and k.name.lower() not in self.name_index]
        except Exception:
            return []

    def start_private(self, now):
        """A friend bot whispers to the player spontaneously: a greeting on login, now and then a group offer or small talk (at most once per
        12 minutes per player; only bots of the same company with a good relationship to them). A positive reply to a group offer becomes an invite (offer)."""
        if not self.permission('chat'):
            return
        seen = self.__dict__.setdefault('human_first', {})
        last = self.__dict__.setdefault('human_whisper', {})
        for k in self.online_humans():
            a = k.name.lower()
            first = seen.setdefault(a, now)
            if now - last.get(a, 0) < 720 or now - first < 20:
                continue
            fac = int(k.profile.d['pilot'].get('factionId', 0))
            friendly = [b for b in self.bots if b.online and b.dead_until <= now and b.company == fac and b.memory.relation(k.name, now) >= 0.3]
            if not friendly:
                continue
            b = max(friendly, key=lambda b: b.memory.relation(k.name, now) * b.r.uniform(0.6, 1.4))
            if now - first < 300 and not last.get(a):
                purpose = 'private_greeting'                          # new entry
            elif b.r.random() > 0.35 * (0.5 + b.o('sociability')):
                last[a] = now - 360                           # does not write this time (checks again after half an interval)
                continue
            elif self.permission('group') and b.target is not None and b.target.name in ('grinding', 'quest') and b.r.random() < 0.6:
                purpose = 'private_group'
            else:
                purpose = 'private_chat'
            last[a] = now
            if purpose == 'private_group':
                IX.make_offer(b, 'group', k.name, now)
            if self.llm is not None and self.llm.ready and self.llm.special(self, b, k.name, purpose):
                continue
            self.speak(b, 'whisper', SPC.template(b, purpose, name=k.name, map=H.name(b.game_map)), recipient=k.name, now=now + b.r.uniform(2, 10))

    def group_banter_line(self, now):
        """A bot in a group with a human now and then writes to the group chat (where are we going, nice kill ...): once every 4-8 minutes."""
        if not self.permission('chat'):
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
                continue                                     # the group was just formed: not the first word right away
            b = max(members, key=lambda b: b.o('talkativeness') * b.r.random())
            if self.llm is not None and self.llm.ready and self.llm.group_banter_line(self, b, k.name):
                continue
            self.speak(b, 'group', SPC.template(b, 'group_banter'), now=now)

    def rude(self):
        return int(self.setting('rude_chat', 1) or 0)

    def banter(self, b, state):
        """A bot with a harsh aggression level answers an insult harshly."""
        return 'banter_harsh' if self.rude() >= 2 and b.o('aggression') > 0.5 and not b.__dict__.get('moderator') else state

    def throw_banter(self, now):
        """Bots with harsh and very harsh aggression level taunt another company or an online enemy player in global (grudge holders first)."""
        rude = self.rude()
        if rude < 2 or random.random() > 0.05 * (rude - 1):
            return
        is_open = [b for b in self.bots if b.online and b.dead_until <= now and b.o('aggression') > 0.55
                and not b.__dict__.get('moderator')]
        if not is_open:
            return
        b = max(is_open, key=lambda b: b.o('aggression') * b.r.random())
        enemy = [k for k in self.online_humans() if int(k.profile.d['pilot'].get('factionId', 0)) != b.company]
        grudge = [k for k in enemy if b.memory.relation(k.name, now) < -0.2]
        if (grudge or enemy) and b.r.random() < (0.8 if grudge else 0.3 * (rude - 1)):
            k = b.r.choice(grudge or enemy)
            self.speak(b, 'global', SPC.template(b, 'banter_player', name=k.name, map=H.name(b.game_map)), now=now)
        else:
            self.speak(b, 'global', SPC.template(b, 'banter_company', company=b.r.choice([f for f in ('MMO', 'EIC', 'VRU') if f != COMPANY[b.company]])),
                       now=now)

    def can_recruit(self, clan, now):
        """Can a clan recruitment ad be written (at most one per clan in two hours, one in 25 minutes across all); if so, it counts."""
        if now - self._last_recruit.get(None, -1e9) < RECRUIT_ANY_SEC or now - self._last_recruit.get(clan, -1e9) < RECRUIT_CLAN_SEC:
            return False
        self._last_recruit[None] = self._last_recruit[clan] = now
        return True

    def new_text(self, b, state, now, **f):
        """A line from the state's templates not written in the last 45 minutes (None if not found in 4 tries)."""
        self._last_text = [x for x in self._last_text if now - x[0] < REPEAT_SEC]
        for _ in range(4):
            m = SPC.template(b, state, **f)
            if m and re.sub(r'\W+', '', m.lower()) not in (x[1] for x in self._last_text):
                return m
        return None

    def wrote(self, b, text, now):
        self._last_text.append((now, re.sub(r'\W+', '', text.lower())))
        b._last_word = now

    def status_line(self, b, now):
        """A line about something the bot actually did or just did (gate finished, shopping, death, quest, full cargo, grinding)
        -> (state, fields) or None. Level and new ship are already written in event_chat; the same event is not told twice."""
        told = b.__dict__.setdefault('_told', set())
        candidates = []
        for o in b.events[-12:]:
            if now - o['t'] > 900 or (o['type'], o['t']) in told:
                continue
            t = o['type']
            if t == 'gate_done':
                candidates.append(('status_gate', dict(gate=o['gate']), o))
            elif t == 'purchase' and not str(o.get('item', '')).startswith('ship_'):
                item = re.sub(r'^(drone|equipment|resource)_', '', str(o.get('item', ''))).replace('_', ' ')
                candidates.append(('status_purchase', dict(item=item), o))
            elif t == 'death' and o.get('reason') == 'npc':
                candidates.append(('status_death', dict(map=o.get('map', H.name(b.game_map))), o))
            elif t == 'quest_done' and o.get('name'):
                candidates.append(('status_quest', dict(name=o['name']), o))
            elif t == 'fled':
                candidates.append(('status_fled', dict(map=o.get('map', H.name(b.game_map))), o))
        try:
            if b.cargo_fill() > 0.85:
                candidates.append(('status_cargo', dict(percent=int(b.cargo_fill() * 100)), None))
        except Exception:
            pass
        if b.target is not None and b.target.name == 'grinding':
            candidates.append(('status_grind', dict(map=H.name(b.game_map)), None))
        npc = b.k['stats'].get('npc', 0)
        if npc >= 50:
            candidates.append(('status_stats', dict(npc=npc, death=b.k['stats'].get('death', 0)), None))
        if not candidates:
            return None
        d, f, o = b.r.choice(candidates)
        if o is not None:
            told.add((o['type'], o['t']))
            if len(told) > 60:
                told.clear()
        f.setdefault('map', H.name(b.game_map))
        f.setdefault('level', b.level)
        return d, f

    def start_dialog(self, b, is_open, channel, now):
        """b writes a question/remark; another online bot (same language, same company in a company channel) replies with a human delay, sometimes
        b answers back too (at most 3 lines). A reply may not come; the time each line goes out is added on top of the previous one."""
        chat = SPC.dialogue(b)
        if not chat:
            return False
        take = lambda x, kind: SPC.dialogue_line(x, kind, map=H.name(x.game_map), level=x.level)
        m = take(b, chat[0])
        if not m or re.sub(r'\W+', '', m.lower()) in (x[1] for x in self._last_text):
            return False
        t = self.speak(b, channel, m, now=now)
        if t is None:
            return False
        self.wrote(b, m, now)
        candidates = [c for c in is_open if c is not b and SPC.lang(c) == SPC.lang(b) and (channel == 'global' or c.company == b.company)]
        if not candidates:
            return True
        c = max(candidates, key=lambda x: x.o('sociability') * x.r.random())
        if b.r.random() > 0.3 + 0.55 * c.o('sociability'):
            return True                                  # nobody replied
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
        """Now and then a bot writes spontaneously: a line about what it did, short talk, looking for a group, trade, general remark, rarely a clan recruitment
        ad and complaints. Within the channel limit; the same line, the same bot and the same clan's ad are not repeated often."""
        if self.llm is not None and self.llm.ready:
            return                                   # in Advanced mode the model does the spontaneous chat (llm._bot_chat)
        is_open = [b for b in self.bots if b.online and b.dead_until <= now]
        if not is_open or random.random() > 0.065 * min(1.0, len(is_open) / 10.0):
            return
        available = [b for b in is_open if now - b.__dict__.get('_last_word', -1e9) >= BOT_GAP_SEC]
        if not available:
            return
        b = max(available, key=lambda b: b.o('talkativeness') * b.r.random())
        k = b.r.random()
        if b.k.get('clan') and b.archetype == 'leader' and k < 0.3:
            import clan as KL
            c = KL.CLANS.get(b.k['clan'])
            if c is not None and c['leader'] == b.name.lower() and self.can_recruit(b.k['clan'], now):
                m = self.new_text(b, 'clan_recruit', now, tag=c['tag'], clan=c['name'], level=max(3, b.level - 4))
                if m and self.speak(b, 'global', m, now=now) is not None:
                    self.wrote(b, m, now)
                    return
        if b.archetype == 'trader' and k < 0.4:
            m, channel = self.new_text(b, 'trade', now, item='LF-3'), 'global'
        elif b.o('sociability') > 0.6 and k < 0.35:
            m, channel = self.new_text(b, 'group_search', now, map=H.name(b.game_map)), 'company'
        else:
            channel, r = b.r.choice(('global', 'company')), b.r.random()
            m = None
            if r < 0.4:
                d = self.status_line(b, now)
                m = self.new_text(b, d[0], now, **d[1]) if d else None
            elif r < 0.75:
                if self.start_dialog(b, is_open, channel, now):
                    return
            elif r < 0.8 and now - self._last_complaint >= COMPLAINT_SEC:
                self._last_complaint = now
                m = self.new_text(b, 'complaint', now)
            if m is None:
                m = self.new_text(b, 'general', now)
        if m and self.speak(b, channel, m, now=now) is not None:
            self.wrote(b, m, now)
