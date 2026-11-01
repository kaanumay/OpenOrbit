"""Posta, notlar, rehber ve kara liste (yol haritası Aşama 10): istemcinin mesajlaşma penceresi (UIMail) profilden.

Mesaj türleri (istemcinin UIMailSystem.ReturnMailInfo'su; AbsUserMessageInfoCommand.type):
  10  oyuncu mesajı      UserMessageInfoCommand: konu ve metin olduğu gibi gösterilir
  20  klan mesajı        UserMessageClanInfoCommand (klan etiketi)
  50  sistem             UserMessageSystemInfoCommand
  60  müzayede           UserMessageAuctionInfoCommand: msgType 1 "geçildin", 2 "kazandın" (metin istemcide, eşya adıyla)
  70  bilgi              konu ve metin yerelleştirme anahtarı (messaging_systemMessage_<n>_subject/_body), %PARAM<n>% değiştirmeleri
Durum: 1 okunmadı, 3 okundu (istemci mesajı açınca UserMessageUpdateStatusRequest status 3). Sayfa 15 mesaj (istemci startIndex =
(sayfa - 1) * 15). Kutu kimliği (boxId) silme, durum ve ek alma isteklerinde double gelir.
Ekler (LootModule): mesajla gelen eşyalar; UserMessageLootRequest ile alınır (mağazanın ödül yolu). İstemci (UIMailSystem.SetItemInfo,
SetMailItemsInfo) ekleri yalnız bilgi (70) mesajında gösterir; isReceived üç durumlu: 0 gönderilen, 1 alınan (Claim düğmesi), 2 ekleri
alınmış ("Claimed", düğme kapalı). Liste satırındaki hediye simgesi isReceived > 0 iken görünür (1 mavi, 2 sarı): eksiz gelen mesaj
0 (canlı tur 2, 2026-10-23; 2'de sarı simge kalıyordu, CANLI_TEST N5). UserMessageLootCommand'ın istemcide işleyicisi yok: alınca liste yeniden gönderilir (canlı deneme
2026-10-17). Ekli mesaj bu yüzden hep bilgi türüyle eklenir (add).
Alıcı oyuncunun kendisi (kendine not gibi) ya da arkadaş sunucusunda öteki oyuncular (community.py; bağlı değilse kaydı sunucuda
durdukça): mesaj onun gelen kutusuna, bağlıysa mektup simgesi. Rehber contacts.py'de; kara liste profilde saklanır.
"""
import time
import community as TP

NOTE_LIMIT = 10
NOTE_LIMIT_PREMIUM = 50       # resmî forum: Premium üyelerde 50 not (süre bitince fazlası silinmez, yenisi eklenemez)
MAX_RECIPIENTS = 5               # resmî forum: tek seferde en çok 5 alıcı (spam önlemi; klana gönderimde sınır yok)
BOX_LIMIT = 500          # gelen ve giden kutusu başına (seyir defteri ve hesap geçmişiyle aynı)
PAGE = 15
UNREAD, READ = 1, 3
USER, CLAN, SYSTEM, AUCTION, INFO = 10, 20, 50, 60, 70
# gönderme koşulları (kayıttaki UserMessageGetTargetCommand)
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
        self.m = None                       # mağaza (ekler: ödül yolu)
        with self.p.lock:
            d = self.p.d.setdefault('posta', {})
            for k, v in (('sira', 1), ('gelen', []), ('giden', []), ('notlar', []), ('kara_liste', [])):
                d.setdefault(k, v)
            # eski kayıtlardaki Türkçe "Yerel sunucu" karşılaması (yabancı oyuncular ne olduğunu soruyordu) silinir
            d['gelen'] = [r for r in d['gelen'] if not (r.get('sender') == 'DarkOrbit' and r.get('konu') == 'Yerel sunucu')]
        if not self.d.get('welcome'):
            self.d['welcome'] = True
            self.add(INFO, 'messaging_systemMessage_1_subject', 'messaging_systemMessage_1_body')

    @property
    def d(self):
        return self.p.d['posta']

    # -------------------------------------------------------- mesaj üretme (öbür sistemler de kullanır)
    def add(self, kind, subject, body, sender='', sender_id=0, attachments=(), extra=None, inbox=True):
        """Kutuya yeni mesaj -> kayıt. extra: türe özgü alanlar (müzayede: lootId, auctionType, amount, msgType, auctionId;
        klan: clanTag; bilgi: degistirmeler)."""
        if attachments:
            kind = INFO                                # istemci ekleri yalnız bilgi mesajında gösterir
        with self.p.lock:
            mid = self.d['sira']
            self.d['sira'] += 1
            rec = {'id': mid, 'tur': kind, 'durum': UNREAD if inbox else READ, 'tarih': stamp(), 'konu': subject,
                   'metin': body, 'sender': sender, 'sender_id': sender_id, 'attachments': [list(a) for a in attachments],
                   'attachment_claimed': not attachments}
            if extra:
                rec.update(extra)
            box = self.d['gelen' if inbox else 'giden']
            box.insert(0, rec)
            if len(box) > BOX_LIMIT:             # sistem iletileri birikir: en eskiler silinir, eki alınmamışlar kalır
                box[BOX_LIMIT:] = [r for r in box[BOX_LIMIT:] if not r.get('attachment_claimed', True)]
            self.p.dirty = True
        return rec

    def notify(self, rec):
        """Yeni mesaj bildirimi (menüdeki mektup simgesi)."""
        return ('UserMessageNewCommand', {'userMessageInfoCommand': self.info(rec, True), 'unreadCount': self.unread()})

    def unread(self):
        return sum(1 for r in self.d['gelen'] if r['durum'] == UNREAD)

    def info(self, r, inbox):
        me = self.p.d['pilot']
        base = dict(senderId=int(r.get('sender_id', 0)), replacements=r.get('replacements', ''), insertDate=r['tarih'],
                    boxId=r['id'], parent=False, isReceived=(2 if r.get('attachment_claimed') else 1) if inbox and r.get('attachments') else 0,
                    messageId=r['id'], type=r['tur'], subject=r['konu'], body=r['metin'], status=r['durum'],
                    attachments=[mod('LootModule', lootId=l, amount=n, modifier='') for l, n in r.get('attachments', [])])
        if r['tur'] == AUCTION:
            return mod('UserMessageAuctionInfoCommand', **base, lootId=r.get('lootId', ''), auctionType=r.get('auctionType', ''),
                       amount=int(r.get('amount', 0)), msgType=int(r.get('msgType', 0)), auctionId=int(r.get('auctionId', 0)))
        if r['tur'] == CLAN:
            return mod('UserMessageClanInfoCommand', **base, clanTag=r.get('clanTag', ''), parentMessage=None,
                       senderName=r.get('sender', ''))
        if r['tur'] == SYSTEM:
            return mod('UserMessageSystemInfoCommand', **base, strs=list(r.get('strs', [])))
        if r['tur'] == INFO:
            return mod('UserMessageInfoInfoCommand', **base)
        names = r.get('recipients') or ([me.get('userName', '')] if inbox else [])
        return mod('UserMessageInfoCommand', **base, bodyParams='', recipientIds=list(r.get('recipient_ids', [])), title='',
                   bodyInc='', recipients=names, parentMessage=None, senderAvatar='', versionType=0, subjectInc='',
                   subjectParams='', senderName=r.get('sender', ''))

    # -------------------------------------------------------- istekler
    def init_cmd(self):
        return ('UserMessageInitCommand', {'unreadCount': self.unread(), 'outboxCount': len(self.d['giden']),
                                           'inboxCount': len(self.d['gelen']), 'noteLimit': self.note_limit()})

    def box(self, inbox, start):
        start = max(0, int(start or 0))
        rows = self.d['gelen' if inbox else 'giden'][start:start + PAGE]
        name = 'UserMessageInboxListCommand' if inbox else 'UserMessageOutboxListCommand'
        return (name, {'userMessageInfoCommandList': [self.info(r, inbox) for r in rows], 'startIndex': start})

    def find(self, inbox, ids):
        want = {int(i) for i in ids or []}
        return [r for r in self.d['gelen' if inbox else 'giden'] if r['id'] in want]

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
        if f.get('recipientType') == 'clan':                   # klanın sunucudaki üyeleri (çevrimdışı kaydı yüklü olmayan atlanır)
            import clan as KL
            k = KL.clan_of(self.p)
            names = [u['ad'] for a, u in k['uyeler'].items() if a == KL.name(self.p) or TP.find(name=a) is not None] if k else []
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
        recipients = [None if n.lower() == own.lower() else TP.find(name=n) for n in names]     # arkadaş sunucusunda öteki oyuncular
        if any(n.lower() != own.lower() and k is None for n, k in zip(names, recipients)):
            self.log('   posta: alıcı yok: %s' % names)
            return reply(False, 'messaging_errorLayer_noRecipient')
        clan = f.get('recipientType') == 'clan'
        for k in recipients:                                     # alıcının kara listesi ya da rehberde engeli (forum: kara liste)
            if k is None:
                continue
            if any(int(x.get('id', 0)) == self.p.user_id for x in (k.profile.d.get('posta') or {}).get('kara_liste', ())):
                return reply(False, 'messaging_errorLayer_blacklisted')
            blocked = (k.profile.d.get('rehber') or {}).get('engelli') or []
            if any(own.lower() == str(x.get('ad', x) if isinstance(x, dict) else x).lower() for x in blocked):
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
                k.send([box.notify(got)], 'posta: %s' % own)        # bağlıysa mektup simgesi
        self.log('   posta gönderildi: %s -> %s' % (subject[:50], extra['recipients']))
        return out

    def delete(self, inbox, ids):
        drop = {r['id'] for r in self.find(inbox, ids)}
        with self.p.lock:
            box = 'gelen' if inbox else 'giden'
            self.d[box] = [r for r in self.d[box] if r['id'] not in drop]
            self.p.dirty = True
        # messageInfoCommands: istemci listeyi silmeden sonra bunlardan yeniden kuruyor (UserMessageDeleteEventHandler.Run ->
        # CreateMailItem); boş gidince liste boşalıyordu (canlı deneme 2026-10-17). Kutunun ilk sayfası.
        return [('UserMessageDeleteCommand', {'inbox': inbox, 'count': len(self.d['gelen' if inbox else 'giden']),
                                              'textCommand': stack(), 'titleCommand': stack(), 'deleteIds': sorted(drop),
                                              'unreadCount': self.unread(), 'success': bool(drop),
                                              'messageInfoCommands': self.box(inbox, 0)[1]['userMessageInfoCommandList']})]

    def status(self, inbox, st, ids):
        rows = self.find(inbox, ids)
        with self.p.lock:
            for r in rows:
                r['durum'] = st
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
            self.log('   posta eki alındı: %s %s' % (r['konu'], r.get('attachments')))
        page = []
        if done:                                       # istemci Loot yanıtını işlemiyor: "Claimed" görünsün diye mesajın sayfası
            pos = next(i for i, r in enumerate(self.d['gelen']) if r['id'] == done[0])
            page = [self.box(True, pos // PAGE * PAGE)]
        return [('UserMessageLootCommand', {'ids': done})] + msgs + page

    # -------------------------------------------------------- notlar
    def note_cmd(self, n):
        return mod('UserMessageNoteInfoCommand', insertDate=n['tarih'], noteId=n['id'], body=n['metin'], subject=n['konu'])

    def notes(self, name, f):
        notes = self.d['notlar']
        lst = lambda: [self.note_cmd(n) for n in notes]
        if name == 'UserMessageNoteListRequest':
            return [('UserMessageNoteListCommand', {'noteInfoCommandList': lst()})]
        if name == 'UserMessageNoteAddRequest':
            if len(notes) >= self.note_limit():
                return [('UserMessageNoteAddCommand', {'commandList': lst(), 'titleCommand': stack('messaging_errorLayer_notesLimitReached_title'),
                                                       'success': False,
                                                       'textCommand': stack('messaging_errorLayer_notesLimitReached_text', _notesLimit_=self.note_limit())})]
            with self.p.lock:
                nid = self.d['sira']
                self.d['sira'] += 1
                notes.insert(0, {'id': nid, 'tarih': stamp(), 'konu': str(f.get('subject', ''))[:50],
                                 'metin': str(f.get('body', ''))[:5000]})
                self.p.dirty = True
            return [('UserMessageNoteAddCommand', {'commandList': lst(), 'titleCommand': stack(), 'success': True,
                                                   'textCommand': stack()})]
        nid = int(f.get('noteId') or 0)
        n = next((x for x in notes if x['id'] == nid), None)
        if name == 'UserMessageNoteUpdateRequest':
            if n:
                with self.p.lock:
                    n.update(konu=str(f.get('subject', ''))[:50], metin=str(f.get('body', ''))[:5000], tarih=stamp())
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

    # -------------------------------------------------------- kara liste
    def note_limit(self):
        return NOTE_LIMIT_PREMIUM if self.p.premium else NOTE_LIMIT

    def blacklist(self, name, f):
        bl = self.d['kara_liste']
        uid = int(f.get('blackUserId') or 0)
        ids = lambda: [x['id'] for x in bl]
        names = lambda: [x['ad'] for x in bl]
        if name == 'BlackListGetRequest':
            return [('BlackListGetCommand', {'blackList': ids(), 'blackNameList': names()})]
        ok = False
        with self.p.lock:
            if name == 'BlackListAddRequest' and uid and uid != self.p.user_id and uid not in ids():
                bl.append({'id': uid, 'ad': str(uid)})
                ok = True
            elif name == 'BlackListDeleteRequest' and uid in ids():
                bl[:] = [x for x in bl if x['id'] != uid]
                ok = True
            self.p.dirty = True
        cmd = 'BlackListAddCommand' if name == 'BlackListAddRequest' else 'BlackListDeleteCommand'
        return [(cmd, {'textCommand': stack(), 'titleCommand': stack(), 'success': ok, 'blackList': ids(),
                       'blackNameList': names(), 'blackUserId': uid})]
