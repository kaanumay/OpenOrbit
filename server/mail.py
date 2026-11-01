"""Mail, notes, contacts and blacklist (roadmap Stage 10): the client's messaging window (UIMail) from the profile.

Message types (the client's UIMailSystem.ReturnMailInfo; AbsUserMessageInfoCommand.type):
  10  player message     UserMessageInfoCommand: subject and text shown as they are
  20  clan message       UserMessageClanInfoCommand (clan tag)
  50  system             UserMessageSystemInfoCommand
  60  auction            UserMessageAuctionInfoCommand: msgType 1 "you were outbid", 2 "you won" (text in the client, with the item name)
  70  info               subject and text are a localization key (messaging_systemMessage_<n>_subject/_body), %PARAM<n>% replacements
Status: 1 unread, 3 read (when the client opens the message UserMessageUpdateStatusRequest status 3). A page is 15 messages (client startIndex =
(page - 1) * 15). The box id (boxId) arrives as a double in delete, status and attachment-claim requests.
Attachments (LootModule): items that come with the message; claimed with UserMessageLootRequest (the shop's reward path). The client (UIMailSystem.SetItemInfo,
SetMailItemsInfo) shows attachments only in an info (70) message; isReceived has three states: 0 sent, 1 received (Claim button), 2 attachments
claimed ("Claimed", button disabled). The gift icon in the list row is visible while isReceived > 0 (1 blue, 2 yellow): a message without attachments comes with
0 (live round 2, 2026-10-23; with 2 the yellow icon stayed, CANLI_TEST N5). UserMessageLootCommand has no handler in the client: on claiming the list is sent again (live attempt
2026-10-17). So a message with attachments is always added with the info type (add).
The recipient is the player themselves (like a note to self) or, on a friend server, the other players (community.py; if not connected, their record while it stays on the server):
the message goes to their inbox, and if connected the mail icon. The contact list is in contacts.py; the blacklist is stored in the profile.
"""
import time
import community as TP

NOTE_LIMIT = 10
NOTE_LIMIT_PREMIUM = 50       # official forum: 50 notes for Premium members (when the term ends the excess is not deleted, but no new ones can be added)
MAX_RECIPIENTS = 5               # official forum: at most 5 recipients at a time (anti-spam; no limit when sending to the clan)
BOX_LIMIT = 500          # per inbox and outbox (the same as the logbook and account history)
PAGE = 15
UNREAD, READ = 1, 3
USER, CLAN, SYSTEM, AUCTION, INFO = 10, 20, 50, 60, 70
# sending conditions (UserMessageGetTargetCommand in the record)
TARGETS = [(3, 'condition_level-seven-gap'), (4, 'condition_no-pay-user'), (5, 'condition_no-galaxy-gate'),
           (6, 'condition_premium-extension')]
REQUESTS = {'UserMessageInitRequest', 'UserMessageGetTargetRequest', 'UserMessageInboxListRequest', 'UserMessageOutboxListRequest',
            'UserMessageSendRequest', 'UserMessageDeleteRequest', 'UserMessageUpdateStatusRequest', 'UserMessageLootRequest',
            'UserMessageNoteListRequest', 'UserMessageNoteAddRequest', 'UserMessageNoteUpdateRequest', 'UserMessageNoteDeleteRequest',
            'BlackListGetRequest', 'BlackListAddRequest', 'BlackListDeleteRequest'}


def mod(_cls, **f):
    return dict(_=_cls, **f)


def stamp(t=None):
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(t))


def stack(key='empty', **args):
    from shop import stack_msg
    return stack_msg(key, **args)


class Mail:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log
        self.m = None                       # shop (attachments: reward path)
        with self.p.lock:
            d = self.p.d.setdefault('mailer', {})
            for k, v in (('order', 1), ('incoming', []), ('outgoing', []), ('notes', []), ('blacklist', [])):
                d.setdefault(k, v)
            # the Turkish "Yerel sunucu" greeting in old records (foreign players kept asking what it was) is deleted
            d['incoming'] = [r for r in d['incoming'] if not (r.get('sender') == 'DarkOrbit' and r.get('subject') == 'Yerel sunucu')]
        if not self.d.get('welcome'):
            self.d['welcome'] = True
            self.add(INFO, 'messaging_systemMessage_1_subject', 'messaging_systemMessage_1_body')

    @property
    def d(self):
        return self.p.d['mailer']

    # -------------------------------------------------------- message creation (other systems use it too)
    def add(self, kind, subject, body, sender='', sender_id=0, attachments=(), extra=None, inbox=True):
        """New message in the box -> record. extra: type-specific fields (auction: lootId, auctionType, amount, msgType, auctionId;
        clan: clanTag; info: degistirmeler)."""
        if attachments:
            kind = INFO                                # the client shows attachments only in an info message
        with self.p.lock:
            mid = self.d['order']
            self.d['order'] += 1
            rec = {'id': mid, 'type': kind, 'state': UNREAD if inbox else READ, 'date': stamp(), 'subject': subject,
                   'text': body, 'sender': sender, 'sender_id': sender_id, 'attachments': [list(a) for a in attachments],
                   'attachment_claimed': not attachments}
            if extra:
                rec.update(extra)
            box = self.d['incoming' if inbox else 'outgoing']
            box.insert(0, rec)
            if len(box) > BOX_LIMIT:             # system messages accumulate: the oldest are deleted, those with unclaimed attachments stay
                box[BOX_LIMIT:] = [r for r in box[BOX_LIMIT:] if not r.get('attachment_claimed', True)]
            self.p.dirty = True
        return rec

    def notify(self, rec):
        """New message notification (the mail icon in the menu)."""
        return ('UserMessageNewCommand', {'userMessageInfoCommand': self.info(rec, True), 'unreadCount': self.unread()})

    def unread(self):
        return sum(1 for r in self.d['incoming'] if r['state'] == UNREAD)

    def info(self, r, inbox):
        me = self.p.d['pilot']
        base = dict(senderId=int(r.get('sender_id', 0)), replacements=r.get('replacements', ''), insertDate=r['date'],
                    boxId=r['id'], parent=False, isReceived=(2 if r.get('attachment_claimed') else 1) if inbox and r.get('attachments') else 0,
                    messageId=r['id'], type=r['type'], subject=r['subject'], body=r['text'], status=r['state'],
                    attachments=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in r.get('attachments', [])])
        if r['type'] == AUCTION:
            return mod('UserMessageAuctionInfoCommand', **base, lootId=r.get('lootId', ''), auctionType=r.get('auctionType', ''),
                       amount=int(r.get('amount', 0)), msgType=int(r.get('msgType', 0)), auctionId=int(r.get('auctionId', 0)))
        if r['type'] == CLAN:
            return mod('UserMessageClanInfoCommand', **base, clanTag=r.get('clanTag', ''), parentMessage=None,
                       senderName=r.get('sender', ''))
        if r['type'] == SYSTEM:
            return mod('UserMessageSystemInfoCommand', **base, strs=list(r.get('strs', [])))
        if r['type'] == INFO:
            return mod('UserMessageInfoInfoCommand', **base)
        names = r.get('recipients') or ([me.get('userName', '')] if inbox else [])
        return mod('UserMessageInfoCommand', **base, bodyParams='', recipientIds=list(r.get('recipient_ids', [])), title='',
                   bodyInc='', recipients=names, parentMessage=None, senderAvatar='', versionType=0, subjectInc='',
                   subjectParams='', senderName=r.get('sender', ''))

    # -------------------------------------------------------- requests
    def init_cmd(self):
        return ('UserMessageInitCommand', {'unreadCount': self.unread(), 'outboxCount': len(self.d['outgoing']),
                                           'inboxCount': len(self.d['incoming']), 'noteLimit': self.note_limit()})

    def box(self, inbox, start):
        start = max(0, int(start or 0))
        rows = self.d['incoming' if inbox else 'outgoing'][start:start + PAGE]
        name = 'UserMessageInboxListCommand' if inbox else 'UserMessageOutboxListCommand'
        return (name, {'userMessageInfoCommandList': [self.info(r, inbox) for r in rows], 'startIndex': start})

    def find(self, inbox, ids):
        want = {int(i) for i in ids or []}
        return [r for r in self.d['incoming' if inbox else 'outgoing'] if r['id'] in want]

    def handle(self, name, f):
        if name == 'UserMessageInitRequest':
            return [self.init_cmd()]
        if name == 'UserMessageGetTargetRequest':
            return [('UserMessageGetTargetCommand', {'commandList': [mod('UserMessageTargetInfoCommand', id=i, message=m, used=True)
                                                                     for i, m in TARGETS]})]
        if name == 'UserMessageInboxListRequest':
            return [self.box(True, f.get('startIndex'))]
        if name == 'UserMessageOutboxListRequest':
            return [self.box(False, f.get('startIndex'))]
        if name == 'UserMessageSendRequest':
            return self.send(f)
        if name == 'UserMessageDeleteRequest':
            return self.delete(bool(f.get('inbox')), f.get('deleteIds') or [])
        if name == 'UserMessageUpdateStatusRequest':
            return self.status(bool(f.get('inbox')), int(f.get('status') or READ), f.get('ids') or [])
        if name == 'UserMessageLootRequest':
            return self.loot(f.get('ids') or [])
        if name.startswith('UserMessageNote'):
            return self.notes(name, f)
        if name.startswith('BlackList'):
            return self.blacklist(name, f)
        return []

    def send(self, f):
        me = self.p.d['pilot']
        names = [str(n).strip() for n in f.get('recipients') or [] if str(n).strip()]
        subject, body = str(f.get('subject', '')).strip(), str(f.get('body', ''))
        reply = lambda ok, key, info=None: [('UserMessageSendCommand', {
            'textCommand': stack(key + '_text'), 'success': ok, 'messageInfoCommand': info,
            'titleCommand': stack(key + '_title'), 'captchaStatus': 0})]
        if f.get('recipientType') == 'clan':                   # the clan's members on the server (those whose offline record is not loaded are skipped)
            import clan as KL
            k = KL.clan_of(self.p)
            names = [u['name'] for a, u in k['members'].items() if a == KL.name(self.p) or TP.find(name=a) is not None] if k else []
        if not names:
            return reply(False, 'messaging_errorLayer_noRecipient')
        if f.get('recipientType') != 'clan' and len(names) > MAX_RECIPIENTS:
            return reply(False, 'messaging_errorLayer_tooManyRecipients')
        if len(subject) < 3:
            return reply(False, 'messaging_errorLayer_subjectTooShort')
        if len(subject) > 50:
            return reply(False, 'messaging_errorLayer_subjectTooLong')
        if len(body.strip()) < 5:
            return reply(False, 'messaging_errorLayer_bodyTooShort')
        if len(body) > 5000:
            return reply(False, 'messaging_errorLayer_bodyTooLong')
        own = me.get('userName', '')
        recipients = [None if n.lower() == own.lower() else TP.find(name=n) for n in names]     # the other players on a friend server
        if any(n.lower() != own.lower() and k is None for n, k in zip(names, recipients)):
            self.log('   mail: no recipient: %s' % names)
            return reply(False, 'messaging_errorLayer_noRecipient')
        clan = f.get('recipientType') == 'clan'
        for k in recipients:                                     # the recipient's blacklist or a block in the contact list (forum: blacklist)
            if k is None:
                continue
            if any(int(x.get('id', 0)) == self.p.user_id for x in (k.profile.d.get('mailer') or {}).get('blacklist', ())):
                return reply(False, 'messaging_errorLayer_blacklisted')
            blocked = (k.profile.d.get('contacts') or {}).get('blocked') or []
            if any(own.lower() == str(x.get('name', x) if isinstance(x, dict) else x).lower() for x in blocked):
                return reply(False, 'messaging_errorLayer_blocked')
        extra = {'recipients': [k.name if k else own for k in recipients], 'recipient_ids': [k.uid if k else self.p.user_id for k in recipients]}
        if clan:
            extra['clanTag'] = me.get('clanTag', '')
        sent = self.add(CLAN if clan else USER, subject[:50], body[:5000], sender=own, sender_id=self.p.user_id, extra=extra,
                        inbox=False)
        out = reply(True, 'messaging_successLayer_messageSent', self.info(sent, False))
        for k in {(k.uid if k else 0): k for k in recipients}.values():
            box = self if k is None else getattr(getattr(k.session, 'social', None), 'mailer', None) or Mail(k.profile, self.log)
            got = box.add(CLAN if clan else USER, subject[:50], body[:5000], sender=own, sender_id=self.p.user_id, extra=extra)
            if k is None:
                out.append(self.notify(got))
            else:
                k.send([box.notify(got)], 'mail: %s' % own)        # the mail icon if connected
        self.log('   mail sent: %s -> %s' % (subject[:50], extra['recipients']))
        return out

    def delete(self, inbox, ids):
        drop = {r['id'] for r in self.find(inbox, ids)}
        with self.p.lock:
            box = 'incoming' if inbox else 'outgoing'
            self.d[box] = [r for r in self.d[box] if r['id'] not in drop]
            self.p.dirty = True
        # messageInfoCommands: after a deletion the client rebuilds the list from these (UserMessageDeleteEventHandler.Run ->
        # CreateMailItem); when sent empty the list went empty (live attempt 2026-10-17). The box's first page.
        return [('UserMessageDeleteCommand', {'inbox': inbox, 'count': len(self.d['incoming' if inbox else 'outgoing']),
                                              'textCommand': stack(), 'titleCommand': stack(), 'deleteIds': sorted(drop),
                                              'unreadCount': self.unread(), 'success': bool(drop),
                                              'messageInfoCommands': self.box(inbox, 0)[1]['userMessageInfoCommandList']})]

    def status(self, inbox, st, ids):
        rows = self.find(inbox, ids)
        with self.p.lock:
            for r in rows:
                r['state'] = st
            self.p.dirty = True
        return [('UserMessageUpdateStatusCommand', {'unreadCount': self.unread(), 'textCommand': stack(), 'status': st,
                                                    'ids': [r['id'] for r in rows], 'inbox': inbox, 'success': bool(rows),
                                                    'titleCommand': stack(), 'count': len(rows)})]

    def loot(self, ids):
        msgs, done = [], []
        for r in self.find(True, ids):
            if r.get('attachment_claimed'):
                continue
            with self.p.lock:
                r['attachment_claimed'] = True
                self.p.dirty = True
            for loot, n in r.get('attachments', []):
                msgs += self.m.reward(loot, int(n)) if self.m else []
            done.append(r['id'])
            self.log('   mail attachments claimed: %s %s' % (r['subject'], r.get('attachments')))
        page = []
        if done:                                       # the client does not process the Loot response: the message's page so that "Claimed" shows
            pos = next(i for i, r in enumerate(self.d['incoming']) if r['id'] == done[0])
            page = [self.box(True, pos // PAGE * PAGE)]
        return [('UserMessageLootCommand', {'ids': done})] + msgs + page

    # -------------------------------------------------------- notlar
    def note_cmd(self, n):
        return mod('UserMessageNoteInfoCommand', insertDate=n['date'], noteId=n['id'], body=n['text'], subject=n['subject'])

    def notes(self, name, f):
        notes = self.d['notes']
        lst = lambda: [self.note_cmd(n) for n in notes]
        if name == 'UserMessageNoteListRequest':
            return [('UserMessageNoteListCommand', {'noteInfoCommandList': lst()})]
        if name == 'UserMessageNoteAddRequest':
            if len(notes) >= self.note_limit():
                return [('UserMessageNoteAddCommand', {'commandList': lst(), 'titleCommand': stack('messaging_errorLayer_notesLimitReached_title'),
                                                       'success': False,
                                                       'textCommand': stack('messaging_errorLayer_notesLimitReached_text', _notesLimit_=self.note_limit())})]
            with self.p.lock:
                nid = self.d['order']
                self.d['order'] += 1
                notes.insert(0, {'id': nid, 'date': stamp(), 'subject': str(f.get('subject', ''))[:50],
                                 'text': str(f.get('body', ''))[:5000]})
                self.p.dirty = True
            return [('UserMessageNoteAddCommand', {'commandList': lst(), 'titleCommand': stack(), 'success': True,
                                                   'textCommand': stack()})]
        nid = int(f.get('noteId') or 0)
        n = next((x for x in notes if x['id'] == nid), None)
        if name == 'UserMessageNoteUpdateRequest':
            if n:
                with self.p.lock:
                    n.update(subject=str(f.get('subject', ''))[:50], text=str(f.get('body', ''))[:5000], date=stamp())
                    self.p.dirty = True
            return [('UserMessageNoteUpdateCommand', {'textCommand': stack(), 'titleCommand': stack(), 'noteInfoCommandList': lst(),
                                                      'success': bool(n)})]
        if name == 'UserMessageNoteDeleteRequest':
            if n:
                with self.p.lock:
                    notes.remove(n)
                    self.p.dirty = True
            return [('UserMessageNoteDeleteCommand', {'noteId': nid, 'commandList': lst(), 'success': bool(n), 'textCommand': stack(),
                                                      'titleCommand': stack()})]
        return []

    # -------------------------------------------------------- blacklist
    def note_limit(self):
        return NOTE_LIMIT_PREMIUM if self.p.premium else NOTE_LIMIT

    def blacklist(self, name, f):
        bl = self.d['blacklist']
        uid = int(f.get('blackUserId') or 0)
        ids = lambda: [x['id'] for x in bl]
        names = lambda: [x['name'] for x in bl]
        if name == 'BlackListGetRequest':
            return [('BlackListGetCommand', {'blackList': ids(), 'blackNameList': names()})]
        ok = False
        with self.p.lock:
            if name == 'BlackListAddRequest' and uid and uid != self.p.user_id and uid not in ids():
                bl.append({'id': uid, 'name': str(uid)})
                ok = True
            elif name == 'BlackListDeleteRequest' and uid in ids():
                bl[:] = [x for x in bl if x['id'] != uid]
                ok = True
            self.p.dirty = True
        cmd = 'BlackListAddCommand' if name == 'BlackListAddRequest' else 'BlackListDeleteCommand'
        return [(cmd, {'textCommand': stack(), 'titleCommand': stack(), 'success': ok, 'blackList': ids(),
                       'blackNameList': names(), 'blackUserId': uid})]
