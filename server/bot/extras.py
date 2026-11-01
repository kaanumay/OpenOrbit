"""Ekstralar ve CPU'lar: onarım robotları, R0K-T01, kargo CPU'su, HM-7, atlama, gizlenme, Insta-Shield, Smart Bomb, ekstra yuvası.

Takılanlar bot.k['ekip']['ekstra'] {loot: kalan hak (haklıysa) ya da 1}; yuva sayısı gemininki (items.json gemiler.extra) +
SLE CPU'larının ek_yuva'sı. Alışveriş adayları (alisveris._adaylar): her ekstranın bota faydası güç puanının bir payı olarak,
kişiliğe, seviyeye ve izinlere göre (gerçek oyuncunun öncelik sırası: önce onarım robotu, sonra işine yarayan CPU'lar).
Etkiler: govde (onarım), silah (roket beklemesi), katalog (kargo), hedefler/satis (HM-7), soyut (atlama, gizlenme, PvP).
"""
from . import catalog as K

EXTRAS = K.ITEMS['ekstralar']
REPAIR_BOTS = K.ITEMS['onarim_robotlari']
ORDER = ('equipment_extra_repbot_rep-s', 'equipment_extra_repbot_rep-1', 'equipment_extra_repbot_rep-2',
        'equipment_extra_repbot_rep-3', 'equipment_extra_repbot_rep-4')
ROKT = 'equipment_extra_cpu_rok-t01'
CARGO_CPU = 'equipment_extra_cpu_g3x-crgo-x'
HM7 = 'equipment_extra_hmd-07'
JP1, JP2 = 'equipment_extra_cpu_jp-01', 'equipment_extra_cpu_jp-02'
CLOAK = ('equipment_extra_cpu_cl04k-xs', 'equipment_extra_cpu_cl04k-m', 'equipment_extra_cpu_cl04k-xl')
ISH, SMB = 'equipment_extra_cpu_ish-01', 'equipment_extra_cpu_smb-01'
AIM1, AIM2 = 'equipment_extra_cpu_aim-01', 'equipment_extra_cpu_aim-02'
SLE = ('equipment_extra_cpu_sle-01', 'equipment_extra_cpu_sle-02', 'equipment_extra_cpu_sle-03', 'equipment_extra_cpu_sle-04')


def equipped(bot):
    return bot.k['ekip'].setdefault('ekstra', {})


def var(bot, loot):
    return equipped(bot).get(loot, 0) > 0


def slot(bot):
    g = K.ITEMS['gemiler'].get(bot.k['ekip']['gemi']) or {}
    return int(g.get('extra') or 1) + max((EXTRAS[s]['ek_yuva'] for s in SLE if var(bot, s)), default=0)


def right(loot):
    return (EXTRAS.get(loot) or {}).get('hak', 1)


def use(bot, loot):
    """Haklı ekstradan bir hak harcar -> harcandı mı (hak bitince yuvadan çıkar)."""
    t = equipped(bot)
    if t.get(loot, 0) <= 0:
        return False
    t[loot] -= 1
    if t[loot] <= 0 and 'hak' in (EXTRAS.get(loot) or {}):
        del t[loot]
        bot.loadout_changed()
    return True


def repair_level(bot):
    """Takılı en iyi onarım robotu 0 (yok) .. 5 (REP-4)."""
    return max((i + 1 for i, r in enumerate(ORDER) if var(bot, r)), default=0)


def repair_sec(bot):
    """Tam onarım süresi (sn; yoksa None)."""
    for r in reversed(ORDER):
        if var(bot, r):
            v = REPAIR_BOTS[r]
            return v.get('full_repair_sec') or (bot.value()['can'] / max(1, v.get('hp_per_minute', 1000)) * 60)
    return None


def cargo_multiplier(gear):
    return EXTRAS[CARGO_CPU]['kargo_carpan'] if (gear.get('ekstra') or {}).get(CARGO_CPU) else 1.0


# ------------------------------------------------------------------------------------------------------------ alışveriş
def utility(bot, loot):
    """Ekstranın bota faydası: güç puanının payı (0: almaz)."""
    trace, lv, o = bot.permission, bot.level, bot.o
    if loot in ORDER:
        i = ORDER.index(loot) + 1
        return max(0.0, 0.04 * i - 0.04 * repair_level(bot)) * (0.6 + 0.6 * (1 - o('risk')))
    if loot == ROKT:
        return (0.06 + 0.08 * o('saldirganlik')) if trace.get('roket', True) and lv >= 6 else 0.0
    if loot == CARGO_CPU:
        return 0.08 if trace.get('kargo', True) and lv >= 5 else 0.0
    if loot == HM7:
        return 0.1 if trace.get('kargo', True) and lv >= 8 else 0.0
    if loot in (JP1, JP2):
        return 0.05 + 0.04 * o('sabir') if lv >= 5 and not var(bot, JP1) and not var(bot, JP2) else 0.0
    if loot in CLOAK:
        return 0.05 * (1 - o('risk')) if lv >= 8 and trace.get('pvp', True) and not any(var(bot, g) for g in CLOAK) else 0.0
    if loot in (ISH, SMB):
        return 0.05 * o('saldirganlik') if lv >= 12 and trace.get('pvp', True) else 0.0
    if loot in (AIM1, AIM2):
        sky = (bot.k.get('skylab') or {}).get('mod', {}).get('XENO_MODULE', 0)
        return 0.06 * o('rekabet') if lv >= 14 and sky >= 3 and not var(bot, AIM1) and not var(bot, AIM2) else 0.0
    if loot in SLE:
        empty = slot(bot) - len(equipped(bot))
        extra = EXTRAS[loot]['ek_yuva'] - max((EXTRAS[s]['ek_yuva'] for s in SLE if var(bot, s)), default=0)
        return 0.02 * extra if empty <= 0 and extra > 0 else 0.0
    return 0.0


def candidates(bot):
    """Alışveriş adayları [(güç artışı, para, fiyat, loot)]: boş yuva varsa (ya da yuva CPU'su) faydalı ve sahip olunmayan ekstralar."""
    if not bot.permission.get('ekstra', True):
        return []
    power = bot.value()['power']
    empty = slot(bot) - len(equipped(bot))
    out = []
    for loot in list(ORDER) + [ROKT, CARGO_CPU, HM7, JP1, JP2, CLOAK[1], ISH, SMB, AIM2, AIM1] + list(SLE):
        if var(bot, loot) or (empty <= 0 and loot not in SLE and loot not in ORDER):
            continue
        f = K.price(loot)
        p = utility(bot, loot)
        if f and f[1] > 0 and p > 0:
            out.append((power * p, f[0], f[1], loot))
    return out


def equip(bot, loot):
    """Satın alınan ekstra takılır; onarım robotu eskisinin yerine (tek yuva); yuva doluysa en az faydalısı çıkar."""
    t = equipped(bot)
    if loot in ORDER:
        for r in ORDER:
            t.pop(r, None)
    elif loot in SLE:
        for s in SLE:
            t.pop(s, None)
    if len(t) >= slot(bot) and loot not in SLE:
        dropped = min(t, key=lambda x: utility(bot, x) if x not in ORDER else 1.0)
        del t[dropped]
    t[loot] = right(loot)
    bot.loadout_changed()


# ------------------------------------------------------------------------------------------------------------ kullanım
def jump(bot, target):
    """Atlama CPU'su bu yolculuğu kısaltır mı: hedef üs (X-1), CPU'nun izin verdiği haritadan, hakkı var -> kullanılan CPU ya da None."""
    if target != K.ev(bot.firma) or not bot.permission.get('ekstra', True):
        return None
    import map_links as H
    name = H.name(bot.game_map)
    map_class = H.map_class(bot.game_map)
    for cpu in (JP2, JP1):
        if not var(bot, cpu):
            continue
        a = EXTRAS[cpu]['atlama']
        if 'haritalar' in a and map_class not in a['haritalar']:
            continue
        if any(name.startswith(p) for p in a.get('yasak', ())):
            continue
        return cpu
    return None


def cloak(bot):
    """Güçlü düşmandan gizlenme CPU'suyla kaçar -> kullanıldı mı."""
    if not bot.permission.get('ekstra', True):
        return False
    return any(use(bot, g) for g in CLOAK if var(bot, g))


def pvp_factor(bot):
    """Insta-Shield ve Smart Bomb PvP'de güce katkı."""
    return 1.0 + 0.12 * var(bot, ISH) + 0.1 * var(bot, SMB)
