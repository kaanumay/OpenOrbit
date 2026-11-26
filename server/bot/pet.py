"""P.E.T. (R.E.X. in French) for bots (user request 2026-11-26: bots never bought one): bought from the shop like the player's (pet.py data),
it levels up with a share of the bot's EP and adds its laser slots to the bot's lasers; on the player's map it flies next to the bot's
ship (the other players' P.E.T. messages: PetActivationCommand, MoveCommand).

State: gear['pet'] = {'ep': n, 'level': n} (in the gear so catalog.outfit counts its laser slots; shopping then fills them).
"""
import math, random

from . import catalog as K

ID_OFFSET = 90000000                     # the P.E.T.'s unit id: the bot's uid + this (bots 1.8e9 + n: still below the players' 1.9e9)


def _data():
    import pet as P
    return P.PET


def owned(gear):
    return bool(gear.get('pet'))


def level(gear):
    return int((gear.get('pet') or {}).get('level', 0))


def laser_slots(gear):
    """The P.E.T.'s laser slots at its level (pet.json levels: 1 at level 1 .. 12 at level 21)."""
    lv = level(gear)
    if not lv:
        return 0
    rows = _data()['levels']
    return int(rows[min(lv, len(rows)) - 1]['slot']['lasers'])


def price(bot):
    """('U', amount) from the shop (the World Editor's price and removal from sale apply), None if not for sale."""
    return K.price(_data()['loot'])


def wants(bot):
    """A pilot buys its P.E.T. once it has spare uridium: from level 8 (the wiki's "mid game"), with three times its price in hand
    for a frugal one, one and a half for a showy or ambitious one."""
    if owned(bot.k['gear']) or bot.level < 8 or not bot.permission.get('shop', True):
        return False
    f = price(bot)
    if not f:
        return False
    cost = f[1] * bot.game_settings.multiplier('shop_price')
    keep = 1.5 + 1.5 * bot.o('frugality') - 0.4 * bot.o('ambition')
    return bot.k['uridium' if f[0] == 'U' else 'credits'] >= cost * max(1.1, keep)


def buy(bot):
    """Buys the P.E.T. if it wants one -> bought."""
    if not wants(bot):
        return False
    f = price(bot)
    if not bot.pay(f[0], f[1] * bot.game_settings.multiplier('shop_price')):
        return False
    bot.k['gear']['pet'] = {'ep': 0, 'level': 1}
    bot.loadout_changed()
    bot.ist('pet_bought')
    bot.event('pet_bought')
    return True


def gain(bot, ep):
    """The P.E.T.'s share of the bot's EP (pet.json ep_share, the pet_ep setting) -> its level from the level table."""
    p = bot.k['gear'].get('pet')
    if not p or ep <= 0:
        return
    import settings as SET
    p['ep'] = p.get('ep', 0) + ep * _data()['ep_share'] * SET.multiplier('pet_ep')
    rows = _data()['levels']
    lv = max(i + 1 for i, r in enumerate(rows) if p['ep'] >= r['ep'])
    if lv != p.get('level'):
        up = lv > p.get('level', 1)
        p['level'] = lv
        bot.loadout_changed()
        if up:
            bot.event('pet_level', level=lv)


# ------------------------------------------------------------------------------------------------------------ on the player's map
def unit_id(bot):
    return int(bot.uid) + ID_OFFSET


def is_bot_uid(uid):
    import community as TP
    return TP.BOTS is not None and uid in TP.BOTS()


def design(gear):
    """The P.E.T. model by level (pet.json ship_type: [[from level - 1, game.xml type] ...])."""
    lv = level(gear)
    out = 12
    for at, t in _data()['ship_type']:
        if lv - 1 >= at:
            out = t
    return out


def _spot(x, y, r=None):
    a = (r or random).uniform(0, 2 * math.pi)
    d = _data()['follow_distance']
    return int(x + math.cos(a) * d), int(y + math.sin(a) * d)


def show(w, n, now):
    """The bot's P.E.T. next to its ship (with ShipCreateCommand) -> messages."""
    b = n.bot
    if not owned(b.k['gear']):
        return []
    from world import mod
    import clan as KL
    x, y = _spot(*n.mover.pos(now), b.r)
    pl = b.profile.d['pilot'] if getattr(b, 'profile', None) else {}
    try:
        rel = KL.shown_relation(w.p, b.profile)
    except Exception:                         # noqa: BLE001 (no profile yet)
        rel = 0
    return [('PetActivationCommand', dict(
        ownerId=n.id, petId=unit_id(b), petDesignId=design(b.k['gear']), expansionStage=1, petName=b.k['gear']['pet'].get('name') or 'P.E.T.',
        petFactionId=b.company, petClanID=int(pl.get('clanId') or 0), petLevel=level(b.k['gear']), clanTag=pl.get('clanTag', ''),
        clanRelationship=mod('ClanRelationModule', type=rel), x=x, y=y, petSpeed=int(n.speed()), isInIdleMode=False, isVisible=True,
        minimapStrategyModule=mod('MinimapStrategyModule', minimapStrategy=0)))]


def follow(n, x, y, ms):
    """The P.E.T. follows its bot's move (the same arrival time, a spot next to the target) -> messages."""
    if not owned(n.bot.k['gear']):
        return []
    px, py = _spot(x, y, n.bot.r)
    return [('MoveCommand', dict(userId=unit_id(n.bot), x=px, y=py, timeToTarget=ms))]
