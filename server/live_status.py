"""The panel's live status page (roadmap Ö2): every few seconds the game server writes the game's current state to a JSON file
(<log folder>/canli_durum.json); the panel (server/panel/panel.py, /api/canli) reads and shows it. No separate channel is opened to the
server; the file is written under a temporary name and moved into place, so the panel never reads a half file.

Contents: connection, pilot (level, EP, credits, uridium, honor), ship (HP, shield, cargo), position (map, x, y), map
(live aliens, box and ore counts, target, in combat?, in a safe zone? station or portal, gate/wave, duration of the loop step),
events running on the calendar, play time.
"""
import json, os, threading, time

INTERVAL_SEC = 2.0


def _world_info(w):
    now = time.time()
    alive = [n for n in list(w.npcs.values()) if n.alive]
    t = w.npcs.get(w.target) if w.target else None
    out = {'alien': len(alive), 'box': len(w.boxes), 'ore': len(getattr(w, 'ores', {})),
           'target': (t.d.get('name') if t and t.alive else None), 'in_combat': bool(now - getattr(w, 'last_combat', 0) < 10),
           'dead': bool(w.hero_dead), 'safe': bool(w.in_station())}
    perf = getattr(w, 'perf', None)
    if perf:
        out['loop'] = perf.summary()               # duration of the loop step (ms; dunya.Olcum)
    run = getattr(w, 'gate', None)
    g = getattr(run, 'g', None) if run else None
    if g:
        try:
            wave = run.wave()
            out['gate'] = {'name': g.get('name'), 'wave': wave.get('name') if isinstance(wave, dict) else wave, 'stage': run.phase}
        except Exception:
            out['gate'] = {'name': g.get('name')}
    return out


def snapshot(game):
    """game: the game.py module (PROFIL, CURRENT) -> status dict."""
    import map_links as H
    import event_calendar as CAL
    p = game.PROFILE
    pl, g, k = p.d['pilot'], p.d['ship'], p.d['position']
    s = game.CURRENT
    w = s.world if s else None
    ship = p.d.get('ships', {}).get(str(p.d.get('active_ship')), {})
    played = p.d.get('play_sec', 0) + (time.time() - s.play_start if s and getattr(s, 'play_start', None) else 0)
    d = {'time': time.time(), 'connected': s is not None,
         'pilot': {'name': pl.get('userName'), 'level': pl.get('level', 1), 'ep': pl.get('ep', 0), 'credits': pl.get('credits', 0),
                   'uridium': pl.get('uridium', 0), 'honor': pl.get('honourPoints', 0), 'company': pl.get('factionId'),
                   'clan': pl.get('clanTag') or None},
         'ship': {'name': ship.get('lootId'), 'can': int(g.get('hitPoints', 0)), 'max_hp': g.get('hitMax', 0),
                  'kalkan': int(g.get('shield', 0)), 'shield_max': g.get('shieldMax', 0), 'cargo': p.cargo_used(),
                  'cargo_max': g.get('cargoSpaceMax', 0)},
         'position': {'map': H.name(k.get('mapId')), 'map_id': k.get('mapId'), 'x': int(k.get('x', 0)), 'y': int(k.get('y', 0))},
         'events': sorted(CAL.active()), 'play_sec': int(played),
         'session_start': s.play_start if s else None}         # duration of Discord Rich Presence (panel/discord_rp.py)
    if w:
        try:
            x, y = w.hero_pos()
            d['position'].update(x=int(x), y=int(y))
            d['world'] = _world_info(w)
        except Exception as e:                   # the world may be half-built while the map changes
            d['world'] = {'error': repr(e)}
    if game.CO.is_open():                           # friend server: guests (the panel's "Play with Friends" page)
        d['friend'] = {'max_count': game.CO.SETTINGS['max_count'], 'guests': [
            dict(m.summary(), map=H.name(m.profile.d['position'].get('mapId'))) for m in game.CO.entries()]}
        d['local_players'] = [dict(y.summary(), map=H.name(y.profile.d['position'].get('mapId')))     # the multi-client's extra players
                         for y in game.CO.local_players()]
    return d


def write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(data, fh, ensure_ascii=False)
    for k in range(5):                            # Windows refuses the replace while the panel is reading the file
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if k == 4:
                raise
            time.sleep(0.05)


def start(game, folder, log=print):
    path = os.path.join(folder, 'canli_durum.json')

    def loop():
        warned = False
        while True:
            try:
                write(path, snapshot(game))
                warned = False
            except Exception as e:
                if not warned:
                    log('   live status could not be written: %r' % e)
                    warned = True
            time.sleep(INTERVAL_SEC)

    threading.Thread(target=loop, daemon=True).start()
    return path
