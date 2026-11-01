"""Hitac's Word Puzzle and Capsule Lottery (roadmap Ö3; data data/extra_events.json 'hitac_lottery').

Client:
  - Menu item word_puzzle (window 115, UIWordPuzzleSystem): WordPuzzleWindowInitCommand {letterCount} the word's length;
    WordPuzzleLetterAchievedCommand {letterValues [WordPuzzleLetterModule {letterValue, letterIndex}], complete} the collected letters.
    Texts: label_wordpuzzle_* ("Collect cargo boxes from the Hitac minions ..."), lottery_collected_letter (%LETTER%),
    lottery_completed_wordpuzzle, log_msg_received_lottery_ticket_s.
  - The LOTTERY tab of the Vouchers window: LotteryEventFlushCommand {state, spcId} opens/closes the tab (false on login in the record);
    LotteryRequest {quantity} -> LotteryRequestCommand {lotteryLogCommandList [LotteryLogCommand {lotteryLogRewardCommandList
    [{lootId, amount}], lcId, date, amountCapsules, converter}], change, lotteryItems, quantity}. Text: payment_lottery_text_hitacconverter,
    lottery_rewards_booked_history "%ITEM% (%AMOUNT%x)".
Rules (official FAQ and wiki; numbers in extra_events.json): the Hitac Minion's box (HITAC_MINION) holds 300 MCB-50 and a 50% letter;
Underling 0.5%, Underboss 18% letter box; always one of the missing letters; when HITAC is completed one capsule
(resource_lottery-capsule); the mothership's box (HITAC) holds one capsule; capsules also come from the shop; at the Capsule Converter each capsule gives one reward from
the table (2024-2026, 40 packages). Letters drop only while the Hitac event runs; capsules are permanent, converting them also only while the event runs.
The Underling's and Underboss's box gives a row from the contents next to the letter (letter_extra), the mothership's box gives 50 ACM-1 and 1,000 PLT-3030 and lucky technology.
When the event ends, as many entitlements as converted capsules each draw a reward from the 'end_draw' pool.
In the profile: hitac_lottery {letters: [collected index numbers], history: [{date, count, rewards}], spent: draw entitlements}.
"""
import json, os, random, time

import settings as SET
import loot as LOOT
import event_calendar as CAL
from galaxy_gates import screen

HERE = os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(HERE, 'data', 'extra_events.json')
D = (json.load(open(_PATH, encoding='utf8')) if os.path.exists(_PATH) else {}).get('hitac_lottery', {})
EVENT = 'hitac'
WORD = D.get('word', 'HITAC')
LETTER = 'resource_wordpuzzle-letter'      # the letter in the box (the shop's reward path: a random missing letter)
CAPSULE = 'resource_lottery-capsule'
MINION = D.get('minion', 'event_hitac_minion')
MOTHERSHIP = D.get('mothership', 'event_hitac_mothership')
MINIONS, MOTHERSHIPS = {MINION, 'event_hitac2_minion'}, {MOTHERSHIP, 'event_hitac2_mothership'}      # E8: Hitac 2.0 da
HISTORY_MAX = 20


def active(now=None):
    return EVENT in CAL.active(now)


class HitacLottery:
    REQUESTS = ('LotteryRequest',)

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log

    @property
    def st(self):
        d = self.p.d.setdefault('hitac_lottery', {})
        d.setdefault('letters', [])
        d.setdefault('history', [])
        return d

    # ------------------------------------------------------------ puzzle
    def letters_cmd(self, complete=False):
        got = sorted(self.st['letters'])
        return ('WordPuzzleLetterAchievedCommand', dict(complete=complete, letterValues=[
            {'_': 'WordPuzzleLetterModule', 'letterValue': WORD[i], 'letterIndex': i} for i in got]))

    def login_msgs(self):
        msgs = [('LotteryEventFlushCommand', {'state': active(), 'spcId': 0})]
        if active():
            msgs += [('WordPuzzleWindowInitCommand', {'letterCount': len(WORD)}), self.letters_cmd()]
        return msgs

    def tick(self, now):
        """The event started or ended while the session was running: the tab and the puzzle window."""
        on = active(now)
        if getattr(self, 'was', None) is None:
            self.was = on
        msgs = [] if on else self.end_draw()
        if on == self.was:
            return msgs
        self.was = on
        return self.login_msgs() + msgs

    def login_replace(self, n, f):
        if n == 'LotteryEventFlushCommand':        # false in the record: the tab is open while the event runs (separately in the ready bundle)
            return [(n, dict(f, state=active()))]
        return None

    def grant_letter(self, n=1):
        """Letter from a box (the shop's reward path): random among the missing; when complete a capsule, the puzzle starts over at the next letter."""
        msgs = []
        for _ in range(max(1, n)):
            st = self.st
            if len(st['letters']) >= len(WORD):
                st['letters'] = []                 # the previous word was complete: starts over
            missing = [i for i in range(len(WORD)) if i not in st['letters']]
            i = random.choice(missing)
            with self.p.lock:
                st['letters'].append(i)
                self.p.dirty = True
            msgs.append(screen('key:lottery_collected_letter', LETTER=WORD[i]))
            done = len(st['letters']) >= len(WORD)
            msgs.append(self.letters_cmd(complete=done))
            self.log('   Word Puzzle: %s (%s)' % (WORD[i], ''.join(WORD[j] if j in st['letters'] else '_' for j in range(len(WORD)))))
            if done:
                msgs += self.m.reward(CAPSULE, 1) + [screen('key:lottery_completed_wordpuzzle')]
        return msgs

    # ------------------------------------------------------------ aliens
    def drop(self, w, kind, x, y, rows, life=300, pool=None, chance=None):
        """Event box: all of the 'guaranteed' rows; if pool (letter_extra) is given one row with equal weight, if chance ([lootId, count, probability]) is given
        each with its own probability (event_maps.roll)."""
        h = w.drop_box(kind, x, y, None, life)
        spec = {'type': kind, 'mod': 'one_of' if pool else 'hepsi', 'guaranteed': rows}
        if pool:
            spec['contents'] = pool
        elif chance:
            spec['contents'] = [[l, n, SET.chance('drop', c, 'event') * 100] for l, n, c in chance]
        w.boxes[h]['event'] = spec

    def on_kill(self, w, npc, x, y):
        """A Hitac alien died (under the world lock): the Minion's box (MCB-50, 50% letter), the Underling's (0.5%) and Underboss's (18%)
        letter box, the mothership's capsule box."""
        if not active():
            return []
        if npc.tip in MINIONS:
            b = D.get('minion_box', {'type': 'HITAC_MINION', 'contents': [['ammunition_laser_mcb-50', 300]], 'letter': 0.5})
            rows = [[l, a] for l, a in b['contents']] + ([[LETTER, 1]] if random.random() < SET.chance('drop', b.get('letter', 0.5), 'event') else [])
            self.drop(w, b['type'], x, y, rows, b.get('lifetime_sec', 300))
        elif npc.tip in MOTHERSHIPS:
            b = D.get('mothership_box', {'type': 'HITAC', 'capsule_at': 1})
            self.drop(w, b['type'], x, y, [[CAPSULE, b['capsule_at']]] + b.get('guaranteed', []), chance=b.get('chance'))      # + 50 ACM-1, 1,000 PLT-3030, lucky technology
        else:
            for prefix, (kind, chance, *pool) in (D.get('letter_extra') or {}).items():
                if not npc.tip.startswith(prefix):
                    continue
                rows = [[LETTER, 1]] if random.random() < SET.chance('drop', chance, 'event') else []      # panel: drop chance
                if rows or pool:                   # Underling / Underboss: the box always drops, the letter by chance, a row from its contents
                    self.drop(w, kind, x, y, rows, pool=pool[0] if pool else None)
        return []

    # ------------------------------------------------------------ end-of-event draw
    def end_draw(self):
        """Hitac ended (extra_events.json 'end_draw'; wiki: used capsules enter a draw at the end of the event): at the Capsule Converter each
        capsule spent is one entitlement, each entitlement draws 'package' pool rewards (those not owned; in single player the draw's only participant).
        The counter written while the event runs (profile 'spent'); paid out at the first step after the end (at login if it ended while the session was closed)."""
        c = D.get('end_draw')
        n = self.p.d.get('hitac_lottery', {}).get('spent', 0)       # called every step: do not open an empty record in the profile
        if not n or active():
            return []
        with self.p.lock:
            self.st['spent'] = 0
            self.p.dirty = True
        msgs, got = [], []
        for _ in range(n):
            pool = [r for r in (c or {}).get('pool', []) if not LOOT.owned(self.p, r[0]) and r[0] not in got]
            for loot, count in random.sample(pool, min(c.get('package', 1), len(pool))) if c else []:
                got.append(loot)
                msgs += self.m.reward(loot, count)
            if not pool:
                break
        if got:
            self.log('   Hitac ended: capsule draw (%d capsules) -> %s' % (n, ', '.join(got)))
        return msgs + (self.m.money_msgs() if got else [])

    # ------------------------------------------------------------ piyango
    def roll(self):
        rows = D.get('converter') or [['currency_uridium', 100, 1]]
        loot, amount, _ = random.choices(rows, [r[2] for r in rows])[0]
        return loot, (random.randint(*amount) if isinstance(amount, list) else amount)

    def handle(self, name, f):
        if name != 'LotteryRequest':
            return []
        # LotteryRequestCommand (live): quantity = remaining capsules (the tab's counter), lotteryItems = the number in the middle of the converter
        # (also capsules), change > 0 opens the success window.
        # When the tab opens the client asks with quantity 0: info only.
        have = self.p.resource(CAPSULE)
        want = int(f.get('quantity') or 0)
        q = max(0, min(want, have))
        if not active() or not q:
            if want:
                self.log('   Capsule Converter: %s (capsules %d)' % ('no event' if not active() else 'no capsules', have))
            info = [('LotteryRequestCommand', dict(lotteryLogCommandList=self.log_cmds(), change=0, lotteryItems=have, quantity=have))]
            return info + ([screen('key:payment_lottery_text_dialog_nocapsules')] if want else [])
        self.p.add_resource(CAPSULE, -q)
        with self.p.lock:
            self.st['spent'] = self.st.get('spent', 0) + q          # entitlements of the end-of-event draw
        got = {}
        for _ in range(q):
            loot, n = self.roll()
            got[loot] = got.get(loot, 0) + n
        msgs = self.m.resource_msgs(CAPSULE, self.p.resource(CAPSULE), -q)
        for loot, n in got.items():
            msgs += self.m.reward(loot, n)
        msgs += self.m.money_msgs()
        with self.p.lock:
            self.st['history'].insert(0, {'date': time.strftime('%Y-%m-%d %H:%M:%S'), 'count': q, 'rewards': sorted(got.items())})
            del self.st['history'][HISTORY_MAX:]
            self.p.dirty = True
        self.log('   Capsule Converter: %d capsules -> %s' % (q, ', '.join('%s x%d' % x for x in sorted(got.items()))))
        return [('LotteryRequestCommand', dict(lotteryLogCommandList=self.log_cmds(), change=q,
                                               lotteryItems=self.p.resource(CAPSULE), quantity=self.p.resource(CAPSULE)))] + msgs

    def log_cmds(self):
        return [{'_': 'LotteryLogCommand', 'lcId': i + 1, 'date': e['date'], 'amountCapsules': e['count'],
                 'converter': 'payment_lottery_text_hitacconverter',
                 'lotteryLogRewardCommandList': [{'_': 'LotteryLogRewardCommand', 'lootId': l, 'amount': n} for l, n in e['rewards']]}
                for i, e in enumerate(self.st['history'])]
