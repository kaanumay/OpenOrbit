"""Arkadaş sunucusunda haritaların paylaşımı (cok_oyunculu.py; panelin "Arkadaşlarınla Oyna" sayfası).

Tek oyunculuda her oturumun kendi dünyası (dunya.World) vardır. Arkadaş sunucusunda aynı normal haritadaki oyuncuların dünyaları
bir Harita'yı paylaşır: uzaylılar, kutular, cevherler, bekleyen doğmalar, uzaylı kimlik sayacı, takvimin harita etkinliği ve dünya
kilidi ortaktır (dünyaların döngü adımları sırayla işler). Her dünya kendi kahramanını sürer: konum, hedef, ateş, etkiler, P.E.T.,
portallar, ödüller (uzaylıyı kim öldürürse ödül onun; grupta aynı haritadaki üyelerle paylaşılır: dunya.World.paydaslar, grup.py).
  - Uzaylının yapay zekâsını (dunya.think), yeteneklerini (uzayli.py), zehir ve onarımını "sahibi" olan dünya işler: savaştığı
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
SAHIP_SN = 0.1                # sahiplerin yeniden hesaplanma aralığı (döngü adımı)
# yansıtılan mesajlar -> içlerinde geçen gemi kimliklerinin alanları (alıcı hepsini tanıyorsa gider; 0: çevre, ör. radyasyon)
YANSIYAN = {'MoveCommand': ('userId',), 'AttackLaserRunCommand': ('attackerId', 'targetId'),
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
OYUNCU_KARMA = ('M', 'F')
SPREY = 69                    # AssetCreateCommand türü (savas_esya.SPRAY_ASSET)
# eski metinle giden görseller (eski_protokol.py) -> içlerindeki gemi kimliklerinin parça sırası (ilk sayı listesi: kalan parçaların
# hepsi kimlik): roket 0|v|saldıran|hedef|…, Smart Bomb / Insta-Shield / EMP 0|n|SMB|uid, gemi yeteneği 0|n|SD|A|etki|kalıcı|
# etkinleştiren[|hedef], teknoloji 0|n|A|S|kod|uid, Chain Impulse 0|n|ECI|1|saldıran|hedef…, donma/yavaşlama 0|n|fx|start|tür|uid,
# Battle Repair Bot/NPC Nuke şok dalgası 0|n|BT|uid, 0|n|NNK|uid, toplama ışını 0|A|SLA|kip|birim, iyileşme sayısı 0|A|HL|iyileştiren|
# hedef|… ve görünmezlik 0|n|INV|uid|açık
ESKI = {('0', 'v'): (2, 3), ('0', 'n', 'SMB'): (3,), ('0', 'n', 'ISH'): (3,), ('0', 'n', 'EMP'): (3,),
        ('0', 'n', 'SD'): (6, [7]), ('0', 'n', 'A', 'S'): (5,), ('0', 'n', 'ECI'): (4, [5]), ('0', 'n', 'fx'): (5,),
        ('0', 'n', 'BT'): (3,), ('0', 'n', 'NNK'): (3,), ('0', 'A', 'SLA'): (4,), ('0', 'A', 'HL'): (3, 4), ('0', 'n', 'INV'): (3,)}

REG = threading.Lock()
HARITALAR = {}                # harita kimliği -> Harita (kullanan dünya varken)


def al(map_id):
    """Haritanın ortak durumu (yoksa kurulur). Dünya kurulurken bir kez (World.__init__); dünya durunca birak()."""
    with REG:
        h = HARITALAR.get(str(map_id))
        if h is None:
            h = HARITALAR[str(map_id)] = Harita(str(map_id))
        h.ref += 1
        return h


class Harita:
    def __init__(self, map_id):
        self.map_id = map_id
        self.lock = threading.RLock()
        self.npcs, self.boxes, self.ores = {}, {}, {}
        self.pending, self.ore_fields = [], []
        self.next_uid = UID_BASE
        self.uyeler = []              # döngüsü çalışan dünyalar, girişe göre (ilki lider)
        self.etkinlik = None          # takvimin harita etkinliği (etkinlik_harita.HaritaEtkinlik; lider sürer)
        self.ref = 0                  # bu haritayı tutan dünyalar (kurulmuş ama henüz girmemiş olanlar dahil)
        self._sahip, self._sahip_an = {}, 0.0

    @property
    def lider(self):
        return self.uyeler[0] if self.uyeler else None

    def katil(self, w):
        """Dünyanın döngüsü başladı (dünya kilidi altında)."""
        if w not in self.uyeler:
            self.uyeler.append(w)
        if self.etkinlik is not None:
            self.etkinlik.w = self.lider
        self._sahip_an = 0.0

    def ayril(self, w):
        """Dünya durdu (harita değişimi, bağlantı koptu) -> kalan üye yoksa True. Ondan savaşan uzaylılar yeniden sahiplenilir."""
        with self.lock:
            if w in self.uyeler:
                self.uyeler.remove(w)
            for n in self.npcs.values():
                if getattr(n, 'foe', None) is w:
                    n.foe = None
            if self.etkinlik is not None and self.lider is not None:
                self.etkinlik.w = self.lider
            self._sahip_an = 0.0
            return not self.uyeler

    def birak(self):
        """Dünya bu haritayı bıraktı (bir kez): kimse tutmuyorsa kayıttan çıkar."""
        with REG:
            self.ref -= 1
            if self.ref <= 0 and HARITALAR.get(self.map_id) is self:
                del HARITALAR[self.map_id]

    # ------------------------------------------------------------ uzaylıların sahipleri
    def sahipler(self, now):
        """uzaylı kimliği -> yapay zekâsını işleyen dünya. Savaşan uzaylı savaştığı oyuncunun (o haritadaysa); öteki uzaylılar
        ulaşılabilir en yakın oyuncunun (ölü, atlamada, güvenli bölgede, gizli olmayan; kimse değilse en yakının)."""
        if now - self._sahip_an < SAHIP_SN:
            return self._sahip
        uyeler = [w for w in self.uyeler if w.running]
        pos = {w: w.hero_pos(now) for w in uyeler}
        acik = {w: w.ulasilir(now) for w in uyeler}
        out = {}
        for n in self.npcs.values():
            f = getattr(n, 'foe', None)
            if not (n.engaged and f in pos):
                nx, ny = n.mover.pos(now)
                f = min(uyeler, key=lambda w: (not acik[w], (pos[w][0] - nx) ** 2 + (pos[w][1] - ny) ** 2), default=None)
                n.foe = f
            out[n.id] = f
        self._sahip, self._sahip_an = out, now
        return out

    def sahibi_mi(self, w, n, now):
        """Uzaylının yapay zekâsını bu dünya mı işler (yeni doğan, henüz hesaplanmamış uzaylı: lider)."""
        o = self.sahipler(now).get(n.id)
        return (o if o is not None else self.lider) is w

    # ------------------------------------------------------------ mesajlar
    def yansit(self, kaynak, msgs):
        """Kaynak dünyanın herkese görünen mesajları öteki üyelere (tanıdıkları gemilerinkiler)."""
        out = [(m, kimlikler(m)) for m in msgs if not (m[0] == 'VisualModifierCommand' and m[1].get('modifier') == FLASHLIGHT)]
        out = [(m, ids) for m, ids in out if ids is not None]
        if not out:
            return
        for w in self.uyeler:
            if w is kaynak or not w.running:
                continue
            mine = [m for m, ids in out if all(w.tanir(x) for x in ids)]
            if mine:
                w.teslim(mine)

    def hareket(self, kaynak, x, y, ms):
        """Kahraman hareket etti: onu gören oyunculara MoveCommand (oyuncunun kendisine gitmez; istemci kendisi yürütür)."""
        m = ('MoveCommand', dict(userId=kaynak.hid, x=int(x), y=int(y), timeToTarget=int(ms)))
        for w in self.uyeler:
            if w is not kaynak and w.running and kaynak.hid in w.oyuncular:
                w.teslim([m])

    def gorunurluk(self, w, now, hx, hy, gorus, birakma):
        """Öteki oyuncuların w'nin istemcisindeki gemileri: görüşe gireni göster, çıkanı (ölen, atlayan, gizlenen, ayrılan, görünümü
        değişen) kaldır -> mesajlar. Grup üyesi haritanın neresinde olursa olsun görünür (grup.py)."""
        cur = {}
        for m in self.uyeler:
            if m is w or not m.running or m.hero_dead or m.jumping or m.reload_pending or (m.gizli(now) and w.target != m.hid):
                continue                   # gizlenen, onu seçmiş olanda kalır (vurulabilir: oyuncu_savas.attack_error)
            mx, my = m.hero_pos(now)
            lim = birakma if m.hid in w.oyuncular else gorus
            if math.hypot(mx - hx, my - hy) <= lim or w.grup_uyesi(m.hid):
                cur[m.hid] = m
        msgs = []
        for uid in list(w.oyuncular):
            m = cur.get(uid)
            if m is None or w.oyuncular[uid] != imza(w, m):
                del w.oyuncular[uid]
                msgs.append(('ShipRemoveCommand', {'userId': uid}))
        for uid in list(w.petler):         # P.E.T. sahibiyle görünür; sahibi kalkınca ya da P.E.T. değişince (durdu, yeni tasarım) kalkar
            if uid not in w.oyuncular or w.petler[uid] != pet_imza(w, cur[uid]):
                msgs.append(('ShipRemoveCommand', {'userId': w.petler.pop(uid)[0]}))
        for uid, m in cur.items():
            if uid not in w.oyuncular:
                w.oyuncular[uid] = sig = imza(w, m)
                msgs += [(n, dict(f, clanDiplomacy=dict(f['clanDiplomacy'], type=sig[1]))) if n == 'ShipCreateCommand' and f.get('userId') == m.hid
                         else (n, f) for n, f in m.gorunum_msgs(now)]
        for uid, m in cur.items():
            sig = pet_imza(w, m)
            if sig and uid not in w.petler:
                w.petler[uid] = sig
                msgs += [(n, dict(f, clanRelationship=dict(f['clanRelationship'], type=sig[-1]))) if n == 'PetActivationCommand' else (n, f)
                         for n, f in m.pet.view_msgs(now)]
        return msgs


def imza(w, m):
    """m'nin w'nin istemcisindeki gemisi: görünümü ve klan ilişkisi (bakana göre; diplomasi değişince gemi yeniden kurulur)."""
    import klan as KL
    return m.imza(), KL.iliski(w.p, m.p)


def pet_imza(w, m):
    """m'nin uzaydaki P.E.T.'i w'nin istemcisinde: kimlik, görünüm, ad, seviye ve klan ilişkisi; P.E.T. uzayda değilse None."""
    pet = m.pet
    if not (pet and pet.active and pet.w is m):
        return None
    import klan as KL
    return pet.pid, pet.look, pet.d['ad'], pet.d['seviye'], KL.iliski(w.p, m.p)


def kimlikler(m):
    """Yansıtılan mesajın gemi kimlikleri (alıcı hepsini tanımalı) ya da None (yansıtılmaz)."""
    if m[0] in YANSIYAN:
        ids = []
        for k in YANSIYAN[m[0]]:
            v = m[1].get(k)
            ids += v if isinstance(v, list) else [v]
        return ids
    if m[0] in ('AddMineCommand', 'RemoveMineCommand', 'AddFireworkBoxCommand'):
        return [] if str(m[1].get('hash', '')).startswith(OYUNCU_KARMA) else None
    if m[0] in ('AssetCreateCommand', 'AssetRemoveCommand'):
        kind = m[1].get('type') or m[1].get('assetType') or {}
        return [] if kind.get('typeValue') == SPREY else None
    if m[0] != 'LegacyModule':
        return None
    parts = str(m[1].get('message', '')).split('|')
    if parts[:3] in (['0', 'n', 'MIN'], ['0', 'n', 'FWG']):          # mayının patlaması, havai fişeklerin ateşlenmesi (karmalarıyla)
        return [] if len(parts) > 3 and all(h.startswith(OYUNCU_KARMA) for h in parts[3:]) else None
    for key, pos in ESKI.items():
        if tuple(parts[:len(key)]) != key:
            continue
        fixed = [i for i in pos if not isinstance(i, list)]
        rest = [j for i in pos if isinstance(i, list) for j in range(i[0], len(parts))]
        try:
            return [int(parts[i]) for i in fixed + rest]
        except (ValueError, IndexError):
            return None
    return None


def ortak_mi(w):
    """Dünya bir ortak haritada mı ve orada başka oyuncu var mı (yansıtma gereksizse atlanır)."""
    return w.ortak is not None and len(w.ortak.uyeler) > 1
