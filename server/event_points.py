"""Etkinlik puanı, ilerleme eşikleri ve etkinlik sonu ödülleri (resmî Türk forumu: Toplama Zamanı / Hatching Out 129632, Karaşimşek
Dalgası / Blacklight Surge 145819, Korsan Baskını 133215, Evrensel 4 - Europa 177655; veri data/events.json 'puanlama').

'puanlama' alanları (hepsi isteğe bağlı):
  npc        {npc_kimlik: puan ya da [kendi firma haritasında, düşman haritasında]}: sıralama puanı; yalnız öldüren alır
  ilerleme   {npc_kimlik: puan}: ilerleme puanı (Blacklight Surge'ün İlerleme Puanı); kutulardan da gelir: içerik satırı
             'olay_puani:<etkinlik>' (Hatching Out'un Viral Kutuları: VPP; dunya.grant_loot)
  kapi       {kapı: ilerleme puanı}: kapı tamamlanınca (Hatching Out: Alpha/Beta/Gamma 160 VPP; Dispatch'te yok, çifte ödül günü
             etkilemez)
  esikler    [[ilerleme, [[lootId, adet], …]], …]: eşiğe varınca ödülü (istemcinin EventProgress penceresi 1.1.115'te ölü: ödül
             doğrudan, ekranda ileti)
  sifirla    true: son eşikten sonra ilerleme baştan (Hatching Out: "çubuk sıfırlanabilir"); yoksa bir kez (Blacklight Surge)
  siralama   [{den, e, esyalar, unvan}]: etkinlik bitince sıraya göre ödül (EventRewardConfirmationCommand); tek oyunculuda puanı olan
             pilot 1. (Mimesis Mutiny gibi); sira_olcut 'katilim': puan yerine etkinlik sırasında girmiş olmak (Europa: seviye ve EP
             sırası, tek oyuncu 1.)
  katilim    {esyalar, unvan}: etkinlik sürerken giriş yapan herkese, etkinlik bitince (Europa: talep penceresinden)
İstemcinin ilerleme satırı '0|LM|ST|EPP|n' ("You received n Progress Points."); sıralama puanının istemcide göstergesi yok.
Profilde: olay_puan {etkinlik: {donem, puan, ilerleme, esik, katildi}} (etkinlik bitip ödülü verilince silinir).
"""
import map_links as H
import event_calendar as CAL
import rankings as RK
from legacy_protocol import legacy
from galaxy_gates import screen

LOOT = 'olay_puani:'


def cfg(ev):
    return CAL.EVENTS.get(ev, {}).get('scoring')


def events():
    return [k for k in sorted(CAL.EVENTS) if cfg(k)]


def state(p, ev, now=None):
    """Dönemin durumu: yeni dönem başlayınca sıfırdan (bitmiş etkinliğinki ödül verilene dek kalır)."""
    per = CAL.period(ev, now) if CAL.is_active(ev, now) else None
    root = p.d.setdefault('event_points', {})
    st = root.get(ev)
    if st is None or (per and st.get('donem') != per[0]):
        with p.lock:
            st = root[ev] = dict(donem=per[0] if per else None, puan=0, progress=0, threshold=0, joined=False)
            p.dirty = True
    return st


def add(p, ev, n, give, now=None):
    """İlerleme puanı: eşiklerin ödülleri (give(lootId, adet) -> mesajlar) ve EPP satırı."""
    c = cfg(ev)
    if not c or n <= 0 or not CAL.is_active(ev, now):
        return []
    st = state(p, ev, now)
    with p.lock:
        st['progress'] += n
        p.dirty = True
    msgs = [legacy('0|LM|ST|EPP|%d' % n)]
    steps = c.get('thresholds', [])
    while st['threshold'] < len(steps) and st['progress'] >= steps[st['threshold']][0]:
        lim, items = steps[st['threshold']]
        with p.lock:
            st['threshold'] += 1
            p.dirty = True
        for loot, k in items:
            msgs += give(loot, k) if give else []
        msgs.append(screen('%s - %s points reached!' % (CAL.EVENTS[ev]['ad'], format(lim, ',')), big=True))
        if st['threshold'] == len(steps) and c.get('reset'):             # Hatching Out: çubuk dolunca baştan
            with p.lock:
                st['progress'] -= steps[-1][0]
                st['threshold'] = 0
    return msgs


def score(p, ev, n, now=None):
    if n > 0 and cfg(ev) and CAL.is_active(ev, now):
        st = state(p, ev, now)
        with p.lock:
            st['puan'] += n
            p.dirty = True


def on_kill(p, map_id, npc_id, give, now=None):
    """Öldürülen uzaylının puanları (etkin bütün puanlamalı etkinlikler)."""
    msgs, key = [], str(npc_id)
    for ev in events():
        c = cfg(ev)
        if not CAL.is_active(ev, now):
            continue
        pts = c.get('npc', {}).get(key)
        if isinstance(pts, list):                       # Blacklight Surge: kendi firma haritasında çift (1-BL ve 1-8 MMO'nun …)
            pts = pts[0] if H.company(map_id) == p.d.get('pilot', {}).get('factionId') else pts[1]
        if pts:
            score(p, ev, pts, now)
        msgs += add(p, ev, c.get('progress', {}).get(key, 0), give, now)
    return msgs


def gate(p, key, give, now=None):
    """Kapı tamamlandı (Dispatch hariç): etkinliğin kapı puanı."""
    return [m for ev in events() for m in add(p, ev, cfg(ev).get('kapi', {}).get(key, 0), give, now)]


class EventPoints:
    """Oturum sistemi (ek_etkinlikler): öldürme puanı, katılım ve etkinlik bitince ödüller."""

    def __init__(self, profile, shop, log=print):
        self.p, self.m, self.log = profile, shop, log
        self.titles = None                           # ek_etkinlikler bağlar (unvan_avi.grant_title)
        self.next = 0.0

    def give(self, loot, n):
        return self.m.prize(loot, n) if self.m else []

    def on_kill(self, w, n, x, y):
        return on_kill(self.p, w.map_id, n.d.get('npc_kimlik'), self.give)

    def tick(self, now):
        if now < self.next:
            return []
        self.next = now + 5.0
        msgs = []
        for ev in events():
            if CAL.is_active(ev, now):
                st = state(self.p, ev, now)
                if not st['joined']:
                    with self.p.lock:
                        st['joined'] = True
                        self.p.dirty = True
            elif ev in self.p.d.get('event_points', {}):
                msgs += self.finish(ev)
        return msgs

    def finish(self, ev):
        """Etkinlik bitti: katılım ve sıralama ödülü bir kez (tek oyunculu sıra: 1.)."""
        c, st = cfg(ev), self.p.d['event_points'][ev]
        msgs = []
        k = c.get('participation') if st.get('joined') else None
        if k:
            for loot, n in k.get('esyalar', []):
                msgs += self.give(loot, n)
            if k.get('title') and self.titles:
                msgs += self.titles(k['title'])
        ok = st.get('puan', 0) > 0 or (c.get('rank_metric') == 'participation' and st.get('joined'))
        r = next((r for r in c.get('ranking', []) if r['den'] <= 1 <= r['e']), None) if ok else None
        if r:
            for loot, n in r['esyalar']:
                msgs += self.give(loot, n)
            if r.get('title') and self.titles:
                msgs += self.titles(r['title'])
            msgs.append(RK.confirmation(1, RK.DEFAULT_REWARD, r))
        self.log('   %s bitti: puan %d, ilerleme %d%s' % (CAL.EVENTS[ev]['ad'], st.get('puan', 0), st.get('progress', 0),
                                                       ', 1. sıra ödülü' if r else ''))
        with self.p.lock:
            del self.p.d['event_points'][ev]
            self.p.dirty = True
        return msgs + (self.m.money_msgs() if msgs and self.m else [])
