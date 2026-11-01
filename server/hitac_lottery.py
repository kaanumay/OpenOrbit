"""Hitac'ın Word Puzzle'ı ve Capsule Lottery'si (yol haritası Ö3; veri data/extra_events.json 'hitac_piyango').

İstemci:
  - Menü öğesi word_puzzle (pencere 115, UIWordPuzzleSystem): WordPuzzleWindowInitCommand {letterCount} kelimenin boyu;
    WordPuzzleLetterAchievedCommand {letterValues [WordPuzzleLetterModule {letterValue, letterIndex}], complete} toplanan harfler.
    Metinler: label_wordpuzzle_* ("Collect cargo boxes from the Hitac minions …"), lottery_collected_letter (%LETTER%),
    lottery_completed_wordpuzzle, log_msg_received_lottery_ticket_s.
  - Vouchers penceresinin LOTTERY sekmesi: LotteryEventFlushCommand {state, spcId} sekmeyi açar/kapatır (kayıtta girişte false);
    LotteryRequest {quantity} -> LotteryRequestCommand {lotteryLogCommandList [LotteryLogCommand {lotteryLogRewardCommandList
    [{lootId, amount}], lcId, date, amountCapsules, converter}], change, lotteryItems, quantity}. Metin: payment_lottery_text_hitacconverter,
    lottery_rewards_booked_history "%ITEM% (%AMOUNT%x)".
Kurallar (resmî SSS ve wiki; sayılar extra_events.json): Hitac Minion'ın kutusunda (HITAC_MINION) 300 MCB-50 ve %50 harf;
Underling %0,5, Underboss %18 harf kutusu; her zaman eksik harflerden biri; HITAC tamamlanınca bir kapsül
(resource_lottery-capsule); ana gemi kutusunda (HITAC) bir kapsül; kapsüller mağazadan da gelir; Capsule Converter'da her kapsül
tablodan (2024-2026, 40 paket) bir ödül. Harfler yalnız Hitac etkinliği sürerken düşer; kapsüller kalıcı, çevirmek de etkinlik sürerken.
Underling ve Underboss kutusu harfin yanında içerikten bir satır (harf_ek), ana gemi kutusu 50 ACM-1 ve 1.000 PLT-3030 ile şanslı teknoloji
verir. Etkinlik bitince çevrilen kapsül sayısı kadar hak 'bitis_cekilisi' havuzundan ödül çeker (end_draw).
Profilde: hitac_piyango {harfler: [toplanan sıra numaraları], gecmis: [{tarih, adet, oduller}], harcanan: çekiliş hakkı}.
"""
import json, os, random, time

import settings as SET
import loot as LOOT
import event_calendar as CAL
from galaxy_gates import screen

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('hitac_piyango', {})
EVENT = 'hitac'
WORD = D.get('kelime', 'HITAC')
LETTER = 'resource_wordpuzzle-letter'      # kutudaki harf (mağazanın ödül yolu: rastgele eksik harf)
CAPSULE = 'resource_lottery-capsule'
MINION = D.get('minion', 'etk_hitac_minion')
MOTHERSHIP = D.get('ana_gemi', 'etk_hitac_mothership')
MINIONS, MOTHERSHIPS = {MINION, 'etk_hitac2_minion'}, {MOTHERSHIP, 'etk_hitac2_mothership'}      # E8: Hitac 2.0 da
HISTORY_MAX = 20


def active(now=None):
    return EVENT in CAL.active(now)


class HitacLottery:
    REQUESTS = ('LotteryRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        d = self.p.d.setdefault('hitac_piyango', {})
        d.setdefault('harfler', [])
        d.setdefault('gecmis', [])
        return d

    # ------------------------------------------------------------ bulmaca
    def letters_cmd(self, complete=False):
        got = sorted(self.st['harfler'])
        return ('WordPuzzleLetterAchievedCommand', dict(complete=complete, letterValues=[
            {'_': 'WordPuzzleLetterModule', 'letterValue': WORD[i], 'letterIndex': i} for i in got]))

    def login_msgs(self):
        msgs = [('LotteryEventFlushCommand', {'state': active(), 'spcId': 0})]
        if active():
            msgs += [('WordPuzzleWindowInitCommand', {'letterCount': len(WORD)}), self.letters_cmd()]
        return msgs

    def tick(self, now):
        """Etkinlik oturum sürerken başladı ya da bitti: sekme ve bulmaca penceresi."""
        on = active(now)
        if getattr(self, 'was', None) is None:
            self.was = on
        msgs = [] if on else self.end_draw()
        if on == self.was:
            return msgs
        self.was = on
        return self.login_msgs() + msgs

    def login_replace(self, n, f):
        if n == 'LotteryEventFlushCommand':        # kayıttaki false: etkinlik sürerken sekme açık (hazır demetinde ayrıca)
            return [(n, dict(f, state=active()))]
        return None

    def grant_letter(self, n=1):
        """Kutudan harf (mağazanın ödül yolu): eksiklerden rastgele; tamamlanınca kapsül, bulmaca sıradaki harfte baştan."""
        msgs = []
        for _ in range(max(1, n)):
            st = self.st
            if len(st['harfler']) >= len(WORD):
                st['harfler'] = []                 # önceki kelime tamamdı: yeniden başlar
            missing = [i for i in range(len(WORD)) if i not in st['harfler']]
            i = random.choice(missing)
            with self.p.lock:
                st['harfler'].append(i)
                self.p.dirty = True
            msgs.append(screen('key:lottery_collected_letter', LETTER=WORD[i]))
            done = len(st['harfler']) >= len(WORD)
            msgs.append(self.letters_cmd(complete=done))
            self.log('   Word Puzzle: %s (%s)' % (WORD[i], ''.join(WORD[j] if j in st['harfler'] else '_' for j in range(len(WORD)))))
            if done:
                msgs += self.m.reward(CAPSULE, 1) + [screen('key:lottery_completed_wordpuzzle')]
        return msgs

    # ------------------------------------------------------------ uzaylılar
    def drop(self, w, kind, x, y, rows, life=300, pool=None, chance=None):
        """Etkinlik kutusu: 'kesin' satırların hepsi; pool (harf_ek) verilirse eşit ağırlıkla bir satır, sans ([lootId, adet, olasılık]) verilirse
        her biri kendi olasılığıyla (etkinlik_harita.roll)."""
        h = w.drop_box(kind, x, y, None, life)
        spec = {'tur': kind, 'mod': 'biri' if pool else 'hepsi', 'kesin': rows}
        if pool:
            spec['icerik'] = pool
        elif chance:
            spec['icerik'] = [[l, n, SET.chance('dusme', c, 'etkinlik') * 100] for l, n, c in chance]
        w.boxes[h]['etk'] = spec

    def on_kill(self, w, npc, x, y):
        """Hitac uzaylısı öldü (dünya kilidi altında): Minion'ın kutusu (MCB-50, %50 harf), Underling (%0,5) ve Underboss'un (%18)
        harf kutusu, ana geminin kapsül kutusu."""
        if not active():
            return []
        if npc.tip in MINIONS:
            b = D.get('minion_kutusu', {'tur': 'HITAC_MINION', 'icerik': [['ammunition_laser_mcb-50', 300]], 'harf': 0.5})
            rows = [[l, a] for l, a in b['icerik']] + ([[LETTER, 1]] if random.random() < SET.chance('dusme', b.get('harf', 0.5), 'etkinlik') else [])
            self.drop(w, b['tur'], x, y, rows, b.get('omur_sn', 300))
        elif npc.tip in MOTHERSHIPS:
            b = D.get('ana_gemi_kutusu', {'tur': 'HITAC', 'kapsul': 1})
            self.drop(w, b['tur'], x, y, [[CAPSULE, b['kapsul']]] + b.get('kesin', []), chance=b.get('sans'))      # + 50 ACM-1, 1.000 PLT-3030, şanslı teknoloji
        else:
            for prefix, (kind, chance, *pool) in (D.get('harf_ek') or {}).items():
                if not npc.tip.startswith(prefix):
                    continue
                rows = [[LETTER, 1]] if random.random() < SET.chance('dusme', chance, 'etkinlik') else []      # panel: düşme şansı
                if rows or pool:                   # Underling / Underboss: kutu her zaman düşer, harf şansla, içeriğinden bir satır
                    self.drop(w, kind, x, y, rows, pool=pool[0] if pool else None)
        return []

    # ------------------------------------------------------------ etkinlik sonu çekilişi
    def end_draw(self):
        """Hitac bitti (extra_events.json 'bitis_cekilisi'; wiki: kullanılan kapsüller etkinlik sonunda çekilişe girer): Capsule Converter'da
        harcanan her kapsül bir hak, her hak 'paket' kadar havuz ödülü (sahip olunmayanlar; tek oyunculuda çekilişin tek katılımcısı).
        Etkinlik sürerken yazılan sayaç (profilde 'harcanan'); bitişten sonra ilk adımda (oturum kapalıyken bittiyse girişte) ödenir."""
        c = D.get('bitis_cekilisi')
        n = self.p.d.get('hitac_piyango', {}).get('harcanan', 0)       # her adımda çağrılır: profile boş kayıt açma
        if not n or active():
            return []
        with self.p.lock:
            self.st['harcanan'] = 0
            self.p.dirty = True
        msgs, got = [], []
        for _ in range(n):
            pool = [r for r in (c or {}).get('havuz', []) if not LOOT.owned(self.p, r[0]) and r[0] not in got]
            for loot, count in random.sample(pool, min(c.get('paket', 1), len(pool))) if c else []:
                got.append(loot)
                msgs += self.m.reward(loot, count)
            if not pool:
                break
        if got:
            self.log('   Hitac bitti: kapsül çekilişi (%d kapsül) -> %s' % (n, ', '.join(got)))
        return msgs + (self.m.money_msgs() if got else [])

    # ------------------------------------------------------------ piyango
    def roll(self):
        rows = D.get('donusturucu') or [['currency_uridium', 100, 1]]
        loot, amount, _ = random.choices(rows, [r[2] for r in rows])[0]
        return loot, (random.randint(*amount) if isinstance(amount, list) else amount)

    def handle(self, name, f):
        if name != 'LotteryRequest':
            return []
        # LotteryRequestCommand (canlı): quantity = kalan kapsül (sekmenin sayacı), lotteryItems = dönüştürücünün ortasındaki sayı
        # (o da kapsül), change > 0 başarı penceresini açar.
        # Sekme açılınca istemci quantity 0 ile sorar: yalnız bilgi.
        have = self.p.resource(CAPSULE)
        want = int(f.get('quantity') or 0)
        q = max(0, min(want, have))
        if not active() or not q:
            if want:
                self.log('   Capsule Converter: %s (kapsül %d)' % ('etkinlik yok' if not active() else 'kapsül yok', have))
            info = [('LotteryRequestCommand', dict(lotteryLogCommandList=self.log_cmds(), change=0, lotteryItems=have, quantity=have))]
            return info + ([screen('key:payment_lottery_text_dialog_nocapsules')] if want else [])
        self.p.add_resource(CAPSULE, -q)
        with self.p.lock:
            self.st['harcanan'] = self.st.get('harcanan', 0) + q          # etkinlik sonu çekilişinin hakları
        got = {}
        for _ in range(q):
            loot, n = self.roll()
            got[loot] = got.get(loot, 0) + n
        msgs = self.m.resource_msgs(CAPSULE, self.p.resource(CAPSULE), -q)
        for loot, n in got.items():
            msgs += self.m.reward(loot, n)
        msgs += self.m.money_msgs()
        with self.p.lock:
            self.st['gecmis'].insert(0, {'tarih': time.strftime('%Y-%m-%d %H:%M:%S'), 'adet': q, 'oduller': sorted(got.items())})
            del self.st['gecmis'][HISTORY_MAX:]
            self.p.dirty = True
        self.log('   Capsule Converter: %d kapsül -> %s' % (q, ', '.join('%s x%d' % x for x in sorted(got.items()))))
        return [('LotteryRequestCommand', dict(lotteryLogCommandList=self.log_cmds(), change=q,
                                               lotteryItems=self.p.resource(CAPSULE), quantity=self.p.resource(CAPSULE)))] + msgs

    def log_cmds(self):
        return [{'_': 'LotteryLogCommand', 'lcId': i + 1, 'date': e['tarih'], 'amountCapsules': e['adet'],
                 'converter': 'payment_lottery_text_hitacconverter',
                 'lotteryLogRewardCommandList': [{'_': 'LotteryLogRewardCommand', 'lootId': l, 'amount': n} for l, n in e['oduller']]}
                for i, e in enumerate(self.st['gecmis'])]
