"""Mode run: event-specific and PvE modes (bot/modes.py). With the bot on, it picks the mode with the highest expected value among those it
can enter and pass, pays the cost (ticket, key, CPU), moves to the mode's map (leaving your map); when time is up it gets a reward
according to how far it got, then returns to base."""
from ..brain import Goal, target
from .. import catalog as K
from .. import modes as MD
from .. import abstract_sim as S


@target
class ModeRun(Goal):
    name = 'mod'
    permission = 'modes'
    min_sec = 3600 * 2

    def eligible(self, bot, b):
        if bot.level < 8:
            return False
        if b.now < bot.__dict__.get('_mode_next_check', 0):
            return bool(bot.__dict__.get('_mode_candidate'))
        bot._mode_next_check = b.now + 300                     # checks the mode list once every 5 minutes
        a = MD.candidates(bot, b.now)
        bot._mode_candidate = max(a, key=lambda m: MD.value(bot, m)) if a else None
        return bot._mode_candidate is not None

    def points(self, bot, b):
        return 0.7 + 0.5 * bot.o('ambition') + 0.3 * bot.o('rekabet') - 0.5 * bot.mood['fatigue'] + 0.2 * bot.mood['boredom']

    def start(self, bot, b):
        m = bot.__dict__.get('_mode_candidate')
        if m is None or not m.cost(bot):
            bot.plan['finished'] = True
            bot._mode_candidate, bot._mode_next_check = None, b.now + 1800   # could not enter: looks at other things for half an hour (so it does not idle)
            return
        ul, top, duration, reward = MD.run(bot, m, bot.r)
        bot.plan.update(mod=m.uid, ul=ul, top=top, sure=duration, reward=reward, end_time=b.now + duration)
        bot._mode_candidate = None
        bot._mode_next_check = 0
        if m.game_map:
            S.jump_to(bot, m.game_map, b.y)                 # the mode's map: leaves your map
        bot.event('entered_mode', mod=m.name)

    def abstract(self, bot, dt, y):
        if bot.plan.get('finished') or y.now < bot.plan.get('end_time', 0):
            return
        m = next((x for x in MD.modes() if x.uid == bot.plan.get('mod')), None)
        if m is not None:
            o = bot.plan.get('reward') or {}
            bot.reward('npc', y.speed(bot), ep=o.get('ep', 0), credits=o.get('credits', 0), uridium=o.get('uridium', 0), honor=o.get('honor', 0))
            m.finish(bot, bot.plan['ul'], bot.plan['top'], bot.plan['sure'], bot.r)
            m.save(bot, bot.plan['ul'], bot.plan['top'])
            bot.ist('mode_run')
            bot.event('mode_done', mod=m.name, progress='%d/%d' % (bot.plan['ul'], bot.plan['top']))
        if bot.game_map not in K.MAPS:
            S.jump_to(bot, K.ev(bot.firma), y)
        bot.plan['finished'] = True

    def concrete(self, bot, g, w, now):
        return False

    def finished(self, bot, b):
        return bot.plan.get('finished', False)
