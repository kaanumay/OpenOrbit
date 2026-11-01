"""Panelin canlı durum sayfası (yol haritası Ö2): oyun sunucusu birkaç saniyede bir oyunun anlık durumunu bir JSON dosyasına
(<günlük klasörü>/canli_durum.json) yazar; panel (server/panel/panel.py, /api/canli) okuyup gösterir. Sunucuya ayrı bir kanal açılmaz;
dosya geçici adla yazılıp yerine konduğu için panel yarım dosya okumaz.

İçerik: bağlantı, pilot (seviye, EP, kredi, uridyum, onur), gemi (can, kalkan, kargo), konum (harita, x, y), harita
(canlı uzaylı, kutu ve cevher sayısı, hedef, savaşta mı, güvenli bölgede mi: istasyon ya da portal, kapı/dalga, döngü adımının
süresi), takvimde süren etkinlikler, oynama süresi.
"""
import json, os, threading, time

INTERVAL_SEC = 2.0


def _world_info(w):
    now = time.time()
    alive = [n for n in list(w.npcs.values()) if n.alive]
    t = w.npcs.get(w.target) if w.target else None
    out = {'uzayli': len(alive), 'kutu': len(w.boxes), 'cevher': len(getattr(w, 'ores', {})),
           'hedef': (t.d.get('ad') if t and t.alive else None), 'in_combat': bool(now - getattr(w, 'last_combat', 0) < 10),
           'dead': bool(w.hero_dead), 'guvenli': bool(w.in_station())}
    perf = getattr(w, 'perf', None)
    if perf:
        out['loop'] = perf.summary()               # döngü adımının süresi (ms; dunya.Olcum)
    run = getattr(w, 'gate', None)
    g = getattr(run, 'g', None) if run else None
    if g:
        try:
            wave = run.wave()
            out['kapi'] = {'ad': g.get('ad'), 'dalga': wave.get('ad') if isinstance(wave, dict) else wave, 'stage': run.phase}
        except Exception:
            out['kapi'] = {'ad': g.get('ad')}
    return out


def snapshot(game):
    """game: game.py modülü (PROFIL, CURRENT) -> durum sözlüğü."""
    import map_links as H
    import event_calendar as CAL
    p = game.PROFILE
    pl, g, k = p.d['pilot'], p.d['gemi'], p.d['position']
    s = game.CURRENT
    w = s.world if s else None
    ship = p.d.get('gemiler', {}).get(str(p.d.get('aktif_gemi')), {})
    played = p.d.get('play_sec', 0) + (time.time() - s.play_start if s and getattr(s, 'play_start', None) else 0)
    d = {'time': time.time(), 'bagli': s is not None,
         'pilot': {'ad': pl.get('userName'), 'seviye': pl.get('level', 1), 'ep': pl.get('ep', 0), 'kredi': pl.get('credits', 0),
                   'uridyum': pl.get('uridium', 0), 'onur': pl.get('honourPoints', 0), 'firma': pl.get('factionId'),
                   'klan': pl.get('clanTag') or None},
         'gemi': {'ad': ship.get('lootId'), 'can': int(g.get('hitPoints', 0)), 'max_hp': g.get('hitMax', 0),
                  'kalkan': int(g.get('shield', 0)), 'shield_max': g.get('shieldMax', 0), 'kargo': p.cargo_used(),
                  'cargo_max': g.get('cargoSpaceMax', 0)},
         'position': {'harita': H.name(k.get('mapId')), 'map_id': k.get('mapId'), 'x': int(k.get('x', 0)), 'y': int(k.get('y', 0))},
         'etkinlikler': sorted(CAL.active()), 'play_sec': int(played),
         'session_start': s.play_start if s else None}         # Discord Rich Presence'ın süresi (panel/discord_rp.py)
    if w:
        try:
            x, y = w.hero_pos()
            d['position'].update(x=int(x), y=int(y))
            d['dunya'] = _world_info(w)
        except Exception as e:                   # harita değişirken dünya yarım olabilir
            d['dunya'] = {'hata': repr(e)}
    if game.CO.is_open():                           # arkadaş sunucusu: misafirler (panelin "Arkadaşlarınla Oyna" sayfası)
        d['arkadas'] = {'en_cok': game.CO.SETTINGS['en_cok'], 'guests': [
            dict(m.summary(), harita=H.name(m.profile.d['position'].get('mapId'))) for m in game.CO.entries()]}
        d['local_players'] = [dict(y.summary(), harita=H.name(y.profile.d['position'].get('mapId')))     # çoklu istemcinin ek oyuncuları
                         for y in game.CO.local_players()]
    return d


def write(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8') as fh:
        json.dump(data, fh, ensure_ascii=False)
    for k in range(5):                            # panel dosyayı okurken Windows yerine koymayı reddeder
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
                    log('   canlı durum yazılamadı: %r' % e)
                    warned = True
            time.sleep(INTERVAL_SEC)

    threading.Thread(target=loop, daemon=True).start()
    return path
