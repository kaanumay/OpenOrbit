"""After the ship is destroyed: the free repair at the base (pilot.json recover), up to max_revives times in a session; the mode's errand
(its maps, or the galaxy gate's portal) brings the ship back. Otherwise the bot stops."""

REVIVE_DELAY = 5.0            # the death screen stays a moment (the player sees what happened)
RETRY_SEC = 10.0


def dead(pilot, now):
    cfg = pilot.cfg['recover']
    if pilot.dead_at is None:
        pilot.dead_at, pilot.revive_at = now, 0.0
        pilot.stats.add('deaths')
        pilot.note('ship destroyed')
    if not cfg['revive'] or pilot.stats['revives'] >= cfg['max_revives']:
        return pilot.stop('dead')
    if now - pilot.dead_at < REVIVE_DELAY or now - pilot.revive_at < RETRY_SEC:
        return
    pilot.revive_at = now
    if pilot.act.revive():
        pilot.stats.add('revives')
        pilot.note('repaired at the base (%d/%d)' % (pilot.stats['revives'], cfg['max_revives']))
