"""Somut botun etkin eşyaları ve görselleri: oyuncunun gönderdiği mesajların aynısı botun kimliğiyle (teknoloji.py, savas_esya.py).

  Backup Shields   0|n|A|S|SBU|bot                kalkan +75.000
  Battle Repair    VisualModifierCommand 60 açık/kapalı, süre boyunca saniyede can
  Energy Leech     VisualModifierCommand 59, lazer hasarının %10'u cana (15 dk)
  Chain Impulse    0|n|ECI|1|bot|hedefler          yalnız kalkana hasar (istemci: "chain reaction of shield damage")
  Insta-Shield     0|n|ISH|bot                     3 sn dokunulmaz; 10 ACM-01 mayını ya da 100 Xenomit
  Smart Bomb       0|n|SMB|bot                     600 birimde düşman gemilere can ve kalkanın %20'si; 10 mayın ya da 100 Xenomit
  EMP-01           0|n|EMP|bot                     ona kilitlenen oyuncunun seçimi düşer (uzaylıların hedefi sıfırlanır)
  gizlenme CPU'su  0|n|INV|bot|1 / 0              görünmez ve vurulamaz; ateş edince görünür olur
  AIM CPU          atış başına 10 Xenomit: ıska oranı %25 / %50 az
Hepsi botun izinlerine (teknoloji, ekstra, mayin) ve stoğuna bağlı; bekleme süreleri oyuncunun değerleri.
"""
import math, random, time

from eski_protokol import legacy
from . import katalog as K

SE = K.ESYA['savas_esyalari']
TEK = K.ESYA['teknoloji']['esyalar']
EMP = 'ammunition_specialammo_emp-01'
XENOMIT = '3'


def _yayin(w, msgs, *uids):
    from . import govde as BG
    BG._yayin(w, msgs, *uids)


def gorsel(w, n, mod, acik):
    _yayin(w, [('VisualModifierCommand', dict(userId=n.id, modifier=mod, attribute=0, additionalAttribute='', count=0,
                                              activated=acik))], n.id)


def hazir(n, ad, now):
    return now >= n.__dict__.get('cd_' + ad, 0)


def bekle(n, ad, now, sn):
    n.__dict__['cd_' + ad] = now + sn


def xenomit(b):
    return b.k.get('kargo', {}).get(XENOMIT, 0)


def xenomit_harca(b, n):
    k = b.k.setdefault('kargo', {})
    if k.get(XENOMIT, 0) < n:
        return False
    k[XENOMIT] -= n
    if not k[XENOMIT]:
        del k[XENOMIT]
    return True


def bedel(b, c):
    """Insta-Shield ve Smart Bomb'un bedeli: 10 ACM-01 mayını ya da 100 Xenomit -> ödendi mi."""
    from . import silah as SL
    if SL.stok(b).get(c['mayin'], 0) >= c['mayin_adet']:
        return SL.harca(b, c['mayin'], c['mayin_adet']) == c['mayin_adet']
    return xenomit_harca(b, c['xenomit'])


# ------------------------------------------------------------------------------------------------------------ teknoloji
def backup_shields(w, n, now):
    from . import teknoloji as TK
    v = TEK['tech_backup-shields']
    if not hazir(n, 'sbu', now) or not TK.kullan(n.bot, 'tech_backup-shields'):
        return False
    n.shield += v['kalkan']
    bekle(n, 'sbu', now, v['bekleme_sn'])
    _yayin(w, [legacy('0|n|A|S|%s|%d' % (v['eski'], n.id))], n.id)
    return True


def battle_repair(w, n, now, can):
    from . import teknoloji as TK
    v = TEK['tech_battle-repair-bot']
    if not hazir(n, 'brb', now) or not TK.kullan(n.bot, 'tech_battle-repair-bot'):
        return False
    bekle(n, 'brb', now, v['bekleme_sn'])
    gorsel(w, n, v['gorsel'], True)
    for i in range(int(v['sure_sn'])):
        def onar():
            if n.alive:
                n.hp = min(can, n.hp + v['can_sn'])
        w.later(i + 1, onar)
    w.later(v['sure_sn'], lambda: gorsel(w, n, v['gorsel'], False) if n.alive else None)
    return True


def energy_leech(w, n, now):
    """Zor savaşta (dayanıklı uzaylı ya da PvP) etkinleştirilir; süre boyunca lazer hasarının %10'u cana (leech_payi)."""
    from . import teknoloji as TK
    v = TEK['tech_energy-leech']
    if now < n.__dict__.get('leech_bitis', 0) or not hazir(n, 'ela', now) or not TK.kullan(n.bot, 'tech_energy-leech'):
        return
    n.leech_bitis = now + v['sure_sn']
    bekle(n, 'ela', now, v['bekleme_sn'] + v['sure_sn'])
    gorsel(w, n, v['gorsel'], True)
    w.later(v['sure_sn'], lambda: gorsel(w, n, v['gorsel'], False) if n.alive else None)


def leech(n, dmg, can, now):
    if now < n.__dict__.get('leech_bitis', 0):
        n.hp = min(can, n.hp + dmg * TEK['tech_energy-leech']['lazer_can'])


def chain_impulse(w, n, now):
    """700 birim içinde 3+ uzaylı: en yakın 7'sinin kalkanına 10.000 (beklemesi 60 sn)."""
    from . import teknoloji as TK
    v = TEK['tech_chain-impulse']
    if not hazir(n, 'eci', now) or TK._stok(n.bot).get('tech_chain-impulse', 0) <= 0:
        return
    nx, ny = n.mover.pos(now)
    yakin = sorted(((math.hypot(m.mover.pos(now)[0] - nx, m.mover.pos(now)[1] - ny), m) for m in list(w.npcs.values())
                    if m.bot is None and m.alive and not m.d.get('dost')), key=lambda x: x[0])
    yakin = [m for dd, m in yakin if dd <= v['yaricap']][:v['hedef']]
    if len(yakin) < 3 or not TK.kullan(n.bot, 'tech_chain-impulse'):
        return
    bekle(n, 'eci', now, v['bekleme_sn'])
    _yayin(w, [legacy('0|n|ECI|1|%d|%s' % (n.id, '|'.join(str(m.id) for m in yakin)))], n.id)
    from . import govde as BG
    for m in yakin:
        BG.npc_vur(w, n, m, min(v['hasar'], int(m.shield)), now, 5, kalkan=True)


# ------------------------------------------------------------------------------------------------------------ etkin CPU'lar
def insta_shield(w, n, now):
    from . import ekstra as EK
    c = SE['aninda_kalkan']
    b = n.bot
    if not EK.var(b, EK.ISH) or not b.izin.get('ekstra', True) or not hazir(n, 'ish', now) or not bedel(b, c):
        return False
    n.dokunulmaz = now + c['sure_sn']
    bekle(n, 'ish', now, c['bekleme_sn'])
    _yayin(w, [legacy('0|n|ISH|%d' % n.id)], n.id)
    return True


def smart_bomb(w, n, now, dusmanlar):
    """dusmanlar: [(kahraman dünyası ya da None, bot gemisi ya da None)] yarıçapta."""
    from . import ekstra as EK
    c = SE['akilli_bomba']
    b = n.bot
    if not dusmanlar or not EK.var(b, EK.SMB) or not b.izin.get('ekstra', True) or not hazir(n, 'smb', now) or not bedel(b, c):
        return False
    bekle(n, 'smb', now, c['bekleme_sn'])
    _yayin(w, [legacy('0|n|SMB|%d' % n.id)], n.id)
    from . import govde as BG
    for o, t in dusmanlar:
        if o is not None:
            g = o.p.d['gemi']
            o.send(o.hurt_hero(int(g.get('hitPoints', 0) * c['can'] + g.get('shield', 0) * c['kalkan']), killer=n, cause=0,
                               source_asset=True, now=now))
        elif t is not None:
            BG.bot_hasar(w, t, int(t.hp * c['can'] + t.shield * c['kalkan']), n.id, now, katil_bot=b)
    b.ist('smart_bomb')
    return True


def emp(w, n, now):
    """Ona kilitlenen oyuncunun seçimi düşer; botu hedefleyen uzaylılar şaşırır."""
    from . import silah as SL
    c = SE['emp']
    b = n.bot
    x, y = n.mover.pos(now)
    if SL.stok(b).get(EMP, 0) <= 0 or not hazir(n, 'emp', now) or w.in_pvp_peace(x, y) or w.target != n.id:
        return False
    SL.harca(b, EMP, 1)
    bekle(n, 'emp', now, c['bekleme_sn'])
    _yayin(w, [legacy('0|n|EMP|%d' % n.id)], n.id)
    if w.attacking:
        w.laser_stop()                     # istemcinin lazeri ve kırmızı hedef vurgusu da kalksın
    w.target, w.attacking = None, False
    w.send([('ShipDeselectionCommand', {})])
    n.emp_kilit = now + c['saskinlik_sn']      # o süre yeniden seçilemez (dunya.select; oyuncu bildirimi 2026-10-31: hemen seçiliyordu)
    for m in w.npcs.values():
        if m.bot is None and m.bot_hedef == n.id:
            m.bot_hedef = None
            m.next_think = now + c['saskinlik_sn']
    b.ist('emp')
    return True


def gizlen(w, n, now):
    from . import ekstra as EK
    if n.__dict__.get('gizli') or not EK.gizlen(n.bot):
        return False
    n.gizli = True
    _yayin(w, [legacy('0|n|INV|%d|1' % n.id)], n.id)
    # onu seçmiş oyuncunun seçimi ve saldırısı sürer, vuruşlar işler (wiki: "Cloaked ships can still be attacked (if targeted)";
    # oyuncu bildirimi 2026-10-31: gizlenen bota saldırılamıyordu)
    n.bot.ist('gizlendi')
    return True


def gorun(w, n):
    if n.__dict__.get('gizli'):
        n.gizli = False
        _yayin(w, [legacy('0|n|INV|%d|0' % n.id)], n.id)


def korumali(n, now):
    """Vurulamaz mı: Insta-Shield süresinde ya da gizliyken."""
    return now < n.__dict__.get('dokunulmaz', 0) or n.__dict__.get('gizli', False)


def nisan(n, isabet, zor):
    """AIM CPU: zor hedefte (PvP ya da dayanıklı uzaylı) atış başına 10 Xenomit, ıska oranı azalır -> yeni isabet olasılığı."""
    from . import ekstra as EK
    b = n.bot
    cpu = next((c for c in (EK.AIM2, EK.AIM1) if EK.var(b, c)), None)
    if not cpu or not zor or not b.izin.get('ekstra', True) or not xenomit_harca(b, SE['nisan_cpu']['xenomit']):
        return isabet
    return 1 - (1 - isabet) * (1 - K.ESYA['ekstralar'][cpu]['nisan'])


# ------------------------------------------------------------------------------------------------------------ karar
def savas(w, n, now, d, oran, saldiranlar):
    """dusun'un savaş anı: tehlikede savunma (Insta-Shield, Backup Shields, Battle Repair), yakın düşmana Smart Bomb, zor savaşta
    Energy Leech -> can/kalkan değiştiyse True."""
    from . import govde as BG
    oyuncu_ya_da_bot = [u for u in saldiranlar if BG._oyuncu(w, u) is not None or (u in w.npcs and w.npcs[u].bot is not None)]
    degisti = False
    if saldiranlar and oran < 0.35 and oyuncu_ya_da_bot:
        degisti |= insta_shield(w, n, now)
    if saldiranlar and oran < 0.4:
        degisti |= backup_shields(w, n, now) or battle_repair(w, n, now, d['can'])
    if oyuncu_ya_da_bot or (n.hedef is not None and n.hedef in w.npcs and w.npcs[n.hedef].bot is not None):
        energy_leech(w, n, now)
        if n.bot.o('saldirganlik') > 0.5:
            x, y = n.mover.pos(now)
            r = SE['akilli_bomba']['yaricap']
            dus = []
            o = BG._oyuncu(w, w.hid)
            if o is not None and not o.hero_dead and BG.oyuncuya_saldirabilir(w, n, o, now) and math.hypot(*(a - c for a, c in zip(o.hero_pos(now), (x, y)))) <= r:
                dus.append((o, None))
            for t in list(w.npcs.values()):
                if t.bot is not None and t is not n and t.bot.firma != n.bot.firma and BG.bota_saldirabilir(w, n, t, now) \
                        and math.hypot(*(a - c for a, c in zip(t.mover.pos(now), (x, y)))) <= r:
                    dus.append((None, t))                 # güvenli bölgedeki ve korunan botlara değil
            if len(dus) >= 1 and random.random() < 0.5:
                smart_bomb(w, n, now, dus)
    return degisti
