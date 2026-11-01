"""Bot adlarının değişim ve silinme kaydı: panelin Botlar sayfası yazar, oyun her yere uygular.

Botun adı oyunun birçok yerinde adıyla tutulur: klanın üyeleri, lideri, başvuruları (clan.py), oyuncunun klan kopyası (profil
'klan'), rehberler (profil 'rehber': arkadaş, istek, engelli), öteki botların hafızası ve rehberleri. Panel bir botun adını
değiştirince, kadroyu baştan üretince, bot sayısını azaltınca ya da paketi silince buraya sıralı olaylar ekler:
  {'n': sıra, 't': zaman, 'tur': 'ad', 'eski': ad, 'yeni': ad}     ad değişti
  {'n', 't', 'tur': 'sil', 'ad': ad}                                bot artık yok (her yerden çıkar)
  {'n', 't', 'tur': 'klan_cik', 'ad': ad}                           ilerlemesi sıfırlandı: klanlardan çıkar, tanışıklıkları kalır
Her tüketici en son uyguladığı sırayı saklar (profil 'bot_ad_kaydi', klan dosyası 'bot_ad_kaydi', paket durum.json) ve yalnız
yenilerini bir kez uygular: oyun kapalıyken yapılan değişiklik sonraki girişte, açıkken panel kanalıyla (panel_kanali /bot/ad_kaydi)
hemen uygulanır. Silinen ada sonradan başkası sahip olsa da eski olay ona dokunmaz.
Ada göre çalışır: kadro baştan üretilince yeni botlar eskilerin kimliğini (1800000000 + sıra) alır.
Gönderilmiş ve alınmış postalar geçmiştir, olduğu gibi kalır.
"""
import json, os, threading, time

import paths as PTH

LOCK = threading.RLock()
_cache = {'mtime': None, 'events': []}
BOT_UID = (1800000000, 1900000000)        # bot kimlikleri (bot/durum.BOT_UID_TABAN ...): klan liderliği insana geçerken


def file():
    return os.path.join(PTH.SAVE, 'bots', '_name_log.json')


def read():
    """Bütün olaylar (dosya değişmedikçe önbellekten)."""
    p = file()
    try:
        m = os.path.getmtime(p)
    except OSError:
        return []
    with LOCK:
        if _cache['mtime'] != m:
            try:
                with open(p, encoding='utf8') as f:
                    _cache['events'] = json.load(f).get('events') or []
            except (OSError, ValueError):
                _cache['events'] = []
            _cache['mtime'] = m
        return _cache['events']


def last():
    o = read()
    return o[-1]['n'] if o else 0


def add(events):
    """Panel: olayları ekle (ad değişimi, silinme). -> son sıra."""
    events = [x for x in events if x]
    if not events:
        return last()
    with LOCK:
        all_ = list(read())
        n = all_[-1]['n'] if all_ else 0
        t = time.time()
        for x in events:
            n += 1
            all_.append(dict(x, n=n, t=t))
        p = file()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p + '.tmp', 'w', encoding='utf8') as f:
            json.dump({'events': all_}, f, ensure_ascii=False)
        os.replace(p + '.tmp', p)
        _cache['mtime'] = None
        return n


def events_since(n):
    return [x for x in read() if x['n'] > int(n or 0)]


# ------------------------------------------------------------------------------------------------------------ uygulama
def _k(name):
    return str(name or '').strip().lower()


def apply_list(lst, events):
    """Ad listesi (rehber): yeniden adlandırma ve silinme -> yeni liste ya da None (değişmedi)."""
    out, changed = list(lst), False
    for e in events:
        if e['tur'] == 'ad':
            new_ = []
            for x in out:
                if _k(x) == _k(e['eski']):
                    x, changed = e['yeni'], True
                if not any(_k(y) == _k(x) for y in new_):
                    new_.append(x)
            out = new_
        elif e['tur'] == 'delete':
            remaining = [x for x in out if _k(x) != _k(e['ad'])]
            changed = changed or len(remaining) != len(out)
            out = remaining
    return out if changed else None


def apply_clan(k, events):
    """Klan kaydı (asıl kayıt ya da profildeki kopya) -> 'bos' (kimse kalmadı), True (değişti) ya da False. Lider giderse liderlik
    insan üyeye (yoksa sıradakine) geçer."""
    changed = False
    for e in events:
        if e['tur'] == 'ad':
            old, new_ = _k(e['eski']), _k(e['yeni'])
            if old in k['members'] and old != new_:
                k['members'][new_] = dict(k['members'].pop(old), ad=e['yeni'])
                if k['lider'] == old:
                    k['lider'] = new_
                changed = True
            for b in k.get('applications', []):
                if _k(b.get('ad')) == old:
                    b.update(ad=new_, isim=e['yeni'])
                    changed = True
            k['rejected'] = [new_ if _k(r) == old else r for r in k.get('rejected', [])]
        else:                                            # sil, klan_cik
            a = _k(e['ad'])
            if a in k['members']:
                del k['members'][a]
                changed = True
                if k['lider'] == a:
                    if not k['members']:
                        return 'vacant'
                    human = [x for x, u in k['members'].items() if not BOT_UID[0] <= int(u.get('uid') or 0) < BOT_UID[1]]
                    k['lider'] = (human or list(k['members']))[0]
            n = len(k.get('applications', []))
            k['applications'] = [b for b in k.get('applications', []) if _k(b.get('ad')) != a]
            changed = changed or n != len(k['applications'])
            if e['tur'] == 'delete':
                k['rejected'] = [r for r in k.get('rejected', []) if _k(r) != a]
    return changed


def apply_profile(p):
    """Profilin rehberine ve klan kopyasına bekleyen olaylar (oturum açılırken, rehber okunurken) -> değişti mi."""
    new_ = events_since(p.d.get('bot_name_log', 0))
    if not new_:
        return False
    changed = False
    with p.lock:
        r = p.d.get('contacts') or {}
        for name in ('arkadas', 'incoming', 'outgoing', 'declined', 'blocked'):
            if isinstance(r.get(name), list):
                x = apply_list(r[name], new_)
                if x is not None:
                    r[name], changed = x, True
        k = p.d.get('klan')
        if k and 'members' in k:
            s = apply_clan(k, new_)
            if s == 'vacant':
                p.d['klan'] = None
                p.d['pilot'].update(clanId=0, clanTag='')
            changed = changed or bool(s)
        p.d['bot_name_log'] = new_[-1]['n']
        p.dirty = True
    return changed


def apply_clans(KL):
    """Asıl klan kayıtlarına (klan.KLANLAR) bekleyen olaylar; boşalan klan silinir (diplomasisi de) -> değişen klanlar."""
    new_ = events_since(KL.BOT_NAME_N)
    if not new_:
        return []
    out = []
    with KL.LOCK:
        for cid, k in list(KL.CLANS.items()):
            s = apply_clan(k, new_)
            if s == 'vacant':
                KL.CLANS.pop(cid, None)
                KL.DELETED[cid] = k.get('anahtar')
                for c in KL.CLANS.values():
                    c['diplomacy'] = [d for d in c.get('diplomacy', []) if d['klan'] != cid]
                    c['diplomacy_requests'] = [r for r in c.get('diplomacy_requests', []) if cid not in (r['from_clan'], r['to'])]
            elif s:
                out.append(k)
        KL.BOT_NAME_N = new_[-1]['n']
    for k in out:
        KL.changed(k)                                    # sürüm artar, bağlı üyelerin kopyaları yenilenir
    KL.save()
    return out
