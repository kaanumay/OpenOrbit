"""Black Light raid: at its company's BL entry level a pilot gathers with others of its company at X-8, they form a group and go into
the BL map together (bot/blacklight.py). Alone it waits there hunting; with RAID_MIN gathered the oldest one invites the others and leads
them in. On the BL map the team hunts until its time is up or fewer than two are left; then the group breaks up."""
from ..brain import Goal, target
from .. import abstract_sim as S
from .. import blacklight as BLK

GATHER_SEC = 20 * 60              # gives up gathering after this long
FULL_TEAM = 5                     # goes in at once from this many (a team of 5 LF-3 Goliaths takes Impulse II, the Rinusk alien)
WAIT_SEC = 8 * 60                 # with RAID_MIN..FULL_TEAM-1 it waits this long for more, then goes in
RAID_SEC = (60 * 60, 150 * 60)    # how long a raid lasts
COOLDOWN = (1 * 3600, 4 * 3600)   # until the next raid (Rinusk comes slowly: ~20-40 per hour each in a team of 5)


def _y():
    from .. import manager as MGR
    return MGR.ACTIVE


def _lobby(y, company):
    """The raiders of a company waiting at X-8: uid -> Bot."""
    return y.__dict__.setdefault('bl_lobby', {}).setdefault(company, {})


@target
class BlacklightRaid(Goal):
    name = 'bl_raid'
    permission = 'group'
    min_sec = 600

    def eligible(self, bot, b):
        now = b.now if b is not None else bot.hour()
        return now >= bot.k.get('bl_next', 0) and BLK.ready(bot)

    def points(self, bot, b):
        p = 0.55 + 0.35 * bot.o('ambition') + 0.25 * bot.o('sociability') + 0.15 * bot.o('risk')
        y = b.y if b is not None else None
        if y is not None and _lobby(y, bot.company):
            p += 0.5                                    # others are already waiting at X-8: it joins them
        return p * (1 - 0.4 * bot.mood['fatigue'])

    def start(self, bot, b):
        bot.plan.update(phase='gather', map=BLK.GATEWAY[bot.company], since=b.now, min=GATHER_SEC)       # waits out the gathering
        S.go(bot, BLK.GATEWAY[bot.company], b.y, b.now)

    def _step(self, bot, y, now):
        """The raid's state machine (abstract and concrete) -> True if it is busy travelling."""
        if y is None:
            bot.plan['finished'] = True
            return False
        lobby = _lobby(y, bot.company)
        phase = bot.plan.get('phase')
        if phase == 'gather':
            if bot.game_map != BLK.GATEWAY[bot.company]:
                return False
            lobby[bot.uid] = bot
            here = [o for o in lobby.values() if o.online and o.game_map == bot.game_map and o.target is not None and o.target.name == self.name]
            for u in [u for u, o in lobby.items() if o not in here]:
                lobby.pop(u, None)
            waited = now - min(o.plan.get('since', now) for o in here)
            if len(here) >= FULL_TEAM or (len(here) >= BLK.RAID_MIN and waited >= WAIT_SEC):
                here.sort(key=lambda o: (-o.level, o.uid))
                leader, party = here[0], here[:BLK.TEAM_MAX]
                end = now + bot.r.uniform(*RAID_SEC)
                BLK.form_group(y, leader, party, now, end)
                for o in party:
                    lobby.pop(o.uid, None)
                    o.plan.update(phase='raid', map=BLK.BL_MAP[o.company], until=end, leader=leader.uid,
                                  min=end - o.goal_start)         # committed until the raid ends (brain.decision)
                    o.k['bl_raids'] = o.k.get('bl_raids', 0) + 1
                    o.event('bl_raid', now, size=len(party))
                    S.go(o, BLK.BL_MAP[o.company], y, now)
                return True
            if now - bot.plan.get('since', now) > GATHER_SEC:
                lobby.pop(bot.uid, None)
                bot.plan['finished'] = True
            return False
        if phase == 'raid':
            if bot.game_map != BLK.BL_MAP[bot.company]:
                if not bot.en_route and not S.go(bot, BLK.BL_MAP[bot.company], y, now):
                    bot.plan['finished'] = True
                return False
            if now > bot.plan.get('until', now) or BLK.team(bot, y) < 2:
                bot.plan['finished'] = True
            return False
        bot.plan['finished'] = True
        return False

    def abstract(self, bot, dt, y):
        if S.journey(bot, y):
            return
        self._step(bot, y, y.now if y is not None else bot.hour())
        if not bot.plan.get('finished') and not bot.en_route:
            S.farm(bot, dt, y)                         # hunts at X-8 while waiting, as a team on the BL map

    def concrete(self, bot, g, w, now):
        self._step(bot, _y(), now)
        return False                                    # the body hunts and flies its route as usual

    def finished(self, bot, b):
        if not bot.plan.get('finished', False):
            return False
        import group as GR
        from .. import society as SO
        y = b.y if b is not None else None
        if y is not None:
            _lobby(y, bot.company).pop(bot.uid, None)
        if bot.plan.get('phase') == 'raid' and GR.group_of(bot.uid) is not None:
            GR.handle(SO.person(bot), 'LeaveGroupRequest', {})
        now = b.now if b is not None else bot.hour()
        bot.k['bl_next'] = now + bot.r.uniform(*COOLDOWN)
        return True
