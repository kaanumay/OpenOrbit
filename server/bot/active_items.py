"""Somut botun etkin eşyaları ve görselleri: oyuncunun gönderdiği mesajların aynısı botun kimliğiyle (technology.py, combat_items.py).

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

from legacy_protocol import legacy
from . import catalog as K

CIT = K.ITEMS['combat_items']
TECH_DATA = K.ITEMS['technology']['items']
EMP = 'ammunition_specialammo_emp-01'
DCR, RIC = 'ammunition_specialammo_dcr-250', 'ammunition_specialammo_r-ic3'      # yavaşlatma, dondurma (savas_esya.rocket_hit'in etkileri)
SLOWERS = (DCR, RIC)
XENOMIT = '3'


def _broadcast(w, msgs, *uids):
    from . import ship as BG
    BG._broadcast(w, msgs, *uids)


def visual(w, n, mod, is_open):
    _broadcast(w, [('VisualModifierCommand', dict(userId=n.id, modifier=mod, attribute=0, additionalAttribute='', count=0,
                                              activated=is_open))], n.id)


def ready(n, name, now):
    return now >= n.__dict__.get('cd_' + name, 0)


def wait(n, name, now, sec):
    n.__dict__['cd_' + name] = now + sec


def xenomit(b):
    return b.k.get('cargo', {}).get(XENOMIT, 0)


def spend_xenomit(b, n):
    k = b.k.setdefault('cargo', {})
    if k.get(XENOMIT, 0) < n:
        return False
    k[XENOMIT] -= n
    if not k[XENOMIT]:
        del k[XENOMIT]
    return True


def cost(b, c):
    """Insta-Shield ve Smart Bomb'un bedeli: 10 ACM-01 mayını ya da 100 Xenomit -> ödendi mi."""
    from . import weapons as WP
    if WP.stock(b).get(c['mine'], 0) >= c['mine_count']:
        return WP.spend(b, c['mine'], c['mine_count']) == c['mine_count']
    return spend_xenomit(b, c['xenomit'])


# ------------------------------------------------------------------------------------------------------------ teknoloji
def backup_shields(w, n, now):
    from . import technology as TECH
    v = TECH_DATA['tech_backup-shields']
    if not ready(n, 'sbu', now) or not TECH.use(n.bot, 'tech_backup-shields'):
        return False
    n.shield += v['kalkan']
    wait(n, 'sbu', now, v['cooldown_sec'])
    _broadcast(w, [legacy('0|n|A|S|%s|%d' % (v['eski'], n.id))], n.id)
    return True


def battle_repair(w, n, now, hp):
    from . import technology as TECH
    v = TECH_DATA['tech_battle-repair-bot']
    if not ready(n, 'brb', now) or not TECH.use(n.bot, 'tech_battle-repair-bot'):
        return False
    wait(n, 'brb', now, v['cooldown_sec'])
    visual(w, n, v['visual'], True)
    for i in range(int(v['sure_sn'])):
        def repair():
            if n.alive:
                n.hp = min(hp, n.hp + v['hp_sec'])
        w.later(i + 1, repair)
    w.later(v['sure_sn'], lambda: visual(w, n, v['visual'], False) if n.alive else None)
    return True


def energy_leech(w, n, now):
    """Zor savaşta (dayanıklı uzaylı ya da PvP) etkinleştirilir; süre boyunca lazer hasarının %10'u cana (leech_payi)."""
    from . import technology as TECH
    v = TECH_DATA['tech_energy-leech']
    if now < n.__dict__.get('leech_end', 0) or not ready(n, 'ela', now) or not TECH.use(n.bot, 'tech_energy-leech'):
        return
    n.leech_end = now + v['sure_sn']
    wait(n, 'ela', now, v['cooldown_sec'] + v['sure_sn'])
    visual(w, n, v['visual'], True)
    w.later(v['sure_sn'], lambda: visual(w, n, v['visual'], False) if n.alive else None)


def leech(n, dmg, hp, now):
    if now < n.__dict__.get('leech_end', 0):
        n.hp = min(hp, n.hp + dmg * TECH_DATA['tech_energy-leech']['laser_hp'])


def chain_impulse(w, n, now):
    """700 birim içinde 3+ uzaylı: en yakın 7'sinin kalkanına 10.000 (beklemesi 60 sn)."""
    from . import technology as TECH
    v = TECH_DATA['tech_chain-impulse']
    if not ready(n, 'eci', now) or TECH._stock(n.bot).get('tech_chain-impulse', 0) <= 0:
        return
    nx, ny = n.mover.pos(now)
    nearby = sorted(((math.hypot(m.mover.pos(now)[0] - nx, m.mover.pos(now)[1] - ny), m) for m in list(w.npcs.values())
                    if m.bot is None and m.alive and not m.d.get('friendly')), key=lambda x: x[0])
    nearby = [m for dd, m in nearby if dd <= v['radius']][:v['target']]
    if len(nearby) < 3 or not TECH.use(n.bot, 'tech_chain-impulse'):
        return
    wait(n, 'eci', now, v['cooldown_sec'])
    _broadcast(w, [legacy('0|n|ECI|1|%d|%s' % (n.id, '|'.join(str(m.id) for m in nearby)))], n.id)
    from . import ship as BG
    for m in nearby:
        BG.hit_npc(w, n, m, min(v['damage'], int(m.shield)), now, 5, shield=True)


# ------------------------------------------------------------------------------------------------------------ etkin CPU'lar
def insta_shield(w, n, now):
    from . import extras as EX
    c = CIT['insta_shield']
    b = n.bot
    if not EX.var(b, EX.ISH) or not b.permission.get('ekstra', True) or not ready(n, 'ish', now) or not cost(b, c):
        return False
    n.immune_until = now + c['sure_sn']
    wait(n, 'ish', now, c['cooldown_sec'])
    _broadcast(w, [legacy('0|n|ISH|%d' % n.id)], n.id)
    return True


def smart_bomb(w, n, now, enemies):
    """dusmanlar: [(kahraman dünyası ya da None, bot gemisi ya da None)] yarıçapta."""
    from . import extras as EX
    c = CIT['smart_bomb']
    b = n.bot
    if not enemies or not EX.var(b, EX.SMB) or not b.permission.get('ekstra', True) or not ready(n, 'smb', now) or not cost(b, c):
        return False
    wait(n, 'smb', now, c['cooldown_sec'])
    _broadcast(w, [legacy('0|n|SMB|%d' % n.id)], n.id)
    from . import ship as BG
    for o, t in enemies:
        if o is not None:
            g = o.p.d['ship']
            o.send(o.hurt_hero(int(g.get('hitPoints', 0) * c['can'] + g.get('shield', 0) * c['kalkan']), killer=n, cause=0,
                               source_asset=True, now=now))
        elif t is not None:
            BG.bot_damage(w, t, int(t.hp * c['can'] + t.shield * c['kalkan']), n.id, now, killer_bot=b)
    b.ist('smart_bomb')
    return True


def emp(w, n, now):
    """Ona kilitlenen oyuncunun seçimi düşer; botu hedefleyen uzaylılar şaşırır."""
    from . import weapons as WP
    c = CIT['emp']
    b = n.bot
    x, y = n.mover.pos(now)
    if WP.stock(b).get(EMP, 0) <= 0 or not ready(n, 'emp', now) or w.in_pvp_peace(x, y) or w.target != n.id:
        return False
    WP.spend(b, EMP, 1)
    wait(n, 'emp', now, c['cooldown_sec'])
    _broadcast(w, [legacy('0|n|EMP|%d' % n.id)], n.id)
    if w.attacking:
        w.laser_stop()                     # istemcinin lazeri ve kırmızı hedef vurgusu da kalksın
    w.target, w.attacking = None, False
    w.send([('ShipDeselectionCommand', {})])
    n.emp_lock = now + c['daze_sec']      # o süre yeniden seçilemez (dunya.select; oyuncu bildirimi 2026-10-31: hemen seçiliyordu)
    for m in w.npcs.values():
        if m.bot is None and m.bot_target == n.id:
            m.bot_target = None
            m.next_think = now + c['daze_sec']
    b.ist('emp')
    return True


def cloak(w, n, now):
    from . import extras as EX
    if n.__dict__.get('hidden') or not EX.cloak(n.bot):
        return False
    n.hidden = True
    _broadcast(w, [legacy('0|n|INV|%d|1' % n.id)], n.id)
    # onu seçmiş oyuncunun seçimi ve saldırısı sürer, vuruşlar işler (wiki: "Cloaked ships can still be attacked (if targeted)";
    # oyuncu bildirimi 2026-10-31: gizlenen bota saldırılamıyordu)
    n.bot.ist('hidden')
    return True


def decloak(w, n):
    if n.__dict__.get('hidden'):
        n.hidden = False
        _broadcast(w, [legacy('0|n|INV|%d|0' % n.id)], n.id)


def is_protected(n, now):
    """Vurulamaz mı: Insta-Shield süresinde ya da gizliyken."""
    return now < n.__dict__.get('immune_until', 0) or n.__dict__.get('hidden', False)


def aim(n, hit, is_hard):
    """AIM CPU: zor hedefte (PvP ya da dayanıklı uzaylı) atış başına 10 Xenomit, ıska oranı azalır -> yeni isabet olasılığı."""
    from . import extras as EX
    b = n.bot
    cpu = next((c for c in (EX.AIM2, EX.AIM1) if EX.var(b, c)), None)
    if not cpu or not is_hard or not b.permission.get('ekstra', True) or not spend_xenomit(b, CIT['aim_cpu']['xenomit']):
        return hit
    return 1 - (1 - hit) * (1 - K.ITEMS['extras'][cpu]['aim'])


# ------------------------------------------------------------------------------------------------------------ karar
def combat(w, n, now, d, ratio, attackers):
    """dusun'un savaş anı: tehlikede savunma (Insta-Shield, Backup Shields, Battle Repair), yakın düşmana Smart Bomb, zor savaşta
    Energy Leech -> can/kalkan değiştiyse True."""
    from . import ship as BG
    player_or_bot = [u for u in attackers if BG._player(w, u) is not None or (u in w.npcs and w.npcs[u].bot is not None)]
    changed = False
    if attackers and ratio < 0.35 and player_or_bot:
        changed |= insta_shield(w, n, now)
    if attackers and ratio < 0.4:
        changed |= backup_shields(w, n, now) or battle_repair(w, n, now, d['can'])
    # PvP: biri ona saldırıyor ya da o bir oyuncuya / bota saldırıyor (karşılık vermeyen oyuncuya saldırırken de: önceden yalnız
    # vurulunca giriyordu, yavaşlatan roketler hiç atılmıyordu; canlı 2026-11-01)
    pvp_target = n.target is not None and ((n.target in w.npcs and w.npcs[n.target].bot is not None) or BG._player(w, n.target) is not None)
    if player_or_bot or pvp_target:
        energy_leech(w, n, now)
        if n.bot.o('aggression') > 0.5:
            x, y = n.mover.pos(now)
            r = CIT['smart_bomb']['radius']
            victims = []
            o = BG._player(w, w.hid)
            if o is not None and not o.hero_dead and BG.can_attack_player(w, n, o, now) and math.hypot(*(a - c for a, c in zip(o.hero_pos(now), (x, y)))) <= r:
                victims.append((o, None))
            for t in list(w.npcs.values()):
                if t.bot is not None and t is not n and t.bot.firma != n.bot.firma and BG.can_attack_bot(w, n, t, now) \
                        and math.hypot(*(a - c for a, c in zip(t.mover.pos(now), (x, y)))) <= r:
                    victims.append((None, t))                 # güvenli bölgedeki ve korunan botlara değil
            if len(victims) >= 1 and random.random() < 0.5:
                smart_bomb(w, n, now, victims)
        o = BG._player(w, n.target) if n.target is not None else None
        if o is not None:
            slow_down(w, n, o, ratio, now)
    return changed


def slow_down(w, n, o, ratio, now):
    """Üstüne saldırdığı oyuncuya DCR-250 (hız -%30, 5 sn) ya da canı azaldıysa R-IC3 (2 sn donma): oyuncunun roket etkisi
    (items.json 'etki', dunya.hero_effect) ve görseli aynen; bekleme süreleri roketinki."""
    from . import weapons as WP, ship as BG
    b = n.bot
    if not b.permission.get('custom_ammunition', True) or not BG.can_attack_player(w, n, o, now):
        return False
    x, y = n.mover.pos(now)
    hx, hy = o.hero_pos(now)
    if math.hypot(hx - x, hy - y) > BG.LASER_RANGE or o.hero_effects.d.keys() & {'slow', 'frozen'}:
        return False
    for loot in ((RIC,) if ratio < 0.35 else ()) + ((DCR,) if ratio < 0.6 or b.o('aggression') > 0.5 else ()):
        r = K.ITEMS['rockets'][loot]
        if WP.stock(b).get(loot, 0) > 0 and ready(n, loot, now):
            (kind, (val, sec)), = r['effect'].items()
            WP.spend(b, loot, 1)
            wait(n, loot, now, r['cooldown_sec'])
            o.hero_effect(kind, sec, val, source=loot)
            o.send([legacy('0|n|fx|start|%s|%d' % (r['fx'], o.hid))])
            o.later(sec, lambda fx=r['fx']: o.send([legacy('0|n|fx|end|%s|%d' % (fx, o.hid))]))
            b.ist('slow_down')
            return True
    return False
