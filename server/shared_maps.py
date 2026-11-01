"""Arkadaş sunucusunda haritaların paylaşımı (multiplayer.py; panelin "Arkadaşlarınla Oyna" sayfası).

Tek oyunculuda her oturumun kendi dünyası (dunya.World) vardır. Arkadaş sunucusunda aynı normal haritadaki oyuncuların dünyaları
bir Harita'yı paylaşır: uzaylılar, kutular, cevherler, bekleyen doğmalar, uzaylı kimlik sayacı, takvimin harita etkinliği ve dünya
kilidi ortaktır (dünyaların döngü adımları sırayla işler). Her dünya kendi kahramanını sürer: konum, hedef, ateş, etkiler, P.E.T.,
portallar, ödüller (uzaylıyı kim öldürürse ödül onun; grupta aynı haritadaki üyelerle paylaşılır: dunya.World.paydaslar, group.py).
  - Uzaylının yapay zekâsını (dunya.think), yeteneklerini (alien.py), zehir ve onarımını "sahibi" olan dünya işler: savaştığı
    oyuncu (vuran oyuncu sahibi olur), savaşmıyorsa ulaşılabilir en yakın oyuncu (sahipler).
  - Haritanın işleri (yeniden doğmalar, süresi biten kutular, zaman çizelgeli uzaylılar, takvimin harita etkinliği) liderin döngüsünde:
    haritaya ilk giren, o çıkınca sıradaki.
  - Herkesin görmesi gereken mesajlar (uzaylının hareketi, lazer ve vuruşlar, patlamalar, görsel etkiler) gönderen dünyadan öteki
    üyelere yansıtılır (yansit); her alıcı yalnız tanıdığı gemilerinkini alır (World.tanir).
  - Oyuncular birbirini görüş mesafesinde, grup üyeleri haritanın her yerinde görür (gorunurluk): ShipCreateCommand, unvan, dronlar
    ve modüller (kayıttaki başka oyuncunun mesajları; game.Session.gorunum), kahramanın hareketi MoveCommand olarak (hareket). Ölü,
    atlamadaki ya da gizli oyuncu görünmez.
Kapı, mod ve etkinlik haritaları (oturumun kendi koşusu olanlar) paylaşılmaz: her oyuncunun kendi kopyası (game.Session.start_world).
Son oyuncu çıkınca harita durumu tek oyunculudaki gibi saklanır (dunya.WORLD_CACHE) ve ortak durum bırakılır.
"""
import math, threading

UID_BASE = 150300000          # uzaylı kimliklerinin başlangıcı (dunya.World'ünkiyle aynı)
FLASHLIGHT = 62               # el feneri (dunya.FLASHLIGHT): oyuncunun kendi ekranının etkisi, yansıtılmaz
OWNER_SEC = 0.1                # sahiplerin yeniden hesaplanma aralığı (döngü adımı)
# yansıtılan mesajlar -> içlerinde geçen gemi kimliklerinin alanları (alıcı hepsini tanıyorsa gider; 0: çevre, ör. radyasyon)
REFLECTED = {'MoveCommand': ('userId',), 'AttackLaserRunCommand': ('attackerId', 'targetId'),
            'AttackHitCommand': ('attackerId', 'victimId'), 'AttackMissedCommand': ('targetUserId',),
            'ShipDestroyedCommand': ('destroyedUserId',), 'VisualModifierCommand': ('userId',),
            # lazerin bitişi: istemci AttackLaserRunCommand'da saldıranın hedefini kurar (ShipInfo.Target) ve gemiyi ona döndürür;
            # bu gelmezse öteki oyuncunun gemisi hedefe dönük kalıyor, burnu dönmüyor ve motor efekti çıkmıyordu (AttackAbortLaser.Run)
            'AttackAbortLaserCommand': ('uid',),
            # emote, seviye atlama, gemi yetenekleri, parçacık topu, Hellstorm (liste alanları: içindeki her kimlik)
            'EmoteActivationCommand': ('userId',), 'LevelUpCommand': ('uid',),
            'AbilityEffectActivationCommand': ('activatorId', 'targetIds'), 'AbilityEffectDeActivationCommand': ('activatorId', 'targetIds'),
            'AbilityStartCommand': ('activatorId',), 'AbilityStopCommand': ('activatorId', 'targetIds'),
            'PlayVisualEffectCommand': ('activatorId', 'targetIds'), 'CannonAttackCommand': ('attackerId', 'attackedId'),
            'HellstormAttackCommand': ('attackerId', 'targetId')}
# oyuncunun mayınları ve havai fişekleri (savas_esya.py; karmaları M<kimlik>_<sıra>, F<kimlik>_<sıra>) ve spreyi herkese görünür;
# uzaylının mayını (U…) yalnız onu kuran dünyanın kahramanını vurur, yansıtılmaz
PLAYER_HASH = ('M', 'F')
SPRAY = 69                    # AssetCreateCommand türü (savas_esya.SPRAY_ASSET)
# eski metinle giden görseller (eski_protokol.py) -> içlerindeki gemi kimliklerinin parça sırası (ilk sayı listesi: kalan parçaların
# hepsi kimlik): roket 0|v|saldıran|hedef|…, Smart Bomb / Insta-Shield / EMP 0|n|SMB|uid, gemi yeteneği 0|n|SD|A|etki|kalıcı|
# etkinleştiren[|hedef], teknoloji 0|n|A|S|kod|uid, Chain Impulse 0|n|ECI|1|saldıran|hedef…, donma/yavaşlama 0|n|fx|start|tür|uid,
# Battle Repair Bot/NPC Nuke şok dalgası 0|n|BT|uid, 0|n|NNK|uid, toplama ışını 0|A|SLA|kip|birim, iyileşme sayısı 0|A|HL|iyileştiren|
# hedef|… ve görünmezlik 0|n|INV|uid|açık
LEGACY = {('0', 'v'): (2, 3), ('0', 'n', 'SMB'): (3,), ('0', 'n', 'ISH'): (3,), ('0', 'n', 'EMP'): (3,),
        ('0', 'n', 'SD'): (6, [7]), ('0', 'n', 'A', 'S'): (5,), ('0', 'n', 'ECI'): (4, [5]), ('0', 'n', 'fx'): (5,),
        ('0', 'n', 'BT'): (3,), ('0', 'n', 'NNK'): (3,), ('0', 'A', 'SLA'): (4,), ('0', 'A', 'HL'): (3, 4), ('0', 'n', 'INV'): (3,)}

REG = threading.Lock()
MAPS = {}                # harita kimliği -> Harita (kullanan dünya varken)


def take(map_id):
    """Haritanın ortak durumu (yoksa kurulur). Dünya kurulurken bir kez (World.__init__); dünya durunca birak()."""
    with REG:
        h = MAPS.get(str(map_id))
        if h is None:
            h = MAPS[str(map_id)] = Map(str(map_id))
        h.ref += 1
        return h


class Map:
    def __init__(self, map_id):
        self.map_id = map_id
        self.lock = threading.RLock()
        self.npcs, self.boxes, self.ores = {}, {}, {}
        self.pending, self.ore_fields = [], []
        self.next_uid = UID_BASE
        self.members = []              # döngüsü çalışan dünyalar, girişe göre (ilki lider)
        self.event = None          # takvimin harita etkinliği (etkinlik_harita.HaritaEtkinlik; lider sürer)
        self.ref = 0                  # bu haritayı tutan dünyalar (kurulmuş ama henüz girmemiş olanlar dahil)
        self._owner, self._owner_at = {}, 0.0

    @property
    def leader(self):
        return self.members[0] if self.members else None

    def killer(self, w):
        """Dünyanın döngüsü başladı (dünya kilidi altında)."""
        if w not in self.members:
            self.members.append(w)
        if self.event is not None:
            self.event.w = self.leader
        self._owner_at = 0.0

    def detach(self, w):
        """Dünya durdu (harita değişimi, bağlantı koptu) -> kalan üye yoksa True. Ondan savaşan uzaylılar yeniden sahiplenilir."""
        with self.lock:
            if w in self.members:
                self.members.remove(w)
            for n in self.npcs.values():
                if getattr(n, 'foe', None) is w:
                    n.foe = None
            if self.event is not None and self.leader is not None:
                self.event.w = self.leader
            self._owner_at = 0.0
            return not self.members

    def release(self):
        """Dünya bu haritayı bıraktı (bir kez): kimse tutmuyorsa kayıttan çıkar."""
        with REG:
            self.ref -= 1
            if self.ref <= 0 and MAPS.get(self.map_id) is self:
                del MAPS[self.map_id]

    # ------------------------------------------------------------ uzaylıların sahipleri
    def owners(self, now):
        """uzaylı kimliği -> yapay zekâsını işleyen dünya. Savaşan uzaylı savaştığı oyuncunun (o haritadaysa); öteki uzaylılar
        ulaşılabilir en yakın oyuncunun (ölü, atlamada, güvenli bölgede, gizli olmayan; kimse değilse en yakının)."""
        if now - self._owner_at < OWNER_SEC:
            return self._owner
        members = [w for w in self.members if w.running]
        pos = {w: w.hero_pos(now) for w in members}
        is_open = {w: w.reachable(now) for w in members}
        out = {}
        for n in self.npcs.values():
            f = getattr(n, 'foe', None)
            if not (n.engaged and f in pos):
                nx, ny = n.mover.pos(now)
                f = min(members, key=lambda w: (not is_open[w], (pos[w][0] - nx) ** 2 + (pos[w][1] - ny) ** 2), default=None)
                n.foe = f
            out[n.id] = f
        self._owner, self._owner_at = out, now
        return out

    def is_owner(self, w, n, now):
        """Uzaylının yapay zekâsını bu dünya mı işler (yeni doğan, henüz hesaplanmamış uzaylı: lider)."""
        o = self.owners(now).get(n.id)
        return (o if o is not None else self.leader) is w

    # ------------------------------------------------------------ mesajlar
    def mirror(self, source, msgs):
        """Kaynak dünyanın herkese görünen mesajları öteki üyelere (tanıdıkları gemilerinkiler)."""
        out = [(m, uid_list(m)) for m in msgs if not (m[0] == 'VisualModifierCommand' and m[1].get('modifier') == FLASHLIGHT)]
        out = [(m, ids) for m, ids in out if ids is not None]
        if not out:
            return
        for w in self.members:
            if w is source or not w.running:
                continue
            mine = [m for m, ids in out if all(w.knows(x) for x in ids)]
            if mine:
                w.deliver(mine)

    def movement(self, source, x, y, ms):
        """Kahraman hareket etti: onu gören oyunculara MoveCommand (oyuncunun kendisine gitmez; istemci kendisi yürütür)."""
        m = ('MoveCommand', dict(userId=source.hid, x=int(x), y=int(y), timeToTarget=int(ms)))
        for w in self.members:
            if w is not source and w.running and source.hid in w.players:
                w.deliver([m])

    def visibility(self, w, now, hx, hy, vision, release):
        """Öteki oyuncuların w'nin istemcisindeki gemileri: görüşe gireni göster, çıkanı (ölen, atlayan, gizlenen, ayrılan, görünümü
        değişen) kaldır -> mesajlar. Grup üyesi haritanın neresinde olursa olsun görünür (group.py)."""
        cur = {}
        for m in self.members:
            if m is w or not m.running or m.hero_dead or m.jumping or m.reload_pending or (m.hidden(now) and w.target != m.hid):
                continue                   # gizlenen, onu seçmiş olanda kalır (vurulabilir: oyuncu_savas.attack_error)
            mx, my = m.hero_pos(now)
            lim = release if m.hid in w.players else vision
            if math.hypot(mx - hx, my - hy) <= lim or w.is_group_member(m.hid):
                cur[m.hid] = m
        msgs = []
        for uid in list(w.players):
            m = cur.get(uid)
            if m is None or w.players[uid] != signature(w, m):
                del w.players[uid]
                msgs.append(('ShipRemoveCommand', {'userId': uid}))
        for uid in list(w.pets):         # P.E.T. sahibiyle görünür; sahibi kalkınca ya da P.E.T. değişince (durdu, yeni tasarım) kalkar
            if uid not in w.players or w.pets[uid] != pet_signature(w, cur[uid]):
                msgs.append(('ShipRemoveCommand', {'userId': w.pets.pop(uid)[0]}))
        for uid, m in cur.items():
            if uid not in w.players:
                w.players[uid] = sig = signature(w, m)
                msgs += [(n, dict(f, clanDiplomacy=dict(f['clanDiplomacy'], type=sig[1]))) if n == 'ShipCreateCommand' and f.get('userId') == m.hid
                         else (n, f) for n, f in m.gorunum_msgs(now)]
        for uid, m in cur.items():
            sig = pet_signature(w, m)
            if sig and uid not in w.pets:
                w.pets[uid] = sig
                msgs += [(n, dict(f, clanRelationship=dict(f['clanRelationship'], type=sig[-1]))) if n == 'PetActivationCommand' else (n, f)
                         for n, f in m.pet.view_msgs(now)]
        return msgs


def signature(w, m):
    """m'nin w'nin istemcisindeki gemisi: görünümü ve klan ilişkisi (bakana göre; diplomasi değişince gemi yeniden kurulur)."""
    import clan as KL
    return m.signature(), KL.relation(w.p, m.p)


def pet_signature(w, m):
    """m'nin uzaydaki P.E.T.'i w'nin istemcisinde: kimlik, görünüm, ad, seviye ve klan ilişkisi; P.E.T. uzayda değilse None."""
    pet = m.pet
    if not (pet and pet.active and pet.w is m):
        return None
    import clan as KL
    return pet.pid, pet.look, pet.d['ad'], pet.d['seviye'], KL.relation(w.p, m.p)


def uid_list(m):
    """Yansıtılan mesajın gemi kimlikleri (alıcı hepsini tanımalı) ya da None (yansıtılmaz)."""
    if m[0] in REFLECTED:
        ids = []
        for k in REFLECTED[m[0]]:
            v = m[1].get(k)
            ids += v if isinstance(v, list) else [v]
        return ids
    if m[0] in ('AddMineCommand', 'RemoveMineCommand', 'AddFireworkBoxCommand'):
        return [] if str(m[1].get('hash', '')).startswith(PLAYER_HASH) else None
    if m[0] in ('AssetCreateCommand', 'AssetRemoveCommand'):
        kind = m[1].get('type') or m[1].get('assetType') or {}
        return [] if kind.get('typeValue') == SPRAY else None
    if m[0] != 'LegacyModule':
        return None
    parts = str(m[1].get('message', '')).split('|')
    if parts[:3] in (['0', 'n', 'MIN'], ['0', 'n', 'FWG']):          # mayının patlaması, havai fişeklerin ateşlenmesi (karmalarıyla)
        return [] if len(parts) > 3 and all(h.startswith(PLAYER_HASH) for h in parts[3:]) else None
    for key, pos in LEGACY.items():
        if tuple(parts[:len(key)]) != key:
            continue
        fixed = [i for i in pos if not isinstance(i, list)]
        rest = [j for i in pos if isinstance(i, list) for j in range(i[0], len(parts))]
        try:
            return [int(parts[i]) for i in fixed + rest]
        except (ValueError, IndexError):
            return None
    return None


def is_shared(w):
    """Dünya bir ortak haritada mı ve orada başka oyuncu var mı (yansıtma gereksizse atlanır)."""
    return w.shared is not None and len(w.shared.members) > 1
