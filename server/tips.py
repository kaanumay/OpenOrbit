"""Yeni başlayan ipuçları ve tek seferlik bildirimler (yol haritası Ö2).

İstemci (HintSystemContentProvider): HintWindowAddComand {window {content: HintType}, visibility 0, soundModule, addToList,
openedFromArchive} ipucu penceresini açar; addToList ile ipucu arşivine de girer (HintWindowListInitCommand girişte arşivi kurar).
İstemcinin sözlüğünde 39 tür var, CONFIG_SWITCH (15) yok: o gönderilmez. Metinler iki türlü: "gameentry_hintwindow_message_*"
(bir şey olunca: kargo doldu, cephane bitti, onarım) ve "targeted_hintwindow_message_*" (bir özelliğe davet: Galaksi Kapıları,
yetenek ağacı, Tech Factory). Kayıtta girişte WELCOME (12), arşivde HOW_TO_FLY ve REQUEST_MISSION (13, 14) vardı.

Tek oyunculu uyarlama: her ipucu bir kez (profilde ipuclari_gosterilen); oyuncunun kapattıkları (ipuclari_kapali, game.py) yeniden
açılmaz; panelin "ipuclari" ayarı kapalıysa hiç gönderilmez.
- Olay ipuçları (metnine göre): savaştan hasarlı çıkınca onarım (3 tuşu), ilk cevher (rafineride sat), kargo doldu, cephane
  bitti (hızlı satın alma), ilk öldürme (XP/onur/kredi kazan), ilk hedef seçme (saldırı tuşları), ilk portala yaklaşma (J), başka
  firmanın haritası ya da 4-X (PvP uyarısı), PLT-2021 elde varken başka roket atma, mağazadan ilk ekipman (hangarda tak), ikinci gemi
  (gemi ışınlama).
- Davet ipuçları seviye atlayınca (LEVELS); özellik zaten kullanılmışsa (used) gösterilmez: Mesela roket fırlatıcısı olan oyuncuya
  roket fırlatıcı ipucu açılmaz.

Etkinlik bildirimi: süren harita etkinliğinin açıklaması (istemcinin <metin>_event_description'ı, ör. curcubitor) etkinlik dönemi
başına bir kez NormalTipsCommand {messageKey} ile mesaj kutusunda (profilde etkinlik_bildirimi).
"""
import settings as SET

SHIP_REPAIR, SKYLAB, PVP_WARNING, THE_SHOP, CHANGING_SHIPS, INSTALLING_NEW_EQUIPMENT, JUMP_GATES, PREPARE_BATTLE = 0, 1, 2, 3, 4, 5, 6, 7
GET_MORE_AMMO, BOOST_YOUR_EQUIP, SELL_RESOURCE, WEALTHY_FAMOUS = 8, 9, 10, 11
EQUIP_YOUR_ROCKETS, ATTACK, FULL_CARGO, SECOND_CONFIGURATION, ITEM_UPGRADE = 17, 19, 21, 22, 23
GALAXY_GATE, SKILL_TREE, TECH_FACTORY, PALLADIUM, AUCTION_HOUSE, ROCKET_LAUNCHER, EXTRA_CPU, SHIP_DESIGN = 24, 25, 26, 28, 29, 30, 31, 32
ORE_TRANSFER, PRO_ACTION_BAR_INFO, ASSEMBLY = 35, 37, 39
PLT_2021 = 'ammunition_rocket_plt-2021'
CLIENT_TYPES = set(range(40)) - {15}  # istemcinin bildiği türler (HintSystemContentProvider)
SOUND = 132                           # kayıttaki ipucunun sesi

# davet ipuçlarının seviyeleri (uyarlama: özellik o seviyede işe yarar hâle gelir; 5-2'nin tüccarı ~10-12, Tech Factory/Assembly
# orta seviyeler)
LEVELS = {2: (THE_SHOP, PREPARE_BATTLE), 3: (BOOST_YOUR_EQUIP,), 4: (GALAXY_GATE, PRO_ACTION_BAR_INFO),
          5: (SECOND_CONFIGURATION, EXTRA_CPU, AUCTION_HOUSE), 6: (SKILL_TREE, SKYLAB), 7: (ROCKET_LAUNCHER, ITEM_UPGRADE),
          8: (TECH_FACTORY, ASSEMBLY, ORE_TRANSFER), 10: (SHIP_DESIGN,), 12: (PALLADIUM,)}


def owned_items(p):
    return set(p.d.get('esyalar', {}).values())


def used(p, kind):
    """Özellik zaten kullanılıyor mu (davet ipucu gereksiz)."""
    items = owned_items(p)
    if kind == EXTRA_CPU:
        return any(i.startswith('equipment_extra_cpu_') for i in items)
    if kind == ROCKET_LAUNCHER:
        return any(i.startswith('equipment_weapon_rocketlauncher_') for i in items)
    if kind == SHIP_DESIGN:
        return any(s.get('designs') for s in p.d.get('gemiler', {}).values())
    if kind == GALAXY_GATE:
        return any(g.get('parcalar') or g.get('tamam') for g in ((p.d.get('kapilar') or {}).get('kapilar') or {}).values() if g)
    return False


def for_purchase(p, loot, first_equipment):
    """Mağazadan alınan eşya -> ipucu türü ya da None."""
    if loot.startswith('ship_') and '_design_' not in loot and len(p.d.get('gemiler', {})) >= 2:
        return CHANGING_SHIPS
    if first_equipment:
        return INSTALLING_NEW_EQUIPMENT
    return None


class Hints:
    def __init__(self, profile, log=print):
        self.p, self.log = profile, log

    def shown(self):
        return self.p.d.setdefault('ipuclari_gosterilen', [])

    def show(self, kind):
        """İpucu bir kez -> [HintWindowAddComand] ya da boş (gösterilmiş, kapatılmış, istemcide yok ya da panelde kapalı)."""
        if kind not in CLIENT_TYPES or not SET.get('ipuclari'):
            return []
        if kind in self.shown() or kind in self.p.d.get('ipuclari_kapali', []):
            return []
        with self.p.lock:
            self.shown().append(kind)
            self.p.dirty = True
        self.log('   ipucu: %d' % kind)
        return [('HintWindowAddComand', dict(paymentLink='', visibility=0, addToList=True, openedFromArchive=False,
                                             soundModule={'_': 'SoundTriggerModule', 'playSound': True, 'soundId': SOUND},
                                             window={'_': 'HintWindowModule', 'content': kind}))]

    def level(self, lv):
        """Seviye atlandı: o seviyeye (ve atlanan alt seviyelere) kadarki davet ipuçlarından gösterilmemiş ilki. Bir seferde bir
        pencere (üst üste açılmasın); kalanlar sonraki seviyelerde gelir."""
        for at in sorted(LEVELS):
            if at > lv:
                break
            for kind in LEVELS[at]:
                if kind in self.shown() or used(self.p, kind):
                    continue
                msgs = self.show(kind)
                if msgs:
                    return msgs
        return []

    def event_tips(self, specs, period):
        """Süren harita etkinliklerinin açıklaması dönem başına bir kez (NormalTipsCommand). specs: [(etkinlik, bölüm)]; period:
        etkinlik -> dönemin başlangıcı (yoksa 0)."""
        if not SET.get('ipuclari'):
            return []
        st = self.p.d.setdefault('etkinlik_bildirimi', {})
        out = []
        for k, s in specs:
            text = (s.get('bilgi') or {}).get('metin')
            if not text or st.get(k) == period(k):
                continue
            with self.p.lock:
                st[k] = period(k)
                self.p.dirty = True
            out.append(('NormalTipsCommand', {'messageKey': '%s_event_description' % text}))
            self.log('   etkinlik bildirimi: %s' % k)
        return out
