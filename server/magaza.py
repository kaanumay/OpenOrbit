"""Mağaza ve hangar: cephane/ekipman satın alma ve hangarda ekipman takıp çıkarma (kayıttaki ve istemcideki akışlar).

Satın alma (kayıt: LCB-10 ve MCB-25 alımları, belgeler/istemci/kayit_analizi.md):
  ShopItemBuyRequest {lootId, category, amount, …} ->
    [hızlı alım öğelerinin durumu] + 0|A|C|kredi|uridyum + para birimi envanteri + cephane sayacı (MenuItemStatusCommand)
    + InventoryItemUpdatedCommand + InventoryItemPack + 0|LM|ST|BAT|lootId|adet + ShopItemBuyCommand(resultId 1)
    + kategorinin güncel ShopItemListCommand'i (maxAmount = paranın yettiği adet, yetmiyorsa -1)
  Fiyat: price × adet, yukarı yuvarlanır (kayıt: 0,5 U'luk MCB-25'ten 1 adet -> 1 U).
  Ekipman alımında eşya envantere girer (hangarId 0). Gemide boş yuva varsa ShopItemBuyCommand allowAutoEquip=1 ve
  hintEquipTo="hint_equip_to_ship" taşır; istemci "Envantere / Otomatik donat" sorar ve onayda aşağıdaki takma isteğini
  gönderir (istemci kodu: UIShopSystem.SendHangarShipMoveItemsRequest).
Tek oyunculu: gerçek parayla satılan ("Payment") eşyalar uridyumla satılır (fiyatlar esyalar.json odeme_fiyatlari).
  Paketlerin içeriği odeme_paketleri tablosundan verilir (gemi paketleri dahil); içeriği sunucuda olmayan eşya listede gösterilmez.
  Paketin verilemeyen parçaları (sahip olunan gemi, P.E.T., formasyon; dronlar boş yer kadar) atlanır, gerisi verilir, ekranda
  "Already owned, not given: …" (package_fit); hepsi zaten varsa alım olmaz. Fiyat değişmez.
Hızlı alım: buy_<lootId> (kayıttaki SELECTION öğesi; MenuActionRequest actionType 1: kısayol çubuğunda tek tık, öğe çubuğunda çift tık;
  öğe çubuğundaki tek tık actionType 0, gerçek sunucu yanıtlamıyor); adet öğenin sayacı (lazer 1000, roket 100).
Hangar:
  HangarShipEquipmentRequest -> HangarShipEquipmentCommand (iki config'in eşya kimlikleri profilden)
  HangarListRequest          -> HangarShipsCommand (envanter: ekipman örnekleri, cephane, cevher)
  HangarShipDetailRequest    -> HangarShipDetailCommand (lazer sayısı, cephane, jeneratörler, hız)
  HangarShipMoveItemsRequest {items, source, destination, configId} (istemci: UINewHangarSystem.SendMoveItemRequest;
    hedef/kaynak "ship" | "inventory", yuvayı eşyanın türü belirler) -> HangarShipMoveItemsCommand(result 1)
    + eşyaların hangarId güncellemesi + HangarShipEquipmentCommand; etkin config değiştiyse hız/kalkan/görünüm.
Dronlar (kayıttaki hesapta dron yoktu; biçimler istemcinin kodundan):
  Mağaza "drone" kategorisi: Flax (kredi), Iris (uridyum); fiyat her dronla artar (esyalar.json dronlar), en çok 8.
  Formasyonlar mağazadan alınır; kısayol çubuğunun drone_formations kategorisinde görünür olur. Çubuktan seçilince
  (MenuActionRequest drone_formation_*) DroneFormationChangeCommand + uzaydaki dron dizilimi + bonuslar (hız, kalkan, can).
  Uzayda: "0|n|d|<kullanıcı>|<formasyon>|" + dron başına "tür|seviye|tasarım|görünüm" (istemci: MapEventsAssemblyHelper.
    AssembleSetDrones; tür 1 Flax, 2 Iris, 3 Apis, 4 Zeus; seviye 1-6).
  Hangar: HangarShipsCommand.drones (HangarShipDroneView) ve HangarShipEquipmentCommand.droneConfigs (config başına dron listesi,
    takılı eşyalar SingleDroneEquipmentMsg.defaults). Dronlara yalnız lazer ve kalkan jeneratörü takılır (Flax 1, Iris 2 yuva);
    istemci hedef/kaynak "drone" + droneId gönderir (yuva kümesi "default"; istemci: UINewHangarSystem.ReturnDroneId).
Dron tasarımları (mağaza "customization"; Havoc ve Hercules esyalar.json ek_magaza): dron başına bir "design" (bonuslu,
  istemcide DroneDesignType) ve bir "visual" (görünüm, DroneCustomizationType) yuvası; config başına (P.E.T. gibi config
  numarasına bağlı, gemiye değil; dron kaydında tasarim/gorunum {config: eşya kimliği}). Uzayda dron
  dizgisinin tasarım/görünüm alanları istemcinin game.xml tasarım kimlikleri (esyalar.json dron_tasarimlari).
P.E.T. (pet.py): mağazada pet_pet10 (bir tane), dişliler (petgear) ve protokoller (protocol) envantere girer; hangarda
  P.E.T. yuvaları (lasers, generators, gears, protocols) config başına; yuva açma ve ad değiştirme pet.py'de.
Katalog ve fiyatlar kayıttaki ShopItemListCommand'lerden (data/yanitlar.json); ekipman değerleri data/esyalar.json.
"""
import json, math, os, time
import veri as VERI
import booster as BOOSTER   # noqa: E402
import pet as PETM
import ekstra as EK
import rutbe as RT
import teknoloji as TK
import yukseltme as YK
import gemi_modul as GM
import ganimet as GN
import qfc as QF
import parcacik as PC
import rezonator as RZ
import ayar as AY
import harita as H
import etkinlik_gorunumleri as EG
import ipucu as IP
import sezon as SZ
import yetenek as YT

HERE = os.path.dirname(os.path.abspath(__file__))
ESYA = json.load(open(os.path.join(HERE, 'data', 'esyalar.json'), encoding='utf8'))
_F = json.load(open(os.path.join(HERE, 'data', 'fiyatlar.json'), encoding='utf8'))
FIYAT, KUR = _F['fiyatlar'], _F['kur']        # market dengesi (tools/market_dengesi.py); KUR: 1 U kaç kredi
DUNYA_MAGAZA = VERI.yukle('magaza')['urunler']    # Dünya Editörü: lootId -> {fiyat, para ('C' | 'U'), satista}; oyun açıkken yenile()


def yenile():
    """Dünyanın mağazası değişti (game.dunya_izle): sözlük yerinde güncellenir, sonraki liste ve alım yeni fiyatla."""
    DUNYA_MAGAZA.clear()
    DUNYA_MAGAZA.update(VERI.yukle('magaza')['urunler'])
CONFIG_COOLDOWN_SN = 5          # config geçişleri arası (kayıtta 2,4 sn sonraki reddedildi; süre uyarlama)
PREMIUM_KARGO = 500             # Premium: "500 extra units of cargo space" (istemci breakingNewsContent_permPremiumAdvantages)

CURRENCY = {'virtual': 'credits', 'real': 'uridium'}
SLOTS = (('equipment_weapon_laser_', 'laser'), ('equipment_weapon_rocketlauncher_', 'rocket'),
         ('equipment_generator_', 'generators'), ('equipment_extra_', 'extra'), ('equipment_shipupgrade_', 'upgrades'),
         ('equipment_core_', 'QuantumFluidCore'),       # Quantum Fluid Core: geminin özel yuvaları (qfc.py)
         ('equipment_weapon_cannon_', 'cannon'), ('equipment_cannon_shield_', 'cannonShield'),      # parçacık topu, kırıcı
         ('equipment_weapon_drive_', 'drive'), ('equipment_lens_', 'lens'))                        # Singularity Drive, mercek
# hangar panelleri: istemci gemi için "ship" gönderir; yuva adları da kabul edilir
PANELS = {'ship': None, 'laser': 'laser', 'lasers': 'laser', 'generator': 'generators', 'generators': 'generators',
          'extra': 'extra', 'extras': 'extra', 'rocket': 'rocket', 'rockets': 'rocket', 'rocketlauncher': 'rocket',
          'upgrades': 'upgrades', 'upgrade': 'upgrades', 'ship_upgrades': 'upgrades', 'shipupgrade': 'upgrades'}
INVENTORY = ('inventory', '')
DEFAULT_SLOTS = {'laser': 15, 'generators': 15, 'extra': 3, 'rocket': 1, 'upgrades': 3, 'QuantumFluidCore': 2, 'cannon': 3,
                 'cannonShield': 6, 'drive': 0, 'lens': 0}
EQUIP_SLOTS = ('laser', 'generators', 'extra', 'rocket', 'upgrades', 'QuantumFluidCore', 'cannon', 'cannonShield', 'drive', 'lens')
CLIENT_SLOTS = {'laser': 'lasers', 'generators': 'generators'}       # CLIENT_SHIP_SLOTS'taki adları (capacity)
MODULE_TYPE_IDS = {'DAMAGE': 1, 'HP': 2, 'SHIELD': 3, 'SPECIAL': 4}       # ShipUpgradeModuleUpdateCommand.moduleTypeIds (uyarlama)
ORES = {int(t): loot for t, loot in ESYA['cevherler']['turler'].items()}     # OreType -> eşya (hangar envanteri)
DRONES = ESYA['dronlar']
FORMS = ESYA['formasyonlar']
FORM_RULES = ESYA['formasyon_kurallari']     # formasyon başına asgari dron sayısı ve satış takvimi
LEVELS = ESYA['dron_seviyeleri']
DRONE_ITEMS = ('equipment_weapon_laser_', 'equipment_generator_shield_')     # dronlara lazer ve kalkan jeneratörü (+ ekstralar: drone_ok)
REPBOT = 'equipment_extra_repbot_'                                           # onarım robotları: config başına bir tane
LAB = ESYA['laboratuvar']
DESIGNS = ESYA['dron_tasarimlari']
DESIGN_SLOTS = {'tasarim': 'design', 'gorunum': 'visual'}     # drone record key -> design slot (drone item's "yuva")
DESIGN_TYPES = {'design': 'net.bigpoint.darkorbit.asset.drone.design.DroneDesignType',
                'visual': 'net.bigpoint.darkorbit.asset.drone.design.DroneCustomizationType'}
PET_LOOT = ESYA['pet']['loot']
PET_FUEL = 'resource_pet-fuel'
PACK_MAX = 255             # bayt sayaçlı liste (InventoryItemPack.items): en çok bu kadar eşya
NEW_RESOURCES = ('resource_collectable_evocation-chip', 'resource_collectable_calling-chip',          # N.O.V.A. (nova.py)
                 'resource_collectable_luminaflux-alloy', 'resource_collectable_armory-token',       # Hyperforge (qfc.py), Armory
                 'resource_collectable_armory-token-mega', 'resource_collectable_optigrad-chip',       # Restabilize (parcacik.py)
                 'resource_collectable_horizon-shard', 'resource_collectable_containment-node',       # sürücü alt nitelikleri
                 'resource_collectable_pulse-core', 'resource_ignishard-l01', 'resource_beacon-crystal')
PASS_ITEMS = ('resource_season-pass-point', 'resource_gold-pass', 'resource_ext-gold-pass', 'resource_battle-pass',
              'resource_monthly-deluxe')
# istemcinin tanımında özelliği (Traits) olmayan eşyalar (data/istemci_esyalari.json'da yalnız tür ve sınıf): kimlikli envanter
# eşyası olunca Assembly açıkken AssemblyInventoryIndex.UpdateItem NullReferenceException veriyor, eşya listesinin kalanı (girişte
# UserInventoryModule'ün indirimi dahil) işlenmiyordu (Gold/Extra Gold Pass, Trinity VIP Badge; canlı tur 2). Bu kaynaklar gönderilmez
NO_TRAITS = {l for l, v in YK.ITEMS.items() if set(v) <= {'tur', 'sinif'}}
EVENT_ITEMS = ('resource_collectable_voyagers-oath-token', 'resource_voyagers-vip-badge',      # Voyagers (pve_modlari.py)
               'resource_ftl-key', 'resource_collectable_galaxy-coupon', 'resource_lottery-capsule')   # Ö3 etkinlik paraları (market dengesi)


def mod(name, **f):
    f['_'] = name
    return f


from eski_protokol import legacy, loot_kind  # noqa: E402,F401  (eski metin protokolü: eski_protokol.py)


def keyed(key, **wild):
    """İstemcinin yerelleştirme anahtarıyla hata metni (MessageKeyListWildcardCommand)."""
    reps = [mod('MessageWildcardReplacementModule', wildcard='%' + k + '%', replacement=v,
                replacementType=mod('ReplacementTypeModule', typeValue=5 if v.startswith('ttip_') else 0)) for k, v in wild.items()]
    return mod('MessageKeyListWildcardCommand', commandList=[
        mod('MessageKeyListWildcardModule', wildCardReplacements=reps, baseKey=key,
            baseKeyType=mod('ReplacementTypeModule', typeValue=5), textStyle=0)])


BASEKEY = json.load(open(os.path.join(HERE, 'data', 'mesaj_anahtarlari.json'), encoding='utf8'))['anahtarlar']


# metindeki yer tutucular (istemcinin ArgKey enum'u): ad "_X_" ise metinde %X%, değilse adın kendisi (XXX, YYY, DATETIME)
ARG_KEYS = {'_COOLDOWN_': 0, '_BOOSTERNAME_': 1, '_module_': 2, '_level_': 3, '_date_': 4, '_userlevel_': 5, '_maxMessages_': 6,
            '_notesLimit_': 7, '_MINIMUM_BID_': 8, '_NAME_': 9, '_AMOUNT_': 10, '_CURRENCY_': 11, 'XXX': 12, 'YYY': 13,
            'DATETIME': 14, '_MAX_BID_': 15}


def res(key):
    """Yer tutucu değerinin istemcide yerelleştirilmesi (ShowCallBackText.ReturnTipByType: ':' ile bölünür, ikinci parça 'res' ise
    son parça GetTextById ile çevrilir). "res:<anahtar>" çalışmıyordu (canlı test H36: yer tutucu ham kalıyordu)."""
    return ':res:' + key


def stack_ek(key, ek):
    """İstemcinin yerelleştirdiği metin (key) ve ardına dilden bağımsız bir ek (sayılar): ham metin "XXX<ek>", XXX istemcide çevrilir
    (RES_YERINE'deki gibi type 1). Ekteki yer tutucu (_AMOUNT_) bu yolda doldurulmuyor (canlı test 2026-10-30): değerler ekin içinde."""
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX' + ek,
               argsList=[mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=res(key))])


def stack_msg(key, **args):
    """Yanıt komutlarındaki hata/başarı metni (ShopItemBuyCommand, HangarShipMoveItemsCommand, HangarShipActivateShipCommand).
    İstemci BaseStackCommand bekler; başka sınıf InvalidCastException verip bağlantıyı koparır (canlı test).
    type 0 + enumBaseKey: istemci BaseKey enum adını yerelleştirme anahtarı olarak kullanır (stringBasekey ise ham metin olur).
    args: yer tutucuların değerleri (ArgStackCommand; istemci ShowCallBackText.ReturnTipString): ör. XXX='Komutan',
    _MINIMUM_BID_='10,000'. res(<anahtar>) değeri istemcide çevrilir. Verilmezse metinde "XXX" gibi ham yer tutucu kalıyordu
    (canlı deneme 2026-10-17: "A new rank was created: XXX.")."""
    lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in args.items()]
    if key in RES_YERINE:
        # istemcinin yüklemediği kaynaktaki anahtar: ham metin "XXX" + XXX'in yerelleştirilmiş değeri (type 1; ReturnTipString
        # yer tutucuları sondan başa çevirir: önce XXX, sonra metnin kendi yer tutucuları)
        alias, extra = RES_YERINE[key]
        lst = [mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS[k], value=str(v)) for k, v in extra.items()] + lst
        lst.append(mod('ArgStackCommand', type=0, value2=None, key=ARG_KEYS['XXX'], value=res(alias)))
        return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey='XXX', argsList=lst)
    return mod('BaseStackCommand', type=0, enumBaseKey=BASEKEY[key], stringBasekey='', argsList=lst)


def raw_msg(text):
    """Ham metin (type 1: stringBasekey olduğu gibi gösterilir; RES_YERINE gibi)."""
    return mod('BaseStackCommand', type=1, enumBaseKey=0, stringBasekey=text, argsList=[])


# istemcinin metinlerinde karşılığı olmayan ret nedenleri (BaseKey'lerde ve 40 metin dosyasında yok; istemci yalnız genel metni
# gösteriyordu: N4, HAT-7/20) -> (İngilizce, Türkçe); istemcinin dilinde ham metin (Magaza.neden)
NEDENLER = {
    'ad_bekleme': ('You can only rename your Pilot once every 48 hours. (Your last name change: %DATETIME%)',     # change_pilotname_error_time
                   'Pilotunun adını en fazla 48 saatte bir değiştirebilirsin. (Son ad değişikliğin: %DATETIME%)'),
    'ad_yasak': ('This Pilot name is not permitted.', 'Bu Pilot adına izin verilmiyor.'),                       # change_pilotname_error_blacklist
    'abone_oldu': ('You have subscribed to this booster. It will be bought again automatically.',            # istemci booster_bought_subscription
                   'Bu güçlendiriciye abone oldun; süresi bitmeden kendiliğinden yeniden alınacak.'),
    'abone_bitti': ('Your booster subscription has been cancelled.', 'Güçlendirici aboneliğin sona erdi.'),
    'pet_zaten': ('This item is already equipped on your P.E.T.', "Bu eşya P.E.T.'inde zaten takılı."),
    'pet_dolu': ('Your P.E.T. has no free slot for this item.', "P.E.T.'inde bu eşya için boş yuva yok."),
    'baska_gemi': ('This item is equipped on another ship. Unequip it there first.', 'Bu eşya başka bir gemide takılı; önce oradan çıkar.'),
    'ayni_top': ('Your ship already has a cannon of this type.', 'Gemide bu türden bir top zaten takılı.'),
    'qfc_gemi': ('This Quantum Fluid Core is bound to another ship.', 'Bu Quantum Fluid Core başka bir gemiye bağlı.'),
    'ayni_qfc': ('Your ship already has a Quantum Fluid Core of this type.', 'Gemide bu türden bir Quantum Fluid Core zaten takılı.'),
    'tek_yuva_cpu': ('Only one Slot CPU is allowed per configuration.', "Bir config'e yalnız bir Slot CPU takılabilir."),
    'takili_satis': ('Equipped items cannot be sold. Unequip it first (check both configurations).',
                     "Takılı eşya satılamaz; önce çıkar (iki config'e de bak)."),
    'eksik_yukleme': ('Some equipment were not available to be loaded into the saved configuration.',
                      "Kayıtlı config'teki bazı eşyalar yüklenemedi (satılmış ya da başka gemide)."),
    'aktarim_envanter': ('Some equipment cannot be equipped on the new ship and was moved to your inventory.',
                         'Bazı eşyalar yeni gemiye takılamadığı için envantere kaldırıldı.'),
    'yakit_dolu': ("Your P.E.T.'s fuel tank is full.", "P.E.T.'inin yakıt deposu dolu."),
    'arastirma_puani': ('Not enough Research Points available.', 'Yeterli araştırma puanı yok.'),
    'on_kosul': ('The prerequisites for the next level of this skill are not met.', 'Bu yeteneğin sonraki seviyesinin ön koşulları karşılanmıyor.'),
    'ayni_modul': ('Only one module of each type (Damage, HP, Shield, Special) can be equipped on a ship.',
                   'Bir gemiye her türden (hasar, can, kalkan, özel) yalnız bir modül takılabilir.'),
    'qfc_satis': ('Quantum Fluid Cores cannot be sold. You can recycle them in the Hyperforge (Assembly).',
                  "Quantum Fluid Core satılamaz; Hyperforge'da (Assembly) geri dönüştürebilirsin."),
    'rh_bag_suresi': ('Returnees must bond with an active player within 24 hours of logging in.',
                      'Dönen oyuncular girişten sonraki 24 saat içinde aktif bir oyuncuya bağlanmalı.'),
}


# BaseKey adı istemcide metin bulamayanlar -> yüklenen kaynaktaki eşdeğeri (ve yer tutucuları). İstemci "resource_items_old"
# kaynağını yüklüyor ama paketteki dosya "resource_item_old" (LocalizationManager): o dosyadaki anahtarlar (drone_have_max)
# hiç bulunmuyor, hata penceresi boş açılıyordu (canlı test 2026-10-18). clan_errmsg_desc_to_long hiçbir kaynakta yok.
RES_YERINE = {'drone_have_max': ('items_drone_have_max', {}),
              'drone_slotCPUinUse': ('drone_slotCPUinUse', {}),        # resource_system_inc'te; BaseKey'lerde yok
              'special_generic_hint': ('items_special_generic_hint', {}),
              'tf_message_not_enough_seprom': ('tf_message_not_enough_seprom', {}),   # "Not enough Seprom available" (yetenek ağacı)
              'clan_errmsg_desc_to_long': ('clan_errmsg_to_long', {'_NAME_': res('label_description')})}


# Assembly tariflerinde malzeme olan kaynaklar (mağazada satılanlar: Prismatic Socket, Nano Case …; assembly.py)
ASSEMBLY_PARTS = {l for r in json.load(open(os.path.join(HERE, 'data', 'tarifler.json'), encoding='utf8'))['tarifler'].values()
                  for l in r['parcalar'] if l.startswith('resource_')}
STAT_TABLES = (('lazerler', 'hasar'), ('kalkan_jeneratorleri', 'kalkan'), ('hiz_jeneratorleri', 'hiz'))
# etkisi olmayan, satılmaz (mağazada gizli): Radar CPU'su (diplomasi renkleri: bot oyuncular). Serum CPU'su IM-01 enfeksiyonunu iyileştirir
NO_EFFECT = ('equipment_extra_cpu_rd-x',)
PAY_CURRENCY = {'currency_uridium': ('uridium', 'URI'), 'currency_credits': ('credits', 'CRE'), 'currency_experience': ('ep', 'EP'),
                'currency_honour': ('honourPoints', 'HON')}
PRIZE_CURRENCY = {'currency_uridium': 'uridyum', 'currency_credits': 'kredi', 'currency_experience': 'ep', 'currency_honour': 'onur'}
SHOP_MAX = 255                     # ShopItemListCommand.itemList'in sayacı bir bayt (protocol.LIST_MAX)
# bedava ürün (panelin mağaza fiyatı 0, "Yaratıcı"): adet seçicili üründe istemci Buy'u alınabilecek adet >= 1 iken açıyor ve adedi
# bakiye / price[0] ile buluyor; fiyat 0 ise adet 0 (UIShopSystem.CalculateAffordableAmount, SetRightNumberLevel), Buy kapanıyordu
# (kullanıcı 2026-10-25). Listede price[0] bu kadar (Decimal'e 1E-09 çevrilir: bakiye / fiyat taşmaz; tutar 2 haneye yuvarlanıp 0
# görünür), metni (cost) 0; alımın fiyatı buy_price'tan (0). Cephanede adet sınırı BEDAVA_ADET (fiyat x adet hep 0,00 kalır).
# Tıklamada toplam kutusu fiyatı yuvarlamadan yazıyor ("0.000000001 U."): istemcinin BepInEx eklentisi yuvarlar (panel/eklenti/Yamalar.cs MagazaTutari).
BEDAVA_FIYAT = 1e-9
BEDAVA_ADET = 1000000


def design_base(loot):
    """Gemi tasarımı -> ait olduğu gemi (ship_goliath_design_amber -> ship_goliath); tasarım değilse None."""
    return loot.split('_design_')[0] if loot.startswith('ship_') and '_design_' in loot else None


def slot_of(loot):
    return next((s for p, s in SLOTS if loot.startswith(p)), None)


def loose_item(loot):
    """Gemi yuvası olmayan, envantere örnek olarak giren eşya: dron ve P.E.T. tasarımı, P.E.T. dişlisi ve protokolü (hangarda takılır)."""
    return loot in DESIGNS or loot in PETM.DESIGNS or PETM.slot_for(loot) in ('gears', 'protocols')


def hidden(loot):
    """Depoda (diger_esyalar) envanterde görünmeyen ve hiçbir sistemin okumadığı eşya mı. Kaynaklar (resource_) görünür; gemisi yokken
    gelen gemi tasarımı (pending_designs) ve CBS modülü (cbs.absorb) bilerek bekler. Ödül böyle bir eşyaya düşerse kaybolmuş sayılır
    (2026-10-22: Season Pass'in dron tasarımları, rezervleri ve Assembly'nin P.E.T. protokolleri böyle kayboluyordu)."""
    return not loot.startswith(('resource_', 'module_')) and not design_base(loot)


def pet_only(loot):
    """P.E.T.'e özel lazer/jeneratör (LF-P01, SG3N-P01 …; esyalar.json yalniz_pet)."""
    return bool(ESYA['lazerler'].get(loot, ESYA['kalkan_jeneratorleri'].get(loot, {})).get('yalniz_pet'))


ITEM_TYPE = 'net.bigpoint.darkorbit.asset.item.ItemType'
# istemcinin eşya sınıfları (istemci_esyalari.json 'sinif' kısa ad -> tam ad; istemcinin metin sabitlerinden)
CLASS_PATHS = {c.split('.')[-1]: 'net.bigpoint.darkorbit.asset.' + c for c in (
    'cannonshield.CannonShieldType', 'weapon.CannonType', 'weapon.DriveType', 'lens.LensType', 'quantum.QuantumFluidCoreType',
    'shipupgrade.ShipUpgradeType', 'extra.ExtraType', 'extra.ModuleType', 'extra.UpgradeType', 'module.StationModuleType',
    'drone.DroneType', 'drone.formation.DroneFormationType', 'drone.design.DroneCustomizationType', 'drone.design.DroneDesignType',
    'pet.PetType', 'pet.design.PetCustomizationType', 'item.HardwareType', 'item.SynthesisResourceType', 'captain.CaptainType')}
_ist = json.load(open(os.path.join(HERE, 'data', 'istemci_esyalari.json'), encoding='utf8'))['esyalar']
CLIENT_CLASS = {k: v['sinif'] for k, v in _ist.items() if v.get('sinif') in CLASS_PATHS}
# Dronlara takılan ekstralar: istemcinin 'equipable' özelliğinde DRONE olanlar (AGS-X, RG-SL ve PA-X yalnız gemiye). Yuva CPU'ları
# (SLE-*) şimdilik dışarıda: yuvasını açtığı ekstralar geminin config'indedir, dronda iken çıkarılınca taşma olurdu.
# HM-7 (MERCHANT_DRONE) da dışarıda: dron yuvasında hangar çizimi düşer (istemci UINewHangarSystem.SetImageSprite NullReference,
# canlıda görüldü; öteki dron ekstraları sorunsuz), ticaret dronu gemi yuvasında kalır.
DRONE_EXTRAS = frozenset(k for k, v in _ist.items() if k.startswith('equipment_extra_') and 'DRONE' in (v.get('takilir') or ())
                         and v.get('tur') != 'MERCHANT_DRONE' and not EK.slot_bonus_of([k]))
CLIENT_SHIP_SLOTS = {k: v['yuvalar'] for k, v in _ist.items() if v.get('yuvalar')}       # gemi ve tasarım lootId -> istemcinin yuvaları
del _ist


def drone_ok(loot):
    """Dron yuvasına takılabilir mi: lazer, kalkan jeneratörü ve ekstralar (istemci SSS: "lasers, shield generators and extras.
    Speed generators can't be stored on drones"); hız jeneratörü ve roket fırlatıcı takılmaz."""
    return loot.startswith(DRONE_ITEMS) or loot in DRONE_EXTRAS


def loot_type(loot):
    """Hangar envanterinin lootType'ı: tasarımlar, esyalar.json loot_turleri (kayıtla doğrulanmış önekler), yoksa istemcinin kendi
    sınıfı. İstemci hangar envanterini sınıfa göre ayırıyor: genel ItemType giden toplar, sürücüler, mercekler, kırıcılar, QFC'ler
    ve gemi modülleri envanterde hiç görünmüyordu, hangarda takılamıyordu (canlı test H68)."""
    if loot in DESIGNS:
        return DESIGN_TYPES[DESIGNS[loot]['yuva']]
    t = next((t for p, t in sorted(ESYA['loot_turleri'].items(), key=lambda x: -len(x[0])) if loot.startswith(p)), ITEM_TYPE)
    if t == ITEM_TYPE and loot in CLIENT_CLASS:
        return CLASS_PATHS[CLIENT_CLASS[loot]]
    return t


def copy(x):
    return json.loads(json.dumps(x))


def katalog(yanitlar):
    """Standart mağaza kataloğu (panelin Dünya Editörü; profilsiz, dünyasız): kategori -> [{lootId, fiyat, para ('C' | 'U'),
    sabit (fiyatı kendi kuralıyla: dronlar, seviyeli P.E.T. ürünleri, G-HP1, yakıt)}]."""
    m = Magaza.__new__(Magaza)
    m.lists, m.catalog, m.payment, m.extra_entry, m.credit = {}, {}, {}, {}, {}
    m.build_catalog(copy(yanitlar))
    out = {}
    for cat, lst in m.lists.items():
        for it in lst['itemList']:
            loot = it['lootId']
            if loot in m.payment:
                para, u = 'U', m.payment[loot]
            elif loot in m.credit:
                para, u = 'C', m.credit[loot]
            else:
                para, u = 'U' if it.get('currency') == 'real' else 'C', (it.get('price') or [0])[0]
            sabit = loot in DRONES or loot in (PETM.HULL, PET_FUEL) or bool(PETM.level_prices(loot))
            out.setdefault(cat, []).append({'lootId': loot, 'fiyat': u, 'para': para, 'sabit': sabit})
    return out


class Magaza:
    def __init__(self, profil, yanitlar, log=print):
        self.p, self.log = profil, log
        self.dil = None          # istemcinin dili (ChatAuthenticateUserRequest.language; sosyal): ham ret metinleri (neden)
        self.kapilar = None      # Galaksi Kapıları (ödüldeki ücretsiz enerji; oturum bağlar)
        self.quest = None        # görev olayları (oturum: gorev.event; rafine edilen cevher toplama görevlerine sayılır)
        self.biletler = None     # (Season Pass, Battle Pass, günlük ödüller): oturum bağlar; pass eşyaları onlara gider
        self.yeni = None         # Aşama 9'un sistemleri (yeni_sistemler.py): N.O.V.A. ve QFC ödülleri onlara gider
        self.chromin = None      # Chromin Rush (chromin.py; oturum bağlar): Chromin girişi sınırla
        self.hitac = None        # Hitac Word Puzzle (hitac_piyango.py; oturum bağlar): kutudaki harf
        self.world = lambda: None  # current World (the session sets it): drone formation wait (formation_wait)
        self.lists, self.catalog = {}, {}
        self.payment = {}        # tek oyunculu: gerçek parayla satılan ("Payment") eşya -> uridyum fiyatı
        self.extra_entry = {}    # ek_magaza satırı (takvim / bir_kez: Ö7 dükkânlarının paketleri)
        self.credit = {}         # market dengesi: kredili "Payment" ürünü -> kredi fiyatı (data/fiyatlar.json)
        self.shop_gate = None    # (satır, lootId) -> şimdi satılır mı (dukkanlar.py: etkinlik, kampanya, bir kez, seviye)
        self.on_bought = []      # alımdan sonra (lootId, adet) -> mesajlar (dukkanlar.py: VIP, Pre-BF, Mileage sayaçları)
        self.build_catalog(yanitlar)
        first = lambda req, name: next((m for e in yanitlar.get(req, []) for m in e['yanit'] if m['_m'] == name), None)
        self.equip_tpl = first('HangarShipEquipmentRequest', 'HangarShipEquipmentCommand')
        self.ships_tpl = first('HangarListRequest', 'HangarShipsCommand')
        self.detail_tpl = first('HangarShipDetailRequest', 'HangarShipDetailCommand')
        self.item_tpl, self.tpl_ids = None, {}
        for pack in (self.ships_tpl or {}).get('items', []):
            for it in pack.get('items', []):
                self.item_tpl = self.item_tpl or it
                self.tpl_ids.setdefault(it['lootId'], it['itemid'])
        self.sent_lists = set()          # bu oturumda istemciye gönderilen mağaza kategorileri
        self.featured = None             # (kategori, lootId, bitiş): ödeme düğmesinin ürünü listenin başında (odeme.py)
        self.pet = PETM.Pet(profil, log)  # oturum kendi P.E.T.'ini bağlar (uzaydaki davranış dünyayla)
        self.pet.on_stats = self.apply_stats       # HEAT bonusu değişince gemi değerleri
        for loot, n in list(profil.d.get('diger_esyalar', {}).items()):
            if loot.startswith('pet_designs_'):       # Aşama 6 öncesi depoda saklanan P.E.T. tasarımları -> envanter
                for _ in range(n):
                    profil.new_item(loot)
                profil.add_resource(loot, -n)

    def build_catalog(self, yanitlar):
        """Katalog: kayıttaki ShopItemListCommand'ler + ek mağaza + P.E.T. yakıtı; fiyatlar (market dengesi, sonra dünyanın mağazası)."""
        fiyat = ESYA['odeme_fiyatlari']
        for e in yanitlar.get('ShopItemListRequest', []):
            for m in e['yanit']:
                if m['_m'] == 'ShopItemListCommand':
                    self.lists.setdefault(m['category'], m)
                    for it in m['itemList']:
                        self.catalog.setdefault(it['lootId'], it)
                        if it.get('cost') == 'Payment' or it.get('isPaymentItem'):
                            self.payment.setdefault(it['lootId'], fiyat['ozel'].get(it['lootId'], fiyat.get(m['category'], fiyat['varsayilan'])))
        for cat, extra in ESYA['ek_magaza'].items():     # kayıtta olmayan, tek oyunculuda başka yoldan alınamayan eşyalar
            lst = self.lists.get(cat) if not cat.startswith('_') else None
            for x in (extra if lst else []):
                self.extra_entry[x['lootId']] = x
                tpl = self.catalog.get(x['sablon'])
                if tpl and x['lootId'] not in self.catalog:
                    kr = 'kredi' in x                    # kredili satır (Liberator 40.000 C: oyuncu isteği 2026-10-30)
                    tutar = x['kredi'] if kr else x['uridyum']
                    it = dict(copy(tpl), lootId=x['lootId'], price=[float(tutar)], currency='virtual' if kr else 'real', isPaymentItem=0,
                              cost='{:,} {}'.format(tutar, 'C.' if kr else 'U.'))
                    lst['itemList'].append(it)
                    self.catalog[x['lootId']] = it
        # P.E.T. yakıtı PET/GEAR sekmesinde, kısayolun birim fiyatıyla (uridyum: gerçek kayıt 1.000 birim = 250 U, yani birimi 0,25 U),
        # adet seçilerek (kayıttaki mağazada yok; kullanıcı bildirimi 2026-10-25: yalnız kısayolla ve otomatik alınıyordu). Şablon:
        # uridyumlu, adet seçilen cephane satırı
        lst, tpl = self.lists.get('petgear'), self.catalog.get('ammunition_rocketlauncher_ubr-100')
        if lst and tpl and PET_FUEL not in self.catalog:
            f = PETM.PET['yakit_satin']
            it = dict(copy(tpl), lootId=PET_FUEL, category='petgear', price=[f['uridyum'] / f['adet']], currency='real',
                      cost='{:g} U.'.format(f['uridyum'] / f['adet']))
            lst['itemList'].append(it)
            self.catalog[PET_FUEL] = it
        self.apply_prices()

    def apply_prices(self):
        """Market dengesinin fiyatları (data/fiyatlar.json <- tools/market_dengesi.py): Payment ürünlerinin ve ek mağazanın
        fiyatı tek ölçekle; içeriği kredi sınıfı olanlar kredili."""
        for loot, r in FIYAT.items():
            it = self.catalog.get(loot)
            if r['para'] == 'C':
                self.payment.pop(loot, None)
                if it is not None and (it.get('cost') == 'Payment' or it.get('isPaymentItem')):
                    self.credit[loot] = r['fiyat']
                elif it is not None:
                    it.update(price=[float(r['fiyat'])], currency='virtual', cost='{:,} C.'.format(r['fiyat']))
            elif loot in self.payment:
                self.payment[loot] = r['fiyat']
            elif it is not None and loot in self.extra_entry:
                it.update(price=[float(r['fiyat'])], currency='real', cost='{:,} U.'.format(r['fiyat']))

    @property
    def hangar_id(self):
        return self.p.ship()['hangarId']

    @property
    def ship_id(self):
        return int(self.p.d['aktif_gemi'])

    # ------------------------------------------------------------ yardımcılar
    def handles(self, name, f):
        if name == 'MenuActionRequest':
            mid = f.get('menuItemId', '')
            # Quick-buy activation is actionType=1 (slot-bar click, item-bar double click); the recorded server ignores 0.
            return (mid.startswith('buy_') and f.get('actionType') == 1) or mid in FORMS
        return name in ('ShopItemListRequest', 'ShopItemBuyRequest', 'HangarShipEquipmentRequest', 'HangarListRequest',
                        'HangarShipDetailRequest', 'HangarShipMoveItemsRequest', 'LabRefinementRequest', 'LabUpdateItemRequest',
                        'LabUpdateRequest', 'HangarShipUnlockSlotRequest', 'HangarShipRenamePetRequest', 'HangarShipSellItemRequest',
                        'HangarShipSellDroneRequest', 'HangarShipFavouriteRequest', 'HangarShipClearConfigRequest',
                        'HangarShipSaveConfigRequest', 'HangarShipLoadConfigRequest', 'HangarShipImportConfigRequest')

    def ship_sid(self, ship_id):
        """İstekteki shipId profilde yoksa etkin gemi."""
        return str(ship_id) if str(ship_id) in self.p.d['gemiler'] else self.p.d['aktif_gemi']

    def handle(self, name, f):
        """İsteğe yanıt mesajları; None ise kayıtlı yanıta bırakılır."""
        if name == 'ShopItemListRequest':
            m = self.shop_list(f.get('category', ''))
            if m:
                self.sent_lists.add(f.get('category', ''))
            return [m] if m else None
        if name == 'HangarShipSellItemRequest':
            return self.sell(f)
        if name == 'HangarShipSellDroneRequest':
            return self.sell_drone(f)
        if name == 'ShopItemBuyRequest' and f.get('action') == 'toggleSubscription':
            return self.toggle_subscription(f.get('lootId', ''), f.get('category', ''), f.get('buyCategory', ''))
        if name == 'ShopItemBuyRequest':
            return self.buy(f.get('lootId', ''), f.get('amount', 1), f.get('category', ''), f.get('buyCategory', ''),
                            pet_name=f.get('petName') or '', level=f.get('level') or 1)
        if name == 'MenuActionRequest':
            if f['menuItemId'] in FORMS:
                return self.change_formation(f['menuItemId'])
            return self.quick_buy(f['menuItemId'][4:])
        if name == 'HangarShipEquipmentRequest':
            return [self.equipment_cmd(self.ship_sid(f.get('shipId')))] if self.equip_tpl else None
        if name == 'HangarListRequest':
            if not self.ships_tpl:
                return None
            # istemcinin hangar gemi ızgarası mağazanın gemi listesini kullanır; liste gelmeden hangar açılırsa
            # HangerListCallBack NullReferenceException verir (canlı test). Kayıtta mağaza hep önce açılmıştı.
            with self.p.lock:          # istemcinin göremediği yuvalarda kalanlar (önceden takılmış) envantere: yoksa hangar açılmıyor
                trimmed = [i for sid in self.p.d['gemiler'] for i in self.trim_slots(sid)]
                if trimmed:
                    self.p.sync_ekipman()
                    self.p.dirty = True
                    self.log('   hangar: yuvası olmayan %d eşya envantere indi' % len(trimmed))
            pre = []
            if 'ship' not in self.sent_lists and self.shop_list('ship'):
                pre.append(self.shop_list('ship'))
                self.sent_lists.add('ship')
            return pre + [self.ships_cmd()]
        if name == 'HangarShipDetailRequest':
            return [self.detail_cmd(self.ship_sid(f.get('shipId')))] if self.detail_tpl else None
        if name == 'HangarShipMoveItemsRequest':
            return self.move(f)
        if name == 'HangarShipFavouriteRequest':
            return self.favourite(f)
        if name == 'HangarShipClearConfigRequest':
            return self.clear_config(f)
        if name == 'HangarShipSaveConfigRequest':
            return self.save_config(f)
        if name == 'HangarShipLoadConfigRequest':
            return self.load_config(f)
        if name == 'HangarShipImportConfigRequest':
            return self.import_config(f)
        if name == 'LabRefinementRequest':
            return self.refine(f)
        if name == 'LabUpdateItemRequest':
            return self.upgrade(f)
        if name == 'LabUpdateRequest':
            return [self.lab_cmd()]
        if name == 'HangarShipUnlockSlotRequest':
            return self.pet.unlock(f) + self.money_msgs()
        if name == 'HangarShipRenamePetRequest':
            return self.pet.rename(f)
        return None

    # ------------------------------------------------------------ rafine etme ve yükseltmeler
    def lab_cmd(self):
        return ('LabUpdateItemCommand', {'itemsUpdatedInfo': self.p.lab_items()})

    def refine(self, f):
        """LabRefinementRequest {toProduce: {oreType, count}}: tarif kadar hammadde düşer, ürün eklenir (istemcinin game.xml tarifleri)."""
        m = f.get('toProduce') or {}
        t, n = (m.get('oreType') or {}).get('typeValue'), int(m.get('count') or 0)
        recipe = LAB['tarifler'].get(str(t))
        if not recipe or n <= 0:
            return []
        need = {int(k): v * n for k, v in recipe.items()}
        short = [k for k, v in need.items() if self.p.ore_count(k) < v]
        if short:
            self.log('   rafine olmadı: %s x%d (eksik %s)' % (ORES.get(t), n, ', '.join(ORES.get(k, str(k)) for k in short)))
            return [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.d['madenler']})]
        self.p.remove_ores(need)
        totals = self.p.add_ores({t: n})
        self.log('   rafine: %s x%d (%s)' % (ORES.get(t), n, ', '.join('%s %d' % (ORES.get(k), v) for k, v in need.items())))
        msgs = [('AttributeOreCountUpdateCommand', {'oreCountList': totals}), self.ore_pack(sorted(need) + [t])]
        return msgs + (self.quest('loot', loot=ORES.get(t), amount=n) if self.quest else [])

    def upgrade(self, f):
        """LabUpdateItemRequest {itemToUpdate, updateWith {oreType, count}}: cevher parçaya yüklenir, her cevher LAB['birim']: lazer/
        roket 10 tur/adet, motor/kalkan 10 dakika (en çok LAB['azami']; artan cevher kargoda kalır). Aynı cevher eklenir, başka cevher
        öncekini siler (istemci: lab_alert).
        Hız ve kalkan hemen değişir."""
        item = (f.get('itemToUpdate') or {}).get('itemValue')
        m = f.get('updateWith') or {}
        t, n = (m.get('oreType') or {}).get('typeValue'), int(m.get('count') or 0)
        if str(item) not in LAB['bonuslar'] or str(t) not in LAB['bonuslar'][str(item)] or n <= 0 or self.p.ore_count(t) < n:
            self.log('   yükseltme olmadı: parça %s, cevher %s x%d (elde %d)' % (item, t, n, self.p.ore_count(t) if t is not None else 0))
            return [self.lab_cmd()]
        old = self.p.d.get('yukseltmeler', {}).get(str(item))
        have = old[1] if old and old[0] == t else 0
        n = min(n, max(0, LAB['azami'] - have) // LAB['birim'][str(item)])
        if n <= 0:
            self.log('   yükseltme olmadı: parça %s dolu (%d)' % (item, have))
            return [self.lab_cmd()]
        totals = self.p.remove_ores({t: n})
        with self.p.lock:
            ups = self.p.d.setdefault('yukseltmeler', {})
            ups[str(item)] = [t, have + n * LAB['birim'][str(item)]]
            self.p.dirty = True
        key = ('lab_upgrade_laser', 'lab_upgrade_rocket', 'lab_upgrade_speed', 'lab_upgrade_shield')[item]
        self.log('   yükseltme: parça %d <- %s x%d (toplam %d)' % (item, ORES.get(t), n, ups[str(item)][1]))
        return ([('AttributeOreCountUpdateCommand', {'oreCountList': totals}), self.ore_pack([t]), self.lab_cmd()] + self.apply_stats()
                + [legacy('0|A|STM|%s' % key)]
                + (self.quest('ore_update', tur=('LASER', 'ROCKET', 'SPEED', 'SHIELD')[item], ore=ORES.get(t)) if self.quest else []))

    def item_id(self, loot):
        return self.p.d['esya_kimlik'].get(loot) or self.tpl_ids.get(loot) or self.p.item_id(loot)

    def capacity(self, slot, sid=None, cid=None, extras=None):
        """Geminin bir yuva türündeki yuva sayısı. Ekstra yuvası config'e göre: o config'teki (cid; yoksa etkin) ya da verilen
        ekstralardaki (extras: lootId listesi) yuva CPU'suyla (SL-01..04). Önce hep etkin config'in CPU'su sayılıyordu: öteki
        config'e takılan Slot CPU yuva açmıyordu (kullanıcı bildirimi 2026-10-24)."""
        if slot == 'upgrades':                                       # gemi modülü yuvası: istemcinin gemi verisi (gemi_modul.py)
            return GM.slots(self.p.ship(sid)['lootId'])
        if slot == 'QuantumFluidCore':                               # QFC yuvası: istemcinin gemi verisi (qfc.py)
            return QF.slots(self.p.ship(sid)['lootId'])
        if slot in PC.SLOTS:                                         # top, kırıcı, sürücü, mercek: istemcinin gemi verisi
            return PC.slots(self.p.ship(sid)['lootId'], slot)
        ship = self.p.ship_row(sid)                                  # giyilen tasarımın yuvalarıyla (Tyrannos 15 lazer …)
        bonus = 0
        if slot == 'extra':
            bonus = EK.slot_bonus_of(extras) if extras is not None else EK.slot_bonus(self.p, sid, cid)
        if slot == 'extra' and self.equip_tpl and 'extra' not in ship:
            return self.equip_tpl.get('extrasSlotsSize1', DEFAULT_SLOTS['extra']) + bonus
        n = ship.get(slot, DEFAULT_SLOTS[slot]) + bonus
        if slot in CLIENT_SLOTS:          # istemci bu yuvaları kendi gemi verisinden çizer (HangarShipEquipmentCommand'da sayısı yok):
            # elle artırılan esyalar.json yuvalarına takılan görünmüyor, ikinci düzenlemede hangar açılmıyordu (oyuncu bildirimi 2026-10-31)
            y = CLIENT_SHIP_SLOTS.get(self.p.ship_look(sid)) or CLIENT_SHIP_SLOTS.get(self.p.ship(sid)['lootId']) or {}
            n = min(n, y.get(CLIENT_SLOTS[slot], n))
        return n

    def trim_slots(self, sid):
        """Yuvasından fazla takılı lazer, jeneratör ve fırlatıcı envantere (kilit altında) -> inenlerin kimlikleri."""
        trimmed = []
        for cfg in self.p.ship(sid)['konfigler'].values():
            for slot in ('laser', 'generators', 'rocket'):
                lst = cfg.get(slot, [])
                trimmed += lst[self.capacity(slot, sid):]
                del lst[self.capacity(slot, sid):]
        return trimmed

    def inv_item(self, iid, loot, amount, hangar=0, level=None):
        lv = YK.item_level(self.p, iid) if str(iid) in self.p.d['esyalar'] else 0     # yükseltme seviyesi (yukseltme.py)
        lv = lv if level is None else level
        return ('InventoryItemUpdatedCommand', {'item': mod('InventoryItemModule', upgradeLevel=lv, lootId=loot, amount=amount, itemId=iid,
                                                            star=(PC.state(self.p, iid) or {}).get('yildiz', 0), isNew=False,
                                                            hangarId=hangar, extAttributes=[], inventoryItemAttributes=[])})

    def drone_item(self, x):
        """Dron, istemcinin envanterinde eşya olarak (kimliği dronun kimliği, seviyesi yükseltme seviyesi): Assembly'nin Upgrade
        sekmesi yükseltilecekleri yalnız envanterdeki eşyalardan seçiyor; dronlar hiç gönderilmediği için Iris, Apis, Zeus (ve Flax)
        listede yoktu (kullanıcı bildirimi 2026-10-24). Build isteğinin targetItemId'si dronun kimliği (yukseltme.target).
        Dronun seviyesi (1-6) InventoryItemAttributeKey.LEVEL (1) niteliğinde: Upgrade sekmesi bonus satırını ondan kuruyor
        (ItemBuff.ParseDrone: lootId + (seviye - 1) adlı seviye verisinin "upgradable"ı). Liste boşken "drone_iris-1" bulunamıyor,
        satır beyaz simge ve "-1%" gösteriyordu (kullanıcı bildirimi 2026-10-24)."""
        msg = self.inv_item(x['kimlik'], x['lootId'], 1, self.hangar_id, level=YK.drone_level(x))
        msg[1]['item']['inventoryItemAttributes'] = [mod('InventoryItemAttributeModule', key=1, value=str(x['seviye']))]
        return msg

    def hangar_item(self, iid, loot, count, hangar=0, level=None):
        it = copy(self.item_tpl) if self.item_tpl else mod(
            'HangarShipEquipmentInventoryItem', moduleRepairCosts=0, modifiers='', star=0, UpgradeLevel=[], charges=-1, setBonusAmt=0,
            setBonusInfo=[], attachedAmmo='', extAttributes=[], setBonusActiveConfig1=False, setBonusActiveConfig2=False,
            currentHitPoints=1, maxHitPoints=0, asteroidId=-1, level=0, setBonus=False, modifier='', isUnstableShipUpgrade=False, ships='')
        it.update(itemid=iid, lootId=loot, itemCount=count, hangarId=hangar, lootType=loot_type(loot))
        if GM.unstable(loot) and str(iid) in self.p.d['esyalar']:
            it['isUnstableShipUpgrade'] = True                          # kararsız modül (gemi_modul.py)
            it['ships'] = GM.ship_ids(GM.state(self.p, iid)['gemiler'])   # ipucu: "+%5 hasar için Goliath, …"
            it['modifiers'] = GM.modifiers_str(self.p, iid)
        if PC.is_item(loot) and str(iid) in self.p.d['esyalar']:
            it.update(PC.hangar_fields(self.p, iid, loot))              # top: temel hasar, nitelikler, yıldız, UL'nin gemisi
        elif RZ.is_item(loot) and str(iid) in self.p.d['esyalar']:
            it['modifiers'] = RZ.modifiers_str(self.p, iid)             # Xeno Resonator'ın nitelikleri (Ö6)
        elif loot.startswith(QF.PREFIX) and QF.state(self.p, iid):
            it['ships'] = GM.ship_ids([QF.state(self.p, iid)['gemi']])  # QFC: bağlı gemi ve nitelikleri (qfc.modifiers_str)
            it['modifiers'] = QF.modifiers_str(self.p, iid)
        if EK.attached(self.p, loot):
            it['attachedAmmo'] = EK.attached(self.p, loot)      # otomatik alım CPU'sunun seçili cephanesi
        if PETM.has_levels(loot):
            # P.E.T. dişlisi/protokolü: istemci level'ı olduğu gibi "Level: %level%" gösterir (TooltipPreparerFactory.ReturnItemLevel),
            # açıklamayı level - 1'den arar (ReturnItemTips.ReturnItemTip). Önceden level - 1 gidiyordu: 1. seviye "Level 0", 4. seviye
            # 3. seviyenin açıklamasıyla (kullanıcı bildirimi 2026-10-24)
            it['level'] = level if level is not None else self.p.item_level(iid)
        elif YK.max_level(loot) and str(iid) in self.p.d['esyalar']:
            it['level'] = YK.item_level(self.p, iid)               # yükseltme seviyesi (0 = istemcide 1)
            it['UpgradeLevel'] = YK.badge(loot, it['level'])       # envanter ve yuvalardaki seviye rozeti
        return it

    def pack(self, items):
        return ('InventoryItemPack', {'items': items})

    def item_updates(self, ids):
        """Takılı olduğu hangar değişen eşyalar: istemcinin envanteri ve hangar ızgarası (move'daki gibi). Config yükleme ve
        aktarımda gitmiyordu: yüklenen lazerler hem yuvada hem envanterde, boşa çıkanlar envanterde görünmüyordu (canlı 2026-10-24)."""
        es, hm = self.p.d['esyalar'], self.p.hangar_map()
        ids = sorted(i for i in set(ids) if str(i) in es)
        items = [self.hangar_item(i, es[str(i)], 1, hm.get(i, 0)) for i in ids]
        return [self.inv_item(i, es[str(i)], 1, hm.get(i, 0)) for i in ids] + \
            [self.pack(items[k:k + PACK_MAX]) for k in range(0, len(items), PACK_MAX)]

    def ore_pack(self, types):
        """Cevher sayısı değişince hangar envanterindeki cevher eşyaları (kayıt: toplamada InventoryItemPack, itemCount yeni sayı)."""
        return self.pack([self.hangar_item(self.item_id(ORES[t]), ORES[t], self.p.ore_count(t)) for t in types if t in ORES])

    # ------------------------------------------------------------ mağaza
    def drone_slots(self, loot):
        """Bu türden kaç dron daha alınabilir: Flax/Iris birlikte en çok dron_azami (8); Apis ve Zeus birer tane, sınırın dışında
        (wiki: en çok 10)."""
        ds = self.p.d['dronlar']
        if DRONES[loot].get('tek'):
            return 0 if any(x['lootId'] == loot for x in ds) else 1
        return max(0, ESYA['dron_azami'] - sum(1 for x in ds if not DRONES[x['lootId']].get('tek')))

    def drone_room(self, loot):
        return self.drone_slots(loot) > 0

    def owned_unique(self, loot):
        """Unique item the player already has: ship, ship design, drone formation, unique drone, P.E.T. The official shop
        stops listing these once bought."""
        if loot == PET_LOOT:
            return self.pet.owned
        if loot.startswith('ship_'):
            if design_base(loot):
                return any(loot in s.get('tasarimlar', []) for s in self.p.d['gemiler'].values())
            return any(s['lootId'] == loot for s in self.p.d['gemiler'].values())
        if loot in FORMS:
            return loot == 'drone_formation_default' or loot in self.p.d['formasyonlar']
        if loot in DRONES and DRONES[loot].get('tek'):
            return self.drone_slots(loot) == 0
        if loot.startswith(('package_', 'deal_')):
            return self.package_done(loot)
        return False

    @staticmethod
    def unique_loot(g):
        """Bir kez sahip olunan eşya: gemi, gemi tasarımı, drone formasyonu, P.E.T., tekil dron."""
        return g.startswith('ship_') or g in FORMS or g == PET_LOOT or bool(g in DRONES and DRONES[g].get('tek'))

    def package_done(self, loot):
        """Benzersiz paket (içinde gemi, tasarım, formasyon, P.E.T. ya da tekil dron olan; Defcom-Raven, Stellar, Dusklight …) bir kez
        alınır; alındıysa ya da benzersiz içeriğinin hepsi zaten varsa mağazada görünmez ve alınamaz (oyuncu bildirimi 2026-10-27:
        Defcom paketi alındıktan sonra listede kalıyordu). Panelin 'paket_siniri' ayarı kapatır (o zaman sahip olunan içerik atlanır,
        gerisi verilir: package_fit)."""
        if not AY.get('paket_siniri'):
            return False
        unique = [g for g, n in (self.contents(loot, 1) or []) if self.unique_loot(g)]
        if not unique:
            return False
        return loot in self.p.d.get('benzersiz_paketler', []) or all(self.owned_unique(g) for g in unique)

    def package_fit(self, grants, owned):
        """Paket içeriğinden şimdi verilebilenler: sahip olunan gemi, P.E.T. ve formasyon atlanır, dronlar boş yer kadar verilir
        -> (verilecekler, [(lootId, atlanan adet, hata anahtarı)])."""
        fit, skipped, taken = [], [], 0             # taken: bu pakette sayılan Flax/Iris (ortak sınır)
        for g, n in grants:
            if g.startswith('ship_') and not design_base(g) and g in owned:
                skipped.append((g, 1, 'items_shop_error_ship_contains_ship'))
            elif g == PET_LOOT and self.pet.owned:
                skipped.append((g, 1, 'eqt_error_generic'))
            elif g in FORMS and (g == 'drone_formation_default' or g in self.p.d['formasyonlar']):
                skipped.append((g, 1, 'items_drone_formation_already_in_use'))
            elif g in DRONES:
                tek = DRONES[g].get('tek')
                k = max(0, min(n, self.drone_slots(g) - (0 if tek else taken)))
                taken += 0 if tek else k
                if k:
                    fit.append((g, k))
                if k < n:
                    skipped.append((g, n - k, 'drone_have_max'))
            else:
                fit.append((g, n))
        return fit, skipped

    @staticmethod
    def skipped_msg(skipped):
        """Paketten verilemeyenlerin ekran mesajı (ör. "Already owned, not given: P.E.T., 8x Iris")."""
        import kapi as KAPI
        name = lambda g: 'P.E.T.' if g == PET_LOOT else g.rsplit('_', 1)[-1].title()
        return KAPI.screen('Already owned, not given: ' + ', '.join(('%dx %s' % (n, name(g))) if n > 1 else name(g)
                                                                  for g, n, key in skipped))

    def drone_price(self, loot):
        """Flax/Iris: aynı türden kaçıncı dron olduğuna göre (wiki: Flax 100.000 C'den ikiye katlanır, Iris 15.000 U'dan artar)."""
        info = DRONES[loot]
        n = sum(1 for x in self.p.d['dronlar'] if x['lootId'] == loot)
        return info['para'], info['fiyatlar'][min(n, len(info['fiyatlar']) - 1)]

    def world_price(self, loot):
        """Dünya Editörü'nün fiyatı -> (para birimi alanı, fiyat) ya da None; kendi kuralıyla fiyatlananlar (dronlar, G-HP1, yakıt,
        seviyeli P.E.T. ürünleri) hariç."""
        w = DUNYA_MAGAZA.get(loot)
        if not w or w.get('fiyat') is None or loot not in self.catalog or loot in DRONES or loot in (PETM.HULL, PET_FUEL) or PETM.level_prices(loot):
            return None
        return ('credits' if w.get('para') == 'C' else 'uridium'), w['fiyat']

    def price(self, loot, level=1):
        """-> (para birimi alanı, birim fiyat) ya da None (kayıtta olmayan eşya). "Payment" eşyalar uridyumla.
        P.E.T. dişli/protokolleri seviyeye göre (wiki fiyatları, uridyum). Dünyanın fiyatı önce."""
        wp = self.world_price(loot)
        if wp:
            return wp
        if loot in DRONES:
            return self.drone_price(loot)
        if loot == PETM.HULL:                        # G-HP1: kaçıncı yükseltme olduğuna göre (P.E.T. seviyesi kadar)
            u = self.pet.hull_price()
            return ('uridium', u) if u else None
        prices = PETM.level_prices(loot)
        if prices and loot in self.catalog:
            return 'uridium', prices[min(max(int(level), 1), len(prices)) - 1]
        if loot in self.payment:
            return 'uridium', self.payment[loot]
        if loot in self.credit:
            return 'credits', self.credit[loot]
        it = self.catalog.get(loot)
        if not it or it.get('cost') == 'Payment' or it.get('currency') not in CURRENCY or not it.get('price') or it['price'][0] < 0:
            return None          # 0 fiyat geçerli: Phoenix mağazada 0 C
        return CURRENCY[it['currency']], it['price'][0]

    def buy_price(self, loot, level=1):
        """Satın alma fiyatı: price() x panelin mağaza fiyatı çarpanı (satış ve geri dönüşüm değerleri price()'tan, çarpansız); uridyumla
        alımlarda Shop Discount."""
        pr = self.price(loot, level)
        uri = bool(pr) and pr[0] == 'uridium'
        k = AY.carpan('magaza_fiyat', 'uridyum' if uri else 'kredi') * (1 - self.discount() if uri else 1)
        return pr if not pr or k == 1.0 else (pr[0], pr[1] * k)

    def discount(self):
        """Uridyumla alımlarda indirim oranı (esyalar.json magaza_indirimi): Premium %5 (herkes) + Shop Discount sürüyorsa oranı."""
        m = ESYA['magaza_indirimi']
        return round((m['premium_oran'] if self.p.premium else 0.0) + (m['oran'] if self.p.d.get('magaza_indirimi', 0) > time.time() else 0.0), 4)

    def gate_ok(self, loot):
        if DUNYA_MAGAZA.get(loot, {}).get('satista') is False:      # Dünya Editörü: satıştan kaldırılan ürün
            return False
        if not EG.in_shop(loot):          # panelin ayarı kapalıyken etkinlik görünümleri yalnız etkinliklerinden
            return False
        entry = self.extra_entry.get(loot) or FORM_RULES.get(loot)      # Bat yalnız Halloween'de satılır (formasyon_kurallari.takvim; wiki)
        return self.shop_gate(entry, loot) if self.shop_gate else True

    def shop_list(self, category):
        t = self.lists.get(category)
        if not t:
            return None
        t = copy(t)
        t['currentShipLootId'] = self.p.ship()['lootId']
        if not self.pet.owned:          # yakıt P.E.T.'le
            t['itemList'] = [it for it in t['itemList'] if it['lootId'] != PET_FUEL]
        # unique items already owned are not listed (official shop): the list sent after a purchase drops the item at once
        t['itemList'] = [it for it in t['itemList'] if not self.owned_unique(it['lootId'])]
        # sunucuda karşılığı olmayanlar (Assembly parçaları, anahtarlar, içeriği tanımlanmamış paketler …) gösterilmez
        t['itemList'] = [it for it in t['itemList'] if self.contents(it['lootId'], 1) is not None and self.gate_ok(it['lootId'])]
        if category == 'shipdesign':
            # ek mağazanın gemi tasarımları (E4 ve E11'in kaynaksız tasarımları, ~270) sekmeye sığmaz (SHOP_MAX): yalnız hangardaki
            # gemilerinki, şimdiki geminin tasarımları önce (fazlası sondan kesilir; kayıttakiler hep)
            owned = {s['lootId'] for s in self.p.d['gemiler'].values()}
            extra = lambda it: it['lootId'] in self.extra_entry
            t['itemList'] = [it for it in t['itemList'] if not extra(it) or design_base(it['lootId']) in owned]
            t['itemList'].sort(key=lambda it: extra(it) and design_base(it['lootId']) != t['currentShipLootId'])
        for it in t['itemList']:
            if (self.extra_entry.get(it['lootId']) or {}).get('bir_kez'):
                it['maxAmount'] = 1                          # Ö7 paketleri: etkinlikte bir kez
            elif (self.extra_entry.get(it['lootId']) or {}).get('en_cok'):
                it['maxAmount'] = self.extra_entry[it['lootId']]['en_cok']      # forum 109162: Süper Destek Paketi 15
        t['itemList'] = [it for it in t['itemList'] if it['lootId'] != PETM.HULL or self.pet.hull_price()]
        for it in t['itemList']:
            if it['lootId'] == PETM.HULL:
                u = self.pet.hull_price()
                it.update(price=[float(u)], cost='{:,} U.'.format(u))
        for it in t['itemList']:
            if it['lootId'] in self.payment:
                u = self.payment[it['lootId']]
                it.update(price=[float(u)], currency='real', cost='{:,} U.'.format(u), isPaymentItem=0, elite=1)
            elif it['lootId'] in self.credit:
                c = self.credit[it['lootId']]
                it.update(price=[float(c)], currency='virtual', cost='{:,} C.'.format(c), isPaymentItem=0, elite=1)
        for it in t['itemList']:            # Dünya Editörü'nün fiyatı (oyun açıkken değişebilir: her listede)
            wp = self.world_price(it['lootId'])
            if wp:
                kr = wp[0] == 'credits'
                it.update(price=[float(wp[1])], currency='virtual' if kr else 'real', cost='{:,} {}'.format(int(wp[1]), 'C.' if kr else 'U.'),
                          isPaymentItem=0)
        for it in t['itemList']:
            if it['lootId'] in DRONES:
                cur, u = self.drone_price(it['lootId'])
                it.update(price=[float(u)], cost='{:,} {}'.format(u, 'U.' if cur == 'uridium' else 'C.'))
            prices = PETM.level_prices(it['lootId'])
            if prices:                    # seviye seçicisi: seviye başına fiyat
                it.update(price=[float(u) for u in prices])
        kc, ku, disc = AY.carpan('magaza_fiyat', 'kredi'), AY.carpan('magaza_fiyat', 'uridyum'), self.discount()
        if kc != 1.0 or ku != 1.0 or disc:              # panelin mağaza fiyatı çarpanı ve Shop Discount (uridyum): istemcinin gösterdiği fiyat ve metin
            for it in t['itemList']:      # (istemci UserInventoryModule.activePremiumDiscount'u fiyata uygulamıyor, canlı tur 2)
                if it.get('price') and it['price'][0] > 0 and it.get('cost') != 'Payment':
                    ki = ku * (1 - disc) if it.get('currency') == 'real' else kc
                    if it['lootId'] == PET_FUEL:         # birim 0,25 U: tavana yuvarlanmaz (1 U görünür, 4 kat pahalı sanılırdı)
                        it['price'] = [round(u * ki, 4) for u in it['price']]
                        it['cost'] = '{:g} U.'.format(round(it['price'][0], 2))
                        continue
                    it['price'] = [float(math.ceil(u * ki - 1e-9)) for u in it['price']]
                    it['cost'] = '{:,} {}'.format(int(it['price'][0]), 'U.' if it.get('currency') == 'real' else 'C.')
        for it in t['itemList']:
            prices = PETM.level_prices(it['lootId'])
            if prices:
                # seviye düğmeleri: istemci (UIShopSystem.SetRightNumberLevel) düğme i'yi i <= MaxNum ise açıyor, MaxNum = alınabilecek
                # adet ile maxAmount'un küçüğü (3 ise hepsi). Kayıttaki maxAmount 1'di (hesapta P.E.T. yoktu), sunucu değiştirmiyordu:
                # P.E.T. seviyesi ne olursa olsun yalnız 1. seviye seçiliyordu (kullanıcı 2026-10-18). maxAmount = P.E.T.'in izin verdiği
                # en yüksek seviye (wiki: 2. seviye P.E.T. 4, 3. seviye 8, 3X 20). Satılan 4. kademesi olan dişliler "3X" düğmesiyle
                # (kayıt: G-EL1/G-RL1 levelGrades [1,2,3,3X]); protokollerin 4. kademesi mağazada satılmaz, kayıttaki gibi [1,2,3]
                lv = self.pet.d['seviye'] if self.pet.owned else 0
                grades = [str(n) for n in range(1, min(len(prices), 3) + 1)]
                if len(prices) > 3 and prices[3] and it['lootId'] in PETM.GEARS:
                    grades.append('3X')
                top = min(len(grades), max(n for n in range(1, len(prices) + 1) if lv >= PETM.level_need(n)))
                it.update(maxAmount=top, maxlevel=top, levelGrades='[%s]' % ','.join(grades))
            if prices and it.get('LevelDataList'):
                # seviye düğmesinin fiyatı ve metni (ClickToggle: LevelDataList[seviye]) alınanla aynı: kayıttakiler kaldı, G-HR1'de
                # 15.000 / 32.000 görünüp 32.000 / 55.000 alınıyordu; panelin çarpanı da burada
                rows = it['LevelDataList'] = [dict(r) for r in it['LevelDataList']]
                for r, u0, u in zip(rows, prices, it['price']):
                    if u0:                                 # 0: mağazada satılmaz (kayıttaki satır kalır); u çarpanla 0 olabilir (bedava)
                        r.update(price=int(u), cost='{:,} U.'.format(int(u)))
            if it['lootId'] == PETM.HULL and it.get('LevelDataList'):
                # G-HP1 G-REP1'in kopyası (ek_magaza sablon): detay paneli ve onay penceresi LevelDataList'ten okuyor, kopyada G-REP1'in
                # fiyatları kalıyordu (2.500 U. gösterilip 25.000 U. alınıyordu, canlı 2026-10-24): her satırda yükseltmenin fiyatı
                it['LevelDataList'] = [dict(r, price=int(it['price'][0]), cost=it['cost']) for r in it['LevelDataList']]
        for it in t['itemList']:
            if it['lootId'] == PET_FUEL:          # en çok deponun boş yeri ve paranın yettiği kadar
                pr = self.buy_price(PET_FUEL)
                n = min(self.fuel_room(), int(self.p.d['pilot'].get(pr[0], 0) // pr[1]) if pr[1] > 0 else BEDAVA_ADET)
                it['maxAmount'] = n if n >= 1 else -1
        if category == 'ammunition':
            for it in t['itemList']:
                pr = self.buy_price(it['lootId'])
                if pr and pr[1] > 0:
                    n = int(self.p.d['pilot'].get(pr[0], 0) // pr[1])
                    it['maxAmount'] = min(n, 2 ** 31 - 1) if n >= 1 else -1
                elif pr:
                    it['maxAmount'] = BEDAVA_ADET              # bedava: kayıttaki adet (kaydedilen hesabın parasının yettiği) değil
        for it in t['itemList']:
            if it.get('amountsSelectable') and it.get('price') and it['price'][0] == 0:
                it['price'] = [BEDAVA_FIYAT] + it['price'][1:]
        if self.featured and self.featured[0] == category and time.time() < self.featured[2]:
            # ödeme düğmesinden açılan mağaza (odeme.py): istemci mağazayı 'extras,resource_key_access-dse' ile açıp o ürünü, listede
            # yoksa ilk ürünü seçiyor (ExpeditionBuyTicketCommandHandler, CreateItem): bilet bu listede yok (canlı tur 2)
            t['itemList'] = [it for it in t['itemList'] if it['lootId'] != 'resource_key_access-dse']
            t['itemList'].sort(key=lambda it: it['lootId'] != self.featured[1])
        if len(t['itemList']) > SHOP_MAX:
            # liste sayacı bir bayt (istemcinin okuması): fazlası kodlanamaz, sekme hiç açılmazdı; sondakiler (ek ürünler) gösterilmez.
            # Etkinlik satırları (ek_magaza takvim) kesilmez: sekme doluyken etkinliğin anahtar ve paketleri kaybolmasın
            self.log('   mağaza: %s sekmesinde %d ürün, ilk %d gösteriliyor' % (category, len(t['itemList']), SHOP_MAX))
            evt = lambda it: bool((self.extra_entry.get(it['lootId']) or {}).get('takvim'))
            rest = {id(it) for it in [it for it in t['itemList'] if not evt(it)][:max(0, SHOP_MAX - sum(map(evt, t['itemList'])))]}
            t['itemList'] = [it for it in t['itemList'] if evt(it) or id(it) in rest][:SHOP_MAX]
        return ('ShopItemListCommand', t)

    def feature(self, category, loot, sec=15.0):
        """Bu kategorinin sonraki listelerinde (sec saniye) bu ürün başta."""
        self.featured = (category, loot, time.time() + sec) if loot else None

    def fuel_room(self):
        """P.E.T.'in yakıt deposunun boş yeri (P.E.T. yoksa 0)."""
        return max(0, PETM.PET['azami_yakit'] - int(self.pet.d['yakit'])) if self.pet.owned else 0

    def neden(self, key):
        """NEDENLER'den istemcinin dilinde ham metin (Türkçe istemciye Türkçe, ötekilere İngilizce)."""
        en, tr = NEDENLER[key]
        return raw_msg(tr if self.dil == 'tr' else en)

    def money_msgs(self):
        pl = self.p.d['pilot']
        return [legacy('0|A|C|%d|%d' % (pl.get('credits', 0), pl.get('uridium', 0))),
                self.inv_item(self.item_id('currency_uridium'), 'currency_uridium', pl.get('uridium', 0)),
                self.inv_item(self.item_id('currency_credits'), 'currency_credits', pl.get('credits', 0))]

    def quick_buy_status(self, menu_id):
        """Kısayol çubuğundaki hızlı alım öğesi: paranın yetip yetmediğine göre etkin/pasif (kayıt: ttip_currency_missing satırı)."""
        base = self.p.menu_status_cache.get(menu_id)
        pr = self.buy_price(menu_id[4:])
        if base is None or not pr:
            return None
        st = copy(base)
        ok = self.p.d['pilot'].get(pr[0], 0) >= math.ceil(pr[1] * max(st.get('counterValue', 1), 1) - 1e-9)
        st['activatable'] = ok
        for tip in ('toolTipSlotBar', 'toolTipItemBar'):
            lines = (st.get(tip) or {}).get('commandList')
            if lines is None:
                continue
            lines[:] = [l for l in lines if l.get('baseKey') != 'ttip_currency_missing']
            if not ok:
                lines.append(copy(keyed('ttip_currency_missing', CURRENCY='ttip_' + pr[0])['commandList'][0]))
        return st

    def quick_buy_msgs(self, currency=None):
        """Para değişince hızlı alım öğelerinin güncel durumu (kayıtta her alım ve ödülden sonra gönderilir)."""
        out = []
        for mid in sorted(self.p.menu_status_cache):
            if mid.startswith('buy_'):
                pr = self.price(mid[4:])
                if pr and (currency is None or pr[0] == currency):
                    st = self.quick_buy_status(mid)
                    if st:
                        out.append(('MenuItemStatusCommand', st))
        return out

    def buy_cmd(self, loot, category, buy_category, result, amount=0, error=None, equip_ids=(), free=0, success=None):
        sub = self.p.d.get('booster_abonelik', {}).get(loot)
        return ('ShopItemBuyCommand', dict(
            canEquipItemId=[float(i) for i in equip_ids], slotSet='', hintEquipTo='hint_equip_to_ship' if equip_ids else '',
            canBeSubscribedTo=BOOSTER.is_booster(loot), userHasBoosterPackage=False, buyCategory=buy_category, resultId=result,
            configId=self.p.aktif_konfig if equip_ids else 0, errorMessage=error, lootId=loot, category=category,
            hangarId=self.hangar_id if equip_ids else 0, realBuyAmount=amount, isSubscriptionRunning=bool(sub),
            allowAutoEquip=1 if equip_ids else 0, sucessMessage=success, emptySlotCount=free, droneId=0,
            isSubscriptionPaused=bool(sub and sub.get('durum') == 'duraklatildi'),
            secondsLeft=int(BOOSTER.left(self.p, loot)) if sub else 0, action='toggleSubscription' if sub else ''))

    def toggle_subscription(self, loot, category='', buy_category=''):
        """Booster aboneliği (resmî forum 127558 Hangar-Güçlendirici: "ABONE OL" / "ABONELİĞİ BİTİR"; istemcinin düğmesi
        ShopItemBuyRequest action 'toggleSubscription'): abone olunca bir kez alınır; süre bitmeden uridyum yetiyorsa yeniden alınır,
        yetmiyorsa abonelik para olana dek durur (subscription_tick)."""
        if not BOOSTER.is_booster(loot):
            return [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        subs = self.p.d.setdefault('booster_abonelik', {})
        if loot in subs:
            with self.p.lock:
                del subs[loot]
                self.p.dirty = True
            self.log('   booster aboneliği bitti: %s' % loot)
            return [self.buy_cmd(loot, category, buy_category, 1, success=self.neden('abone_bitti'))]
        msgs = self.buy(loot, 1, category, buy_category)
        if not BOOSTER.left(self.p, loot):
            return msgs                                  # alınamadı (para yok): abonelik başlamaz
        with self.p.lock:
            subs[loot] = {'durum': 'aktif'}
            self.p.dirty = True
        self.log('   booster aboneliği: %s' % loot)
        return msgs + [self.buy_cmd(loot, category, buy_category, 1, success=self.neden('abone_oldu'))]

    def subscription_tick(self, now):
        """Aboneliği süren boosterlar: kalan 60 sn'nin altına inince uridyum yetiyorsa yeniden alınır, yetmiyorsa duraklar."""
        msgs = []
        for loot, sub in list(self.p.d.get('booster_abonelik', {}).items()):
            if BOOSTER.left(self.p, loot, now) > 60:
                continue
            pr = self.buy_price(loot)
            ok = pr and (self.p.d['pilot'].get('uridium', 0) if pr[0] == 'uridium' else self.p.d['pilot'].get('credits', 0)) >= pr[1]
            state = 'aktif' if ok else 'duraklatildi'
            if ok:
                msgs += [m for m in self.buy(loot, 1) if m[0] != 'ShopItemBuyCommand']
            if sub.get('durum') != state:
                with self.p.lock:
                    sub['durum'] = state
                    self.p.dirty = True
                if not ok:
                    self.log('   booster aboneliği durdu (para yok): %s' % loot)
        return msgs

    def free_slots(self, slot, cid=None):
        return max(0, self.capacity(slot) - len(self.p.config(cid).get(slot, [])))

    def fits(self, slot, iid, loot, pending=()):
        """Yeni gelen eşya etkin config'e kendiliğinden takılabilir (ya da takılması önerilebilir) mi: move()'un kuralları (modülün
        gemisi ve türü, yuva CPU'su, onarım robotu); QFC ve parçacık eşyalarını oyuncu takar. pending: aynı alımda takılması önerilen
        öteki eşyalar. Kullanıcı bildirimi 2026-10-25: ödül modülü etkin geminin olmasa da takılıyordu."""
        cur = list(self.p.config().get(slot, [])) + [i for i in pending if slot_of(self.p.d['esyalar'].get(str(i), '')) == slot]
        loots = [self.p.d['esyalar'].get(str(i), '') for i in cur]
        if slot == 'upgrades':
            return GM.equip_allowed(self.p, iid, self.p.ship()['lootId']) and not GM.type_taken(self.p, iid, cur)
        if slot == 'QuantumFluidCore' or slot in PC.SLOTS:
            return False
        if slot == 'extra':
            on_drones = [self.p.d['esyalar'].get(str(i), '') for ids in self.p.drone_config().values() for i in ids]   # dronlardaki de config'in
            return not (EK.slot_bonus_of([loot]) and EK.slot_bonus_of(loots)) and loot not in on_drones and \
                not (loot.startswith(REPBOT) and any(l.startswith(REPBOT) for l in loots + on_drones))
        return True

    @staticmethod
    def contents(loot, amount):
        """Satın alınınca verilecekler [(lootId, adet)]: cephane, ekipman ve gemi kendisi, paketler esyalar.json odeme_paketleri'nden.
        None: sunucu bu eşyayı henüz veremiyor (tasarım, anahtar …). Gemi her zaman 1 adet."""
        if loot in NO_EFFECT:
            return None
        pk = ESYA['odeme_paketleri'].get(loot)
        if pk:
            if any(l.startswith('ship_') and not design_base(l) and l not in ESYA['gemiler'] for l, n in pk):
                return None          # sunucuda olmayan gemi (Paladin, Basilisk …; Aşama 6): paket gösterilmez
            return [(l, 1 if l.startswith('ship_') else n * amount) for l, n in pk]
        if loot.startswith('ship_') and (loot in ESYA['gemiler'] or design_base(loot)):
            return [(loot, 1)]
        if loot in DRONES or loot in FORMS or loot == PET_LOOT or loot == PETM.HULL:
            return [(loot, 1)]
        if loot in PETM.DESIGNS:                     # P.E.T. tasarımı: envantere, P.E.T.'in görünüm yuvasına takılır
            return [(loot, amount)]
        if BOOSTER.is_booster(loot):
            return [(loot, amount)]
        if loot == 'resource_logfile' or loot in GN.KEYS or loot in ASSEMBLY_PARTS:   # log diski; ganimet anahtarları; Assembly malzemesi
            return [(loot, amount)]
        if loot == 'resource_key_access-dse':        # DSE Travel Permit: Deep Space Echoes'un bileti (echoes.py)
            return [(loot, amount)]
        if loot == PET_FUEL:                         # P.E.T.'in deposuna (_reward)
            return [(loot, amount)]
        if loot in PASS_ITEMS or loot in EVENT_ITEMS:                                # Gold Pass, Battle Pass, puan, Monthly Deluxe; etkinlik paraları
            return [(loot, amount)]
        if loot.startswith(('captain_', 'resource_collectable_energy-')) or loot in NEW_RESOURCES or loot in RZ.SOURCES:  # + Ö6 rezonatör kaynakları
            return [(loot, amount)]
        if loot.startswith('ammunition_') or slot_of(loot) or loot in DESIGNS or PETM.slot_for(loot) in ('gears', 'protocols'):
            return [(loot, amount)]
        if loot in TK.ITEMS:                         # teknoloji eşyası (Explosive Charging Blob: ek mağaza)
            return [(loot, amount)]
        return None

    def buy(self, loot, amount, category='', buy_category='', quick=False, pet_name='', level=1):
        amount = max(1, int(amount or 1))
        try:                                        # 3X düğmesi seviyeyi "3X" gönderir (levelGrades): 4. kademe
            level = 4 if str(level).upper() == '3X' else max(1, int(level))
        except (TypeError, ValueError):
            level = 1
        if not PETM.has_levels(loot):
            level = 1
        elif level > len(PETM.level_prices(loot)) or not PETM.level_prices(loot)[level - 1]:
            # mağazada olmayan kademe: dişlilerin 3X'i, protokollerin AI-ECO dışındaki 4. seviyesi (kayıt; istemci metni "You can't
            # purchase this P.E.T. Gear level from the shop")
            self.log('   satın alma yok: %s seviye %d (mağazada satılmaz)' % (loot, level))
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('pet_gear_shop_level_limit'))]
        elif level > 1 and (not self.pet.owned or self.pet.d['seviye'] < PETM.level_need(level)):
            # wiki: 2. seviye dişli/protokol için P.E.T. seviyesi 4, 3. seviye için 8, 4. seviye 20 (istemci: pet_gear_shop_level_limit)
            self.log('   satın alma yok: %s seviye %d (P.E.T. seviyesi %d gerekir)' % (loot, level, PETM.level_need(level)))
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('pet_gear_shop_level_limit'))]
        if self.package_done(loot) and loot in self.p.d.get('benzersiz_paketler', []):     # benzersiz paket bir kez (panel: paket_siniri;
            # içeriği zaten varsa aşağıdaki kurallar oyunun kendi hatasını verir: items_shop_error_ship_contains_ship …)
            self.log('   satın alma yok: %s (benzersiz paket alınmış)' % loot)
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        if not self.gate_ok(loot):                  # Ö7: etkinlik dışı, alınmış (bir kez) ya da seviye dışı paket
            self.log('   satın alma yok: %s (şimdi satılmıyor)' % loot)
            return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg('shop_item_not_found'))]
        if (self.extra_entry.get(loot) or {}).get('bir_kez'):
            amount = 1
        elif (self.extra_entry.get(loot) or {}).get('en_cok'):
            amount = min(amount, self.extra_entry[loot]['en_cok'])
        if loot == PET_FUEL:                        # deponun boş yeri kadar (fazlasının parası alınmaz)
            if self.fuel_room() <= 0:
                self.log('   satın alma yok: P.E.T. yakıt deposu dolu ya da P.E.T. yok')
                return [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=self.neden('yakit_dolu'))]
            amount = min(amount, self.fuel_room())
        pr = self.buy_price(loot, level)
        grants = self.contents(loot, amount)
        is_ammo = loot.startswith('ammunition_')
        fail = lambda key: [] if quick else [self.buy_cmd(loot, category, buy_category, 0, error=stack_msg(key))]
        if not pr or not grants:
            self.log('   satın alma yok: %s (%s)' % (loot, 'mağazada değil' if not pr else 'içeriği sunucuda henüz yok'))
            return fail('shop_item_not_found')
        owned = {s['lootId'] for s in self.p.d['gemiler'].values()}
        pkg = loot.startswith(('package_', 'deal_'))
        skipped = []
        if pkg:      # paket (S-OS-01 = Yamato + Defcom, Stellar): sahip olunan gemi, P.E.T., formasyon ve dron yeri atlanır, gerisi verilir
            grants, skipped = self.package_fit(grants, owned)
            if not grants:
                self.log('   satın alma yok: %s (içeriğinin hepsi zaten var)' % loot)
                return fail(skipped[0][2])
        if any(g in owned for g, n in grants if g.startswith('ship_') and not design_base(g)):
            self.log('   satın alma yok: %s (bu gemi zaten var)' % loot)
            return fail('items_shop_error_ship_contains_ship')        # oyunun kuralı: her gemi türünden bir tane
        for g, n in ([] if pkg else grants):
            base = design_base(g)
            if base and base not in owned:
                self.log('   satın alma yok: %s (%s yok)' % (g, base))
                return fail('dse_ship_not_exist')                      # tasarım ancak o gemiye sahipken alınır
            if base and any(g in s.get('tasarimlar', []) for s in self.p.d['gemiler'].values()):
                self.log('   satın alma yok: %s (tasarım zaten var)' % g)
                return fail('items_design_already_in_use')
        for g, n in grants:
            if g in DRONES and not self.drone_room(g):
                self.log('   satın alma yok: %s (en çok %d dron)' % (g, ESYA['dron_azami']))
                return fail('drone_have_max')
            if g in FORMS and (g == 'drone_formation_default' or g in self.p.d['formasyonlar']):
                self.log('   satın alma yok: %s (formasyon zaten var)' % g)
                return fail('items_drone_formation_already_in_use')
            if g == PET_LOOT and self.pet.owned:
                self.log('   satın alma yok: P.E.T. zaten var')
                return fail('eqt_error_generic')
        if amount != 1 and any(g.startswith('ship_') or g in DRONES or g in FORMS or g in (PET_LOOT, PETM.HULL) for g, n in grants):
            amount = 1          # içerik de 1 adede göre (yoksa 1'in parasına amount kat kaynak veriliyordu)
            grants = self.contents(loot, 1)
            if pkg:
                grants, skipped = self.package_fit(grants, owned)
        cur, unit = pr
        cost = math.ceil(unit * amount - 1e-9)
        with self.p.lock:
            pl = self.p.d['pilot']
            if pl.get(cur, 0) < cost:
                self.log('   para yetmiyor: %s x%d = %d %s (elde %d)' % (loot, amount, cost, cur, pl.get(cur, 0)))
                return fail('not_enough_' + cur)
            pl[cur] -= cost
            self.p.dirty = True
        RT.money(self.p, cur, -cost, RT.buy_desc(loot), loot, amount)           # hesap geçmişi
        msgs = self.quick_buy_msgs(cur) + self.money_msgs()
        equip_ids, free = [], 0
        for g, n in grants:
            if design_base(g):
                sid = self.own_ship(design_base(g))
                if sid is None:                           # paketteki tasarım, gemi yok: depoda bekler (pending_designs)
                    if not self.p.resource(g):
                        self.p.add_resource(g, 1)
                    self.log('   tasarım saklandı: %s (%s yok)' % (g, design_base(g)))
                    continue
                if g in self.p.ship(sid).get('tasarimlar', []):
                    continue
                with self.p.lock:
                    self.p.ship(sid).setdefault('tasarimlar', []).append(g)
                    self.p.dirty = True
                msgs += [('ShipDesignAddedCommand', {'lootId': g}), legacy('0|LM|ST|LOT|%s|1' % g)]
                self.log('   yeni tasarım: %s (%s)' % (g, design_base(g)))
            elif g.startswith(('resource_', 'currency_', 'tech_', 'pet_designs_', 'captain_')) or (pkg and BOOSTER.is_booster(g)):
                msgs += self.reward(g, n)                  # paket içeriği: kaynak deposu, para, teknoloji, saatlik booster
            elif g.startswith('ship_'):
                sid = self.p.add_ship(g)
                msgs.append(legacy('0|LM|ST|LOT|%s|1' % g))
                msgs += self.pending_designs(g)            # gemi yokken gelen tasarımlar (Assembly, kutu, paket)
                msgs += self.ship_count_msgs([g])          # Plus tarifinin taban gemisi (Assembly sayacı)
                self.log('   yeni gemi: %s (shipId %d, hangarId %d)' % (g, sid, self.p.ship(sid)['hangarId']))
            elif g in DRONES:                              # paketteki dronlar (Stellar: 8 Iris) hepsi, yer kadar (package_fit)
                for _ in range(n):
                    did = self.p.add_drone(g)
                    msgs.append(self.drone_item(self.p.drone(did)))      # Assembly'de yükseltilebilir
                msgs += [legacy('0|LM|ST|LOT|%s|%d' % (g, n))] + self.drone_msgs() + self.formation_status_msgs()
                self.p.ach('formation', dron=len(self.p.d['dronlar']))
                self.log('   yeni dron: %s x%d (kimlik %d, toplam %d)' % (g, n, did, len(self.p.d['dronlar'])))
            elif g in FORMS:
                with self.p.lock:
                    self.p.d['formasyonlar'].append(g)
                    self.p.dirty = True
                st = self.p.menu_status(g)
                msgs += ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|1' % g)]
                self.log('   yeni formasyon: %s' % g)
            elif g.startswith('ammunition_'):
                before = self.p.ammo(g)
                total = self.p.add_ammo(g, n)
                iid = self.item_id(g)
                st = self.p.menu_status(g)
                if st:
                    msgs.append(('MenuItemStatusCommand', st))
                if before == 0:
                    msgs.append(('RefreshSelectedUICategoryCommand', {}))
                kind = loot_kind(g)
                msgs += [self.inv_item(iid, g, total), self.pack([self.hangar_item(iid, g, total)]),
                         legacy('0|LM|ST|%s|%s|%d' % (kind, g, n))]
            elif g == PETM.HULL:
                msgs += self.pet.upgrade_hull()            # +10.000 azami can (wiki), uzaydaysa gösterge
            elif g == PET_LOOT:
                msgs += self.grant_pet(pet_name)
            elif g == 'resource_logfile':
                msgs += self.reward(g, n)                  # pilot yetenek ağacının log diski (kapı üreticisinin sayacı)
            elif BOOSTER.is_booster(g):
                BOOSTER.add(self.p, g, n)                  # her biri 10 saat; aynı booster süresine eklenir
                msgs += [BOOSTER.update_cmd(self.p), legacy('0|LM|ST|LOT|%s|%d' % (g, n))] + self.apply_stats()
                self.log('   booster: %s x%d (kalan %d sn)' % (g, n, BOOSTER.left(self.p, g)))
            elif not slot_of(g):
                for _ in range(n):            # dron tasarımı, P.E.T. dişlisi/protokolü: envantere (hangarda takılır)
                    iid = self.p.new_item(g, level)
                    msgs += [self.inv_item(iid, g, 1), self.pack([self.hangar_item(iid, g, 1)])]
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (g, n)))
                if level > 1:
                    self.log('   seviye %d: %s' % (level, g))
            else:
                room = self.free_slots(slot_of(g))
                free += room
                got = 0
                for _ in range(n):
                    iid = self.p.new_item(g)
                    msgs += [self.inv_item(iid, g, 1), self.pack([self.hangar_item(iid, g, 1)])]
                    if got < room and self.fits(slot_of(g), iid, g, equip_ids):
                        equip_ids.append(iid)
                        got += 1
                EK.recharge(self.p, g, n)                  # atlama/gizlenme CPU'su: yeni hak
                if g == 'equipment_extra_hmd-07':
                    msgs += self.p.menu_changes([g])      # HM-7: takılmasa da kısayol çubuğunda hemen görünür
                msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (g, n)))
        self.log('   satın alındı: %s x%d = %d %s (kalan %d)' % (loot, amount, cost, cur, self.p.d['pilot'][cur]))
        if skipped:
            self.log('   paketten verilmedi (zaten var): %s' % ', '.join('%s x%d' % (g, n) for g, n, key in skipped))
            msgs.append(self.skipped_msg(skipped))
        if pkg and any(self.unique_loot(g) for g, n in self.contents(loot, 1) or []):
            with self.p.lock:
                self.p.d.setdefault('benzersiz_paketler', []).append(loot)      # bir kez alınır (package_done)
                self.p.dirty = True
        for cb in self.on_bought:                      # Ö7 dükkânları (dukkanlar.py)
            msgs += cb(loot, amount) or []
        for g, n in grants:                            # ipucu (bir kez): ikinci gemi -> gemi ışınlama, ilk ekipman -> hangarda tak
            msgs += self.p.hint(IP.for_purchase(self.p, g, bool(slot_of(g)) and not g.startswith('ammunition_')))
        if not quick:
            buy = self.buy_cmd(loot, category, buy_category, 1, amount, equip_ids=equip_ids, free=free)
            lst = self.shop_list(category)
            # istemci liste gelince (ShopItemListCommandHandler -> CreateItem -> OnClickItem) satın alma penceresini gizliyor:
            # "Geminde boş slotlar var, donatılsın mı?" sorusu görünür görünmez kayboluyordu (canlı test 2026-10-18). Soru
            # varsa liste önce gider, soru sonra; yoksa kayıttaki sıra (ShopItemBuyCommand, sonra liste).
            msgs += ([lst, buy] if equip_ids else [buy, lst]) if lst else [buy]
        return msgs

    def grant_pet(self, name=''):
        """P.E.T. (mağaza, paket, Assembly, kutu): yoksa verilir; çubukta simgesi, pencerenin düğmeleri."""
        if self.pet.owned:
            return []
        with self.p.lock:
            self.p.d['pet'] = PETM.new_pet(self.p)
            if len((name or '').strip()) >= 3:              # mağazadaki "P.E.T. name" alanı
                self.p.d['pet']['ad'] = name.strip()[:20]
            self.p.dirty = True
        self.log('   yeni P.E.T.: %s' % PET_LOOT)
        return [('PetPurchasedCommand', {}), self.pet.init_msg(), self.p.generate('@arayuz'),    # çubukta P.E.T. simgesi
                legacy('0|LM|ST|LOT|%s|1' % PET_LOOT)]

    def prize(self, loot, n, kaynak='mod'):
        """Görev, kapı, mod, etkinlik ve Dispatch ödülü: reward()'ın panelli yolu. Kredi, uridyum, EP ve onur kendi çarpanlarıyla;
        yığılan eşyalar (cephane, kaynak, anahtar, teknoloji eşyası) 'mod_odul' çarpanıyla; tek eşyalar (gemi, lazer, tasarım,
        booster, P.E.T., bilet) aynen. kaynak: panelin alt ayarı (gorev, kapi, mod). Mağaza, paket, takas ve GM yolları reward()'ı
        kullanır (ölçeklenmez)."""
        key = PRIZE_CURRENCY.get(loot)
        if key:
            n = AY.miktar(key, n, kaynak)
        elif loot.startswith(('ammunition_', 'resource_', 'tech_')) and loot not in PASS_ITEMS:
            n = AY.miktar('mod_odul', n, kaynak)
        return self.reward(loot, n) if n > 0 else []

    def reward(self, loot, n, level=1):
        msgs = self._reward(loot, n, level)
        if loot in (GM.SHARD, GM.CHIP) or PC.restabilizable(loot):
            # Restabilize sekmesi bedel sayaçlarını ve listeyi bu komuttan alıyor (kayıtta envanter değişince yeniden geliyor);
            # OptiGrad Chip / Unstable Shard gelince sekme 0 gösterip düğmeyi kapalı tutuyordu (canlı test H70)
            msgs = list(msgs or []) + [GM.list_cmd(self.p)]
        return msgs

    def _reward(self, loot, n, level=1):
        """Görev ödülü (kredi/uridyum/EP/onur dışındakiler): cephane, ekipman (boş yuva varsa etkin gemiye takılır; kayıttaki
        gibi; "Auto-equip new items" kapalıysa takılmaz), gemi, gemi tasarımı, cevher, booster, kapı enerjisi, log diski. Sunucuda karşılığı olmayan ödül (Assembly kaynağı, kupon …)
        profilde saklanır (diger_esyalar). level: seviyeli P.E.T. dişlisi/protokolünün seviyesi (Assembly tarifleri)."""
        msgs = []
        RT.note(self.p, 'received_item', loot, n)                              # seyir defteri
        if loot == PET_LOOT:                       # ödül yolundan P.E.T. depoya düşüp kayboluyordu (canlı test H43)
            return self.grant_pet()
        got = SZ.reserve(loot, n)
        if got is not None:                        # Season Pass rezervi: içeriği (sezon.py; önceden görünmez depoya düşüyordu)
            for l, k in got:
                msgs += self.reward(l, k)
            self.log('   rezerv açıldı: %s x%d -> %s' % (loot, n, ', '.join('%s x%d' % x for x in got)))
            return msgs
        if loot in PASS_ITEMS and self.biletler:                               # Season Pass puanı, Gold/Extra Gold, Battle Pass, Deluxe
            sz, bp, go = self.biletler
            if loot == 'resource_battle-pass':
                return bp.grant_pass(n)
            if loot == 'resource_monthly-deluxe':
                return go.grant_deluxe(n)
            return sz.grant(loot, n)
        if self.yeni and (loot.startswith(('captain_', QF.PREFIX)) or PC.is_item(loot)):     # N.O.V.A., QFC, top/sürücü (yeni_sistemler.py)
            got = self.yeni.reward(loot, n)
            if got is not None:
                return got
        if loot in PAY_CURRENCY:                    # paketteki para / EP (hesap geçmişine ve Uridium Bank'a sayılmaz)
            field, kind = PAY_CURRENCY[loot]
            with self.p.lock:
                pl = self.p.d['pilot']
                pl[field] = pl.get(field, 0) + n
                self.p.dirty = True
            if loot == 'currency_experience':
                tot = self.p.gain()                         # seviye EP'ye göre yeniden hesaplanır
                msgs.append(legacy('0|LM|ST|EP|%d|%d|%d' % (n, tot['ep'], tot['seviye'])))
            else:
                msgs += self.money_msgs() + [legacy('0|LM|ST|%s|%d|%d' % (kind, n, self.p.d['pilot'][field]))]
            return msgs
        if loot in ESYA['magaza_indirimi']['gun']:  # Shop Discount (günlük giriş): indirimin süresi eklenir (gösterge sonraki girişte)
            with self.p.lock:
                d = self.p.d
                d['magaza_indirimi'] = max(d.get('magaza_indirimi', 0), time.time()) + ESYA['magaza_indirimi']['gun'][loot] * 86400 * n
                self.p.dirty = True
            return msgs + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]
        if loot.startswith('tech_'):                # teknoloji eşyası (Assembly ve paketler): sayaca
            TK.add(self.p, loot, n)
            st = self.p.menu_status(loot)
            return msgs + ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))]
        if loot.startswith('ammunition_'):
            total = self.p.add_ammo(loot, n)
            iid = self.item_id(loot)
            st = self.p.menu_status(loot)
            if st:
                msgs.append(('MenuItemStatusCommand', st))
            kind = loot_kind(loot)
            msgs += [self.inv_item(iid, loot, total), self.pack([self.hangar_item(iid, loot, total)]), legacy('0|LM|ST|%s|%s|%d' % (kind, loot, n))]
        elif slot_of(loot):
            slot, equipped = slot_of(loot), False
            auto = self.p.d.get('otomatik_kusan', True)     # Ayarlar > Gameplay "Auto-equip new items" (kapalıysa envanterde kalır)
            for _ in range(n):
                iid = self.p.new_item(loot)
                msgs += [self.inv_item(iid, loot, 1), self.pack([self.hangar_item(iid, loot, 1)])]
                if auto and self.free_slots(slot) > 0 and not pet_only(loot) and self.fits(slot, iid, loot):
                    with self.p.lock:
                        self.p.config().setdefault(slot, []).append(iid)
                        self.p.sync_ekipman()
                        self.p.dirty = True
                    msgs.append(self.inv_item(iid, loot, 1, self.hangar_id))
                    equipped = True
            if equipped:
                msgs += [self.equipment_cmd()] + self.apply_stats()
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
            if GM.unstable(loot):                       # Restabilize listesi (canlı test H41: yalnız girişte geliyordu)
                msgs.append(GM.list_cmd(self.p))
        elif loot.startswith('ship_') and loot in ESYA['gemiler']:
            if loot not in {s['lootId'] for s in self.p.d['gemiler'].values()}:
                self.p.add_ship(loot)
                msgs.append(legacy('0|LM|ST|LOT|%s|1' % loot))
                msgs += self.pending_designs(loot) + self.ship_count_msgs([loot])
                if self.ships_tpl:
                    msgs.append(self.ships_cmd())              # hangar listesinde yeni gemi (Assembly, kapı, kutu)
        elif design_base(loot) and self.grant_design(loot):
            msgs += [('ShipDesignAddedCommand', {'lootId': loot}), legacy('0|LM|ST|LOT|%s|1' % loot)]
        elif loot in ORES.values():
            # ödül cevheri kargo dolu da olsa hepsi gelir, kargo azamiyi aşar (resmî Skylab SSS: "transferred to your ship regardless",
            # "temporarily greater cargo capacity"; 10.000 Seprom ödülü 9.000'lik kargoda). Yer açılana dek cevher/kutu toplanmaz.
            # Boş yer kadar veriliyordu: Assembly'nin 5.000 Seprom'u dolu kargoda kayboluyordu (kullanıcı bildirimi 2026-10-24)
            t = next(k for k, v in ORES.items() if v == loot)
            if n > 0:
                msgs += [('AttributeOreCountUpdateCommand', {'oreCountList': self.p.add_ores({t: n})}), self.ore_pack([t])]
        elif loose_item(loot):     # dron / P.E.T. tasarımı, P.E.T. dişlisi ve protokolü (kapı, kutu, Assembly, Pass): envantere, hangarda takılır
            for _ in range(n):
                iid = self.p.new_item(loot, level if PETM.level_prices(loot) else 1)
                msgs += [self.inv_item(iid, loot, 1), self.pack([self.hangar_item(iid, loot, 1)])]
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif BOOSTER.is_booster(loot):   # ödül boosterı: adet saat, süresi oyundayken işler (günlük giriş, görev)
            BOOSTER.add(self.p, loot, seconds=n * 3600)
            msgs += [BOOSTER.update_cmd(self.p), legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] + self.apply_stats()
        elif loot == 'resource_extra-energy' and self.kapilar:
            msgs += self.kapilar.bonus_energy(n)       # Galaksi Kapısı üreticisinin ücretsiz enerjisi
        elif loot in DRONES:                           # Assembly/Dispatch: dron (Flax/Iris en çok dron_azami, Apis/Zeus birer)
            for _ in range(n):
                if not self.drone_room(loot):
                    break
                msgs.append(self.drone_item(self.p.drone(self.p.add_drone(loot))))     # Assembly'de yükseltilebilir
            msgs += [legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] + self.drone_msgs() + self.formation_status_msgs()
        elif loot in FORMS:
            if loot not in self.p.d['formasyonlar']:
                with self.p.lock:
                    self.p.d['formasyonlar'].append(loot)
                    self.p.dirty = True
            st = self.p.menu_status(loot)
            msgs += ([('MenuItemStatusCommand', st)] if st else []) + [legacy('0|LM|ST|LOT|%s|1' % loot)]
        elif loot == 'resource_repairvoucher' and self.kapilar:
            with self.p.lock:                          # onarım kuponu: ölüm ekranında (dunya.vouchers)
                self.kapilar.d['kupon'] += n
                self.p.dirty = True
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif loot == 'resource_pet-fuel' and self.pet and self.pet.owned:
            add = max(0, min(n, PETM.PET['azami_yakit'] - self.p.d['pet'].get('yakit', 0)))
            with self.p.lock:
                self.p.d['pet']['yakit'] = self.p.d['pet'].get('yakit', 0) + add
                self.p.dirty = True
            if add:
                msgs += [legacy('0|LM|ST|LOT|%s|%d' % (loot, add)), self.pet.fuel_msg()]     # P.E.T. penceresinin yakıt çubuğu
            if add < n:                                # depo doldu: istemci log_msg_not_gather_pet_fuel ("cargo is full")
                msgs.append(('PetFuelCargoFullMessage', {}))
        elif loot == 'resource_logfile' and self.kapilar:
            with self.p.lock:                          # log diski: pilot puanına çevrilir (yetenek.py)
                self.kapilar.d['log_disk'] += n
                self.p.dirty = True
            msgs.append(legacy('0|LM|ST|LOT|%s|%d' % (loot, n)))
        elif loot == 'resource_wordpuzzle-letter' and self.hitac:
            msgs += self.hitac.grant_letter(n)         # Hitac kutusundaki harf: Word Puzzle (hitac_piyango.py)
        elif loot == 'resource_collectable_chromin' and self.chromin:
            msgs += self.chromin.gain(n)               # Chromin Rush: 160.000 sınırı, fazlası krediye (chromin.py)
        else:                            # henüz harcayan sistem yok (Assembly kaynakları, kuponlar …): depoda (profil.add_resource)
            total = self.p.add_resource(loot, n)
            if loot.startswith('resource_'):
                msgs += self.resource_msgs(loot, total, n)
            if loot in GN.KEYS and GN.key_line(self.p, GN.KEYS[loot]):         # ganimet anahtarı: HUD sayacı
                msgs.append(legacy(GN.key_line(self.p, GN.KEYS[loot])))
            if hidden(loot):        # envanterde görünmez, hiçbir sistem okumaz: bu ödül kaybolur (test_odul_yollari yakalar)
                self.log('   UYARI: ödül tanınmıyor, envanterde görünmeyecek: %s x%d (depoda saklandı, toplam %d)' % (loot, n, total))
            else:
                self.log('   ödül depoda: %s x%d (toplam %d)' % (loot, n, total))
        return msgs

    def rescue_depot(self):
        """Ödül yolunda önceden tanınmadığı için görünmez depoya düşmüş eşyaları yerine taşır (2026-10-22: Season Pass'in Hyperion dron
        tasarımı ve rezervleri, Assembly'nin P.E.T. protokolleri): tasarım, dişli ve protokol envantere; rezervler açılır (aynı
        içerik birleşir, seyir defteri dolmasın). Hâlâ tanınmayanlar depoda kalır, günlükte uyarılır. Oturum her bağlantıda bir kez,
        giriş mesajlarından önce çağırır -> taşınan [(lootId, adet)]."""
        moved, opened = [], {}
        # gemisi sonradan alınan tasarımlar: mağazadan alınan gemi bekleyenleri vermiyordu (kullanıcı bildirimi 2026-10-24: Assembly'nin
        # Spectrum Legend'ı Spectrum alınınca da yoktu)
        for base in sorted({s['lootId'] for s in self.p.d['gemiler'].values()}):
            moved += [(f['lootId'], 1) for n_, f in self.pending_designs(base)]
        for loot, n in sorted(self.p.d.get('diger_esyalar', {}).items()):
            n = int(n)
            if n <= 0 or not hidden(loot):
                continue
            if loose_item(loot):
                for _ in range(n):
                    self.p.new_item(loot)
            elif loot in SZ.RESERVES:
                for l, k in SZ.reserve(loot, n):
                    opened[l] = opened.get(l, 0) + k
            else:
                self.log('   UYARI: depoda envanterde görünmeyen eşya: %s x%d' % (loot, n))
                continue
            self.p.add_resource(loot, -n)
            moved.append((loot, n))
        for l, k in sorted(opened.items()):
            self.reward(l, k)
        if moved:
            self.log('   depodan kurtarıldı: %s%s' % (', '.join('%s x%d' % x for x in moved),
                                                    ' -> %s' % ', '.join('%s x%d' % x for x in sorted(opened.items())) if opened else ''))
        return moved

    def resource_msgs(self, loot, total, n):
        """Depodaki kaynağın sayacı (InventoryItemUpdatedCommand: Assembly malzeme sayaçları buradan; canlı test H31) ve günlük satırı
        (n > 0 ise "… alındı")."""
        iid = self.item_id(loot)
        items = [] if loot in NO_TRAITS else [self.inv_item(iid, loot, total), self.pack([self.hangar_item(iid, loot, total)])]
        return items + ([legacy('0|LM|ST|LOT|%s|%d' % (loot, n))] if n > 0 else [])

    # ------------------------------------------------------------ satış
    def sale_value(self, loot, n=1):
        """Satış -> (para alanı, tutar) ya da None. İstemcinin kendi değeri (eşyanın "sellable" özelliği, hangarın eşya bilgisinde
        kredi olarak gösterilen; data/istemci_esyalari.json); yoksa fiyatın satis_orani'si (uyarlama), mağazada fiyatı olmayanda
        ref_value. Alış fiyatından pahalıya (ya da aynına) satılmaz: o zaman fiyatın satis_orani'si (SL-01 3.000 U'ya alınıp istemcinin
        değeri 1.250.000 C'ye satılıyordu)."""
        v = YK.ITEMS.get(loot, {}).get('satis')
        if v:
            pr = self.price(loot)
            cost = pr[1] * (KUR if pr[0] == 'uridium' else 1) if pr else 0
            if cost and v >= cost:
                v = cost * ESYA['satis_orani']
            return 'credits', int(v * n)
        fixed = ESYA.get('satis_gemi', {}).get(loot)
        if fixed:
            return fixed[0], int(fixed[1] * n)
        pr = self.price(loot) or self.ref_value(loot)
        if not pr:
            return None
        return pr[0], int(pr[1] * n * ESYA['satis_orani'])

    def ref_value(self, loot):
        """Mağazada olmayan eşyanın değeri (esyalar.json _satis_degerleri): lazer/kalkan/hız aynı tablodaki en güçlü uridyumlu mağaza
        eşyasına gücüyle oranlanır; ötekiler önek tablosundan."""
        for table, key in STAT_TABLES:
            row = ESYA[table].get(loot)
            if row and row.get(key):
                priced = [(l, self.price(l)) for l, r in ESYA[table].items() if l != loot and r.get(key)]
                priced = [(l, pr) for l, pr in priced if pr and pr[0] == 'uridium']
                if priced:
                    ref, (cur, val) = max(priced, key=lambda x: ESYA[table][x[0]][key])
                    return cur, val * row[key] / ESYA[table][ref][key]
        return next((tuple(v) for k, v in ESYA['satis_degerleri'].items() if loot.startswith(k)), None)

    def sell(self, f):
        """HangarShipSellItemRequest {itemList: [{itemId, quantity}]}: envanterdeki takılı olmayan eşya ya da cephane. Hepsi
        satılabiliyorsa satılır (InventoryItemRemovedCommand / sayaç güncellemesi + para), yoksa hiçbiri."""
        fail = lambda neden=None: [('HangarShipSellItemCommand', dict(
            errorMessage=self.neden(neden) if neden else stack_msg('eqt_error_generic'), resultId=0))]
        equipped = self.p.equipped_ids()
        ammo_ids = {self.item_id(l): l for l in self.p.d['cephane']}
        plan = []
        for pk in f.get('itemList') or []:
            iid, q = int(pk.get('itemId') or 0), max(1, int(pk.get('quantity') or 1))
            if any(iid == x[0] for x in plan):          # aynı eşya iki kez: iki kez ödeniyordu
                return fail()
            loot = self.p.d['esyalar'].get(str(iid))
            if loot:
                if iid in equipped:
                    self.log('   satış yok: %s takılı' % loot)
                    return fail('takili_satis')
                if loot.startswith(QF.PREFIX):                  # QFC satılmaz, Hyperforge'da geri dönüşür (resmî SSS)
                    self.log('   satış yok: %s (QFC)' % loot)
                    return fail('qfc_satis')
                q = 1
            elif iid in ammo_ids:
                loot = ammo_ids[iid]
                q = min(q, self.p.ammo(loot))
            val = self.sale_value(loot, q) if loot and q > 0 else None
            if not val:
                self.log('   satış yok: eşya %s (%s)' % (iid, loot))
                return fail()
            plan.append((iid, loot, q, val))
        if not plan:
            return fail()
        msgs, got = [], {}
        for iid, loot, q, (cur, amount) in plan:
            if str(iid) in self.p.d['esyalar']:
                with self.p.lock:
                    del self.p.d['esyalar'][str(iid)]
                    self.p.d.get('esya_seviye', {}).pop(str(iid), None)
                    self.p.dirty = True
                msgs.append(('InventoryItemRemovedCommand', {'itemId': iid}))
            else:
                total = self.p.add_ammo(loot, -q)
                st = self.p.menu_status(loot)
                msgs += ([('MenuItemStatusCommand', st)] if st else []) + [self.inv_item(iid, loot, total),
                                                                          self.pack([self.hangar_item(iid, loot, total)])]
            got[cur] = got.get(cur, 0) + amount
            RT.money(self.p, cur, amount, RT.sell_desc(loot), loot, q)              # hesap geçmişi
            self.log('   satıldı: %s x%d = %d %s' % (loot, q, amount, cur))
        with self.p.lock:
            for cur, amount in got.items():
                self.p.d['pilot'][cur] = self.p.d['pilot'].get(cur, 0) + amount
            self.p.dirty = True
        return msgs + self.money_msgs() + [('HangarShipSellItemCommand', dict(errorMessage=None, resultId=1))]

    def sell_drone(self, f):
        """HangarShipSellDroneRequest {droneId}: dron satılır; üstündeki eşyalar ve tasarımı envantere döner. Değer: istemcinin
        "sellable" değeri (kredi; Flax 100.000, Iris 500.000), yoksa o türden son dronun fiyatının satis_orani'si."""
        x = self.p.drone(f.get('droneId') or 0)
        if not x or DRONES[x['lootId']].get('tek'):        # Apis/Zeus satılmaz (istemcide "sellable" yok)
            return [('HangarShipSellDroneCommand', dict(resultId=0, errorMessage=stack_msg('eqt_error_generic'), drones=self.drone_views()))]
        info = DRONES[x['lootId']]
        n = sum(1 for y in self.p.d['dronlar'] if y['lootId'] == x['lootId'])
        amount = int(info['fiyatlar'][min(n, len(info['fiyatlar'])) - 1] * ESYA['satis_orani'])
        cur = info['para']
        if YK.ITEMS.get(x['lootId'], {}).get('satis'):
            cur, amount = 'credits', int(YK.ITEMS[x['lootId']]['satis'])
        freed = []                    # her gemide dronun eşyaları ve tasarımları envantere
        with self.p.lock:
            for s in self.p.d['gemiler'].values():
                for c in s.get('dron_konfig', {}).values():
                    freed += c.pop(str(x['kimlik']), None) or []
                for c in s.get('dron_tasarim', {}).values():
                    freed += [i for i in (c.pop(str(x['kimlik']), None) or {}).values() if i]
            self.p.d['dronlar'].remove(x)
            self.p.d['pilot'][cur] = self.p.d['pilot'].get(cur, 0) + amount
            self.p.sync_ekipman()
            self.p.dirty = True
        RT.money(self.p, cur, amount, 'sell_drone', x['lootId'], 1)
        self.log('   dron satıldı: %s (kimlik %d) = %d %s' % (x['lootId'], x['kimlik'], amount, cur))
        # boşalan eşyalar istemcinin envanterinde de takılı değil (hangarId 0): önceden hangar listesi yeniden istenene dek takılı
        # sayılıp envanterde görünmüyordu
        form = self.formation_status_msgs()          # satılan dron etkin formasyonun asgari sayısının altına indirdiyse standarda döner
        return (self.money_msgs() + [('InventoryItemRemovedCommand', {'itemId': x['kimlik']}),          # Assembly listesinden
                                     ('HangarShipSellDroneCommand', dict(resultId=1, errorMessage=None, drones=self.drone_views()))]
                + form + self.drone_msgs() + [self.equipment_cmd()] + self.item_updates(freed) + self.apply_stats())

    @staticmethod
    def stack(key):
        return stack_msg(key)

    def grant_design(self, loot):
        """Gemi tasarımı ödülü: gemi profilde varsa tasarımlarına eklenir -> True; yoksa False (ödül saklanır)."""
        sid = self.own_ship(design_base(loot))
        if not sid:
            return False
        with self.p.lock:
            ds = self.p.ship(sid).setdefault('tasarimlar', [])
            if loot not in ds:
                ds.append(loot)
            self.p.dirty = True
        self.log('   tasarım ödülü: %s' % loot)
        return True

    def own_ship(self, base):
        """Bu türden sahip olunan gemi (shipId) ya da None. Astral'ın kiralık gemisi sayılmaz: koşu bitince geri alınır, tasarım
        onunla giderdi."""
        loan = (((self.p.d.get('pve') or {}).get('astral') or {}).get('kosu') or {}).get('sid')
        return next((k for k, s in self.p.d['gemiler'].items() if s['lootId'] == base and k != loan), None)

    def pending_designs(self, ship_loot):
        """Gemi alındı: saklanan tasarım ödülleri (gemi yokken gelenler) artık verilir."""
        msgs = []
        for loot in [l for l in self.p.d.get('diger_esyalar', {}) if design_base(l) == ship_loot]:
            if self.grant_design(loot):
                self.p.add_resource(loot, -self.p.resource(loot))
                msgs += [('ShipDesignAddedCommand', {'lootId': loot})]
        return msgs

    def auto_buy(self, loot, n):
        """Otomatik alım CPU'su (ALB-X, RB-X): mağaza fiyatıyla sessiz alım -> mesajlar (para yetmezse boş)."""
        return self.buy(loot, n, quick=True) if self.price(loot) else []

    def auto_buy_fail(self, loot, n):
        """Otomatik alım para yetmediği için olmadıysa istemcinin metni (Ö1): 0|ammobuy_fail_uri / _cre ("Ammo purchase failed! Not
        enough Uridium." …; NetConnectionHelper.OnData) -> mesajlar ya da boş."""
        pr = self.buy_price(loot, 1) if self.price(loot) else None
        if not pr or self.p.d['pilot'].get(pr[0], 0) >= math.ceil(pr[1] * n - 1e-9):
            return []
        return [legacy('0|ammobuy_fail_%s' % ('uri' if pr[0] == 'uridium' else 'cre'))]

    def auto_buy_ammo(self, f):
        """HangarShipAutoBuyCpuAmmoRequest: otomatik alım CPU'sunun (ALB-X lazer, RB-X roket ve fırlatıcı roketi) alacağı cephane
        (profilde) -> HangarShipAutoBuyCpuAmmoCommand (istemci envanterdeki eşyanın attachedAmmo'sunu günceller). RB-X'in listesinde
        fırlatıcı roketleri de var; ECO-10 seçilince hata veriyordu (kullanıcı bildirimi 2026-10-25)."""
        iid, ammo = f.get('itemId'), f.get('ammoLootId') or ''
        loot = self.p.d['esyalar'].get(str(iid))
        cfg = EK.X.get(loot, {}).get('oto_alim')
        ok = bool(cfg) and cfg['tur'] in ('lazer', 'roket') and ammo.startswith(
            ('ammunition_laser_',) if cfg['tur'] == 'lazer' else ('ammunition_rocket_', 'ammunition_rocketlauncher_')) \
            and bool(self.price(ammo))
        if ok:
            with self.p.lock:
                self.p.d.setdefault('oto_alim_cephane', {})[loot] = ammo
                self.p.dirty = True
            self.log('   otomatik alım: %s -> %s' % (loot, ammo))
        return [('HangarShipAutoBuyCpuAmmoCommand', dict(result=1 if ok else 0, cpuItemId=iid or 0, ammoLootId=ammo,
                                                          errorMessage=None if ok else stack_msg('eqt_error_generic')))]

    def auto_lab(self, item, ore, best=False):
        """Otomatik laboratuvar CPU'su (NC-AWL/AWR/AWB/AGB): yükseltme bitince kargodaki aynı (best: en iyi) cevherle yeniden."""
        opts = LAB['bonuslar'].get(str(item), {})
        if best:
            ore = max((int(t) for t in opts if self.p.ore_count(int(t)) > 0), key=lambda t: opts[str(t)], default=None)
        if ore is None or str(ore) not in opts or self.p.ore_count(ore) <= 0:
            return []
        n = min(self.p.ore_count(ore), 10000)
        self.log('   otomatik yükseltme: parça %d <- %s x%d' % (item, ORES.get(ore), n))
        return self.upgrade({'itemToUpdate': {'itemValue': item}, 'updateWith': {'oreType': {'typeValue': ore}, 'count': n}})

    def quick_buy(self, loot):
        st = self.p.menu_status_cache.get('buy_' + loot, {})
        return self.buy(loot, st.get('counterValue') or (100 if 'rocket' in loot else 1000), quick=True)

    # ------------------------------------------------------------ hangar
    def equipment_cmd(self, sid=None):
        ship = self.p.ship(sid)
        t = copy(self.equip_tpl)
        t.pop('_m', None)
        cur = ship['aktif_konfig']
        for c in t['shipConfigs']:
            pc = ship['konfigler'].get(str(c['setId']), {})
            for slot in EQUIP_SLOTS:
                c[slot] = list(pc.get(slot, []))
            c['active'] = c['setId'] == cur
        # lootId görünümle (tasarım ekli): istemci yuva düzenini gemi listesindeki adla tutup bununla arıyor (ships_cmd)
        t.update(currentConfigId=cur, lootId=self.p.ship_look(sid), hangarId=ship['hangarId'], shipId=int(sid or self.p.d['aktif_gemi']),
                 extrasSlotsSize1=self.capacity('extra', sid, 1), extrasSlotsSize2=self.capacity('extra', sid, 2),
                 droneConfigs=[self.drone_config_msg(c['setId'], c['setId'] == cur, sid) for c in t['shipConfigs']],
                 petConfigs=self.pet.config_msgs(cur, sid))
        return ('HangarShipEquipmentCommand', t)

    def drone_config_msg(self, cid, active, sid=None):
        """Bir geminin bir config'inde dronlar ve takılı eşyaları (HangarDroneEquipmentMsg; eşya kimlikleri
        SingleDroneEquipmentMsg.defaults, tasarım ve görünüm design/visual; tasarımlar geminin config'inde, dron_tasarim)."""
        dc = self.p.drone_config(cid, sid)
        drones = []
        team = self.p.design_mods(cid, sid).get('dron_lazer', 0)   # Havoc, Cerberus: bütün dronlar o tasarımdayken dron lazerine
        for i, x in enumerate(self.p.d['dronlar']):
            lv = LEVELS[x['seviye'] - 1]
            shd = DESIGNS.get(self.p.drone_design(x, 'design', cid, sid) or '', {}).get('dron_kalkan', 0)     # Hercules: o dronun kalkanına
            look, design = self.p.drone_design_id(x, 'visual', cid, sid), self.p.drone_design_id(x, 'design', cid, sid)
            # istemci (UINewHangarSystem.CreateItemInfo): "Effect: weaponEffect%/shieldEffect%"; ...Bouns > 0 olan değer mavi.
            # Seviye, tasarım ve Assembly yükseltmesinin etkisi savaştakiyle aynı (dunya: dron lazeri, magaza: dron kalkanı); 0/0
            # gidiyordu (canlı tur 2), yükseltme sayılmıyordu (kullanıcı bildirimi 2026-10-24: "yükseltilen dron bonus vermiyor").
            # "Upgrade lvl. Damage/Shield" istemcide olduğu gibi yazılıyor: Assembly'deki gibi seviye + 1
            up = YK.drone_level(x)
            weapon = ((1 + lv['lazer'] + team) * YK.factor(x['lootId'], up, YK.DRONE_DAMAGE) - 1) * 100
            shield = ((1 + lv['kalkan'] + shd) * YK.factor(x['lootId'], up, YK.DRONE_SHIELD) - 1) * 100
            drones.append(mod('SingleDroneEquipmentMsg', level=x['seviye'], visual=[look] if look else [],
                              shieldBouns=round(shield - lv['kalkan'] * 100, 2), repairValue='', defaults=list(dc.get(str(x['kimlik']), [])),
                              weaponBouns=round(weapon - lv['lazer'] * 100, 2), damageUpgradeLevel=up + 1, shieldUpgradeLevel=up + 1,
                              design=[design] if design else [], shieldEffect=round(shield, 2),
                              position=i, droneId=x['kimlik'], damage=0.0, repairType='', weaponEffect=round(weapon, 2)))
        return mod('HangarDroneEquipmentMsg', setId=int(cid), active=active, position=0, setDroneEquipment=drones)

    def drone_views(self):
        """Hangar listesindeki dronlar: sıra, seviye, puan ve bir sonraki seviyenin puanı."""
        out = []
        for i, x in enumerate(self.p.d['dronlar']):
            nxt = LEVELS[min(x['seviye'], len(LEVELS) - 1)]['puan']
            out.append(mod('HangarShipDroneView', position=i, damage=0.0, droneId=x['kimlik'], points=x['puan'], level=x['seviye'],
                           lootId=x['lootId'], nextLevel=nxt, droneTypeId=DRONES[x['lootId']]['tur']))
        return out

    def formation_status_msgs(self):
        """Dron sayısı değişince: asgari dron isteyen, sahip olunan formasyonların düğmeleri (Arrow, Dome, Heart, Pincer; wiki). Etkin
        formasyona dron artık yetmiyorsa (dron satıldı) standart formasyona dönülür."""
        out = []
        cur = next((k for k, v in FORMS.items() if v['id'] == self.p.d.get('formasyon', 0)), None)
        if FORM_RULES.get(cur, {}).get('asgari_dron', 0) > len(self.p.d['dronlar']):
            with self.p.lock:
                self.p.d['formasyon'] = 0
                self.p.dirty = True
            out += [('DroneFormationChangeCommand', {'uid': self.p.user_id, 'selectedFormationId': 0})]
            out += [('MenuItemStatusCommand', st) for st in [self.p.menu_status('drone_formation_default')] if st]
        for k in self.p.d['formasyonlar']:
            st = FORM_RULES.get(k, {}).get('asgari_dron') and self.p.menu_status(k)
            if st:
                out.append(('MenuItemStatusCommand', st))
        return out

    def drone_msgs(self):
        """Uzaydaki dronlar: "0|n|d|<kullanıcı>|<formasyon>|tür|seviye|tasarım|görünüm…" (kayıt: başka oyuncuların dronları;
        tasarım/görünüm istemcinin game.xml tasarım kimlikleri, 0 standart)."""
        ds = self.p.d['dronlar']
        if not ds:
            return []
        look = lambda x, slot: DESIGNS.get(self.p.drone_design(x, slot) or '', {}).get('id', 0)
        body = '|'.join('%d|%d|%d|%d' % (DRONES[x['lootId']]['tur'], x['seviye'], look(x, 'design'), look(x, 'visual')) for x in ds)
        return [legacy('0|n|d|%d|%d|%s' % (self.p.user_id, self.p.d.get('formasyon', 0), body))]

    def inventory_items(self):
        hm = self.p.hangar_map()
        items = [self.hangar_item(int(i), loot, 1, hm.get(int(i), 0)) for i, loot in self.p.d['esyalar'].items()]
        items += [self.hangar_item(self.item_id(loot), loot, n) for loot, n in self.p.d['cephane'].items() if n > 0]
        for m in self.p.d['madenler']:
            loot = ORES.get(m['oreType']['typeValue'])
            if loot and m['count'] > 0:
                items.append(self.hangar_item(self.item_id(loot), loot, m['count']))
        for loot, n in sorted(self.p.d.get('diger_esyalar', {}).items()):   # saklanan kaynaklar (ABR, Schism, anahtar, kupon …)
            if loot.startswith('resource_') and n > 0 and loot not in NO_TRAITS:
                items.append(self.hangar_item(self.item_id(loot), loot, n))
        return items

    def ships_cmd(self):
        """Hangar listesi: sahip olunan gemiler (etkin olan işaretli), her biri için tasarım listesi, ortak envanter. Gemi adı görünümle
        (ör. ship_sentinel_design_sentinel-phantasm): istemci (HangarShipsCommandHandlerEvent) yuva düzenini "_design"tan önceki
        adla bulup bu adı yazıyor, donanım penceresi düzeni HangarShipEquipmentCommand.lootId ile arıyor (CreateTabSlot); taban ad
        gidince tasarım değişiminden sonraki ilk MANAGE NullReferenceException veriyordu (canlı tur 2)."""
        t = copy(self.ships_tpl)
        t.pop('_m', None)
        sids = sorted(self.p.d['gemiler'], key=int)
        t['ships'] = [mod('HangarShipBriefCommand', isActive=sid == self.p.d['aktif_gemi'], lootId=self.p.ship_look(sid),
                          shipId=int(sid), isFavorite=bool(self.p.ship(sid).get('favori'))) for sid in sids]
        t['allDesignPack'] = [mod('ShipDesignPack', designList=self.designs(sid)) for sid in sids]
        # InventoryItemPack.items sayısı bayt (en çok 255): envanter 255'lik paketlere bölünür. İstemci hepsini okur
        # (InventoryItemData.RefreshItems: paketler üstünde foreach); 268 eşyalı envanterde liste kodlanamıyordu (canlı 2026-10-19)
        items = self.inventory_items()
        t['items'] = [mod('InventoryItemPack', items=items[i:i + PACK_MAX]) for i in range(0, len(items), PACK_MAX)] or \
            [mod('InventoryItemPack', items=[])]
        t['drones'] = self.drone_views()
        t['petView'] = self.pet.view()
        return ('HangarShipsCommand', t)

    def stats(self, sid=None):
        """Bir geminin etkin config'ine göre gösterilen hız, oyun içi hız, kalkan ve kalkan emme oranı."""
        active = sid is None or str(sid) == self.p.d['aktif_gemi']
        eq = self.p.d['ekipman'] if active else self.p.loadout(sid)
        gens = eq.get('generators', [])
        ship = self.p.ship_row(sid) or None                        # giyilen tasarımın temel hızıyla (Centurion 290-315)
        display = speed = None
        if ship:
            display = ship['temel_hiz'] + sum(ESYA['hiz_jeneratorleri'].get(g, {}).get('hiz', 0) for g in gens)
            speed = display - ESYA['hiz_farki']
        form = self.p.mods()                                # formasyon + dron tasarımları
        lab = active and self.p.lab_bonus(2)              # motor yükseltmesi (Duranium, Promerium)
        if ship:
            display = int((display + form.get('hiz_mutlak', 0))                                       # Leonov +20
                          * (1 + form.get('hiz', 0)) * (1 + (lab or 0)) * AY.carpan('gemi_hiz'))     # panel: geminin hızı
            if 'ust_hiz' in form:                           # Speed Burst (teknoloji.py): en az bu hız
                display = max(display, int(form['ust_hiz']))
            if 'sabit_hiz' in form:                         # gemi yetenekleri: Travel 450, Fortify 0 (kıpırdamaz)
                display = int(form['sabit_hiz'])
            if 'azami_hiz' in form:                         # yavaşlatma küresi (Barb, The Stinger, Saboteur): en çok bu hız
                display = min(display, int(form['azami_hiz']))
            speed = max(0, display - ESYA['hiz_farki'])
        # (kalkan, emme): gemideki jeneratörler + dronlardakiler (dron seviyesi bonusuyla, wiki: seviye başına +%4)
        kj = ESYA['kalkan_jeneratorleri']
        glv = (self.p.d.get('ekipman_seviye') if active else self.p.loadout_levels(sid) or {}) or {}
        glv = glv.get('generators', [])
        shields = [(kj[g]['kalkan'] * YK.factor(g, glv[i] if i < len(glv) else 0, YK.SHIELD), kj[g]['emme'])
                   for i, g in enumerate(gens) if g in kj]
        ship_gens = len(shields)
        cid = self.p.ship(sid)['aktif_konfig']
        for (x, loots), (dloot, dup, ilv) in zip(self.p.drone_loadout(sid), self.p.drone_levels(sid)):
            # dron seviyesi ve dronun tasarımı (Hercules: o dronun kalkan jeneratörlerine +%15); dronun ve jeneratörün yükseltmesi
            bonus = 1 + LEVELS[x['seviye'] - 1]['kalkan'] + DESIGNS.get(self.p.drone_design(x, 'design', cid, sid) or '', {}).get('dron_kalkan', 0)
            bonus *= YK.factor(dloot, dup, YK.DRONE_SHIELD)
            shields += [(kj[g]['kalkan'] * bonus * YK.factor(g, ilv[j] if j < len(ilv) else 0, YK.SHIELD), kj[g]['emme'])
                        for j, g in enumerate(loots) if g in kj]
        total = sum(k for k, e in shields)
        absorb = sum(k * e for k, e in shields) / total if total else 0.8
        absorb = max(0.0, min(1.0, absorb + form.get('emme', 0)))
        hp = self.p.ship_row(sid).get('hp')
        total *= 1 + ((active and self.p.lab_bonus(3)) or 0)     # kalkan yükseltmesi (Duranium, Promerium, Seprom, Osmium)
        # panelin geminin canı ve kalkanı çarpanları; kalkan istemciye 32 bitle gider (AttributeShieldUpdateCommand)
        shield_max = min(AY.I32, int(total * (1 + form.get('kalkan', 0)) * AY.carpan('gemi_kalkan')))
        hp_max = max(1, int(hp * (1 + form.get('can', 0)) * AY.carpan('gemi_can') + form.get('can_mutlak', 0))) if hp else None
        if hp_max and active:
            hp_max = max(1, int(hp_max * form.get('can_carpan', 1.0)))   # enfeksiyon: toplam gövdenin %15'i, Pilot Bio dahil
        return dict(display=display, speed=speed, shield_max=shield_max, absorb=absorb,
                    lasers=len(eq.get('laser', [])), speed_gens=sum(1 for g in gens if g in ESYA['hiz_jeneratorleri']),
                    shield_gens=ship_gens, hp_max=hp_max)

    def detail_cmd(self, sid=None):
        t = copy(self.detail_tpl)
        t.pop('_m', None)
        sid = str(sid or self.p.d['aktif_gemi'])
        ship, s, c = self.p.ship(sid), self.stats(sid), self.p.d['cephane']
        if sid == self.p.d['aktif_gemi']:
            g = self.p.d['gemi']
            hull = dict(hp=int(g.get('hitPoints', 0)), maxHp=g.get('hitMax', 0), shield=int(g.get('shield', 0)),
                        nano=int(g.get('nanoHull', 0)), maxNano=g.get('maxNanoHull', 0))
        else:
            hp = self.p.ship_row(sid).get('hp', 0)
            gv = ship.get('govde') or {}
            hull = dict(hp=int(gv.get('hitPoints', hp)), maxHp=hp, shield=0, nano=int(gv.get('nanoHull', 0)), maxNano=hp)
        t.update(hull, hull=round(100 * hull['hp'] / max(hull['maxHp'], 1)),          # gövde bütünlüğü % (kayıt: 115.659/116.000 -> 100)
                 upgradeModuleCount=len(self.p.loadout(sid)['upgrades']),              # takılı gemi yükseltme modülleri
                 laserAmmo=sum(n for k, n in c.items() if k.startswith('ammunition_laser_')),
                 rockets=sum(n for k, n in c.items() if k.startswith('ammunition_rocket_')),
                 laserCount=s['lasers'], speedGenerators=s['speed_gens'], shieldGenerators=s['shield_gens'], shipId=int(sid),
                 isActive=sid == self.p.d['aktif_gemi'], isFavorite=bool(ship.get('favori')), lootId='',
                 curDesignLootId=self.p.ship_look(sid), designList=self.designs(sid),
                 repairVouchers=int((self.p.d.get('kapilar') or {}).get('kupon', 0)))      # kapıların onarım kuponları
        t['maxSpeed'] = s['display'] or 0                       # gemi verisinde yoksa kayıttaki 355 değil
        return ('HangarShipDetailCommand', t)

    def apply_stats(self):
        """Etkin gemi/config değişti: hız/kalkan/görünüm güncellemesi (kayıt: AttributeShipSpeedUpdateCommand, ShipExtensionsCommand)."""
        msgs = []
        s = self.stats()
        g = self.p.d['gemi']
        with self.p.lock:
            if s['speed'] is not None and s['speed'] != g.get('speed'):      # 0: Fortify (kıpırdamaz)
                g['speed'] = s['speed']
                self.p.d['gosterilen_hiz'] = s['display']      # girişteki hız şablonu da bunu kullanır (profil.patch_template)
                msgs.append(('AttributeShipSpeedUpdateCommand', {'newSpeed': s['speed'], 'displaySpeed': s['display']}))
            if s['hp_max'] and s['hp_max'] != g.get('hitMax'):
                g['hitMax'] = s['hp_max']                      # formasyonun can bonusu/cezası (Heart, Moth, Diamond …)
                g['hitPoints'] = min(g.get('hitPoints', 0), s['hp_max'])
                msgs.append(('HitpointInfoCommand', dict(hitpoints=int(g['hitPoints']), hitpointsMax=g['hitMax'],
                                                         nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))))
            if s['shield_max'] != g.get('shieldMax', 0):
                old_max = g.get('shieldMax', 0)
                if getattr(self, 'keep_shield_ratio', False) and old_max > 0:      # formasyon: kalkan yüzdesi korunur
                    g['shield'] = min(s['shield_max'], g.get('shield', 0) * s['shield_max'] / old_max)
                else:
                    g['shield'] = min(g.get('shield', 0), s['shield_max'])
                g['shieldMax'] = s['shield_max']
                msgs.append(('AttributeShieldUpdateCommand', {'shieldNow': int(g['shield']), 'shieldMax': g['shieldMax']}))
            self.p.d['kalkan_emme'] = s['absorb']
            # kargo alanı: geminin kargosu + Logistics yeteneği (yetenek.py); ShipInitializationCommand'da görünür
            base = self.p.ship_row().get('kargo', 0) + self.p.mods().get('kargo_mutlak', 0)      # Leonov +500
            if base and self.p.premium:
                base += PREMIUM_KARGO          # wiki: (taban + Premium 500) x2 kargo sıkıştırıcı; çarpanlar bu toplama
            if base:
                cargo = int(base * (1 + self.p.mods().get('kargo_alani', 0)) * EK.cargo_factor(self.p)    # + kargo CPU'su
                            * (1 + (self.pet.proto('kargo') if self.pet.owned else 0))      # + AI-CR (P.E.T. uzayda olmasa da)
                            * AY.carpan('kargo'))                                       # panel: kargo kapasitesi
                if cargo != g.get('cargoSpaceMax'):
                    g['cargoSpaceMax'] = cargo
                    self.p.sync_cargo()
                    # istemci (UpdateCargoSpaceCommandHandler: Hero.MaxCargo) yeni azamiyi yoksa harita değişimine dek görmüyordu (Ö1)
                    msgs.append(('UpdateCargoSpaceCommand', {'cargoSpaceMax': cargo}))
            # görünüm: lazer sayısına göre 1-3 (kayıt: 1 lazer -> 1, 2 lazer -> 2). ShipInitializationCommand.expansionStage
            # kayıtta 1'de kaldı, yalnız ShipExtensionsCommand değişti; bu yüzden ayrı tutulur (login_msgs girişte yeniden gönderir)
            mm = self.module_update()                          # gemi modüllerinin simgeleri
            if mm[1] != self.p.d.get('modul_simgeleri'):
                self.p.d['modul_simgeleri'] = mm[1]
                msgs.append(mm)
            stage = self.extension_stage()
            if stage != self.p.d.get('uzanti_asamasi', 1):
                self.p.d['uzanti_asamasi'] = stage
                msgs.append(('ShipExtensionsCommand', {'userId': self.p.user_id, 'extensionStage': stage}))
            self.p.dirty = True
        return msgs + self.p.menu_changes()                    # CPU'lar, Smart Bomb, fırlatıcı, yetenekler (canlı test H21)

    def module_update(self):
        """Etkin geminin modül yuvaları ve takılı modüllerin türleri (ShipUpgradeModuleUpdateCommand; kayıtta girişte max 3, boş)."""
        ids = self.p.config().get('upgrades', [])
        types = [MODULE_TYPE_IDS.get(GM.M.get(self.p.d['esyalar'].get(str(i), ''), {}).get('tur'), 1) for i in ids
                 if str(i) in self.p.d['esyalar']]
        return ('ShipUpgradeModuleUpdateCommand', dict(max=self.capacity('upgrades'), moduleTypeIds=types, uid=self.p.user_id))

    def extension_stage(self):
        n = len(self.p.d['ekipman'].get('laser', []))
        return max(1, min(3, math.ceil(3 * n / max(self.capacity('laser'), 1))))

    def login_msgs(self):
        """Harita yüklendikten sonra: ekipmana bağlı görünüm (kayıttaki giriş 1 ile gelir), dronlar ve eşya sayaçları."""
        stage = self.p.d.get('uzanti_asamasi', 1)
        msgs = [('ShipExtensionsCommand', {'userId': self.p.user_id, 'extensionStage': stage})] if stage != 1 else []
        shield = YT.shield_cmd(self.p)
        if shield[1]['shieldSkillId']:
            msgs.append(shield)                     # kalkan yeteneğinin görünümü (yetenek.shield_cmd)
        import yukseltme as YK
        counts = self.count_msgs()
        hour, shop = YK.bonus_hour(), self.discount()
        disc = [('UserInventoryModule', dict(activePremiumDiscount=int(round(shop * 100)), activeRebateSubDiscount=0,
                                             inventoryItemModules=[f['item'] for n, f in counts],
                                             activeHappyUpgradeDiscount=int(round(hour * 100))))] if hour or shop else []
        # hızlı alım öğeleri: şablonun ipucunda kayıttaki hesabın "ttip_currency_missing" satırı vardı, paraya göre (canlı K7)
        return msgs + self.drone_msgs() + counts + disc + self.quick_buy_msgs()   # Upgrade Hour (H40) ya da Shop Discount sürüyorsa indirim

    def count_msgs(self):
        """Girişte istemcinin eşya sayaçları (InventoryItemUpdatedCommand): Assembly malzemeleri buradan sayılır; kayıttaki girişte
        yalnız dört kaynak vardı, para ve öteki malzemeler 0 görünüyordu (canlı test H33). Para, tariflerde geçen eldeki eşyalar, depodaki
        bütün kaynaklar (yükseltme/atlama/Update/Synthesis bedelleri: ABR, Diametrion, Isochronate, Horizon Shard …; yalnız Assembly
        tarifleri sayılınca bunlar 0 görünüyordu, canlı test H59) ve ekipman örnekleri."""
        import assembly as ASM
        import envanter as INV
        held = {k for k, v in self.p.d.get('diger_esyalar', {}).items()
                if v > 0 and k.startswith('resource_') and k not in NO_TRAITS}
        free = AY.get('assembly_ucretsiz')
        loots = ['currency_credits', 'currency_uridium'] + sorted((ASM.INGREDIENTS | YK.INGREDIENTS | held) - {'currency_credits', 'currency_uridium'})
        out = []
        for loot in loots:
            if loot.startswith(('equipment_', 'drone_', 'recipe_')):
                continue                        # örnekli eşyalar hangar envanterinden (HangarShipsCommand)
            n = INV.client_count(self.p, loot)  # gemiler (Plus tariflerinin taban gemisi) dahil
            if free and not loot.startswith('ship_'):
                n = max(n, 10 ** 6)             # Ücretsiz Assembly: istemci bütün malzemeleri yeterli görür
            if n > 0 or loot.startswith('currency_'):
                out.append(self.inv_item(self.item_id(loot), loot, n))
        # eşya örnekleri (seviye, takılı olduğu hangar): Assembly'nin Upgrade/Disassembly sekmeleri yalnız bunları tanıyor (H38)
        hm = self.p.hangar_map()
        for iid, loot in sorted(self.p.d['esyalar'].items(), key=lambda kv: int(kv[0])):
            if loot.startswith(('equipment_', 'drone_designs_', 'pet_designs_')):
                out.append(self.inv_item(int(iid), loot, 1, hm.get(int(iid), 0)))
        return out + [self.drone_item(x) for x in self.p.d['dronlar']] + self.module_items()

    def module_items(self):
        """Takılı olmayan Clan Battle Station modülleri envanterde (kayıttaki gibi: InventoryItemModule, nitelik 0 = can, upgradeLevel):
        Assembly'nin Upgrade sekmesi yükseltilecekleri envanterden seçiyor, modüller hiç gönderilmediği için listede yoktu (oyuncu
        bildirimi 2026-10-27). Build isteğinin targetItemId'si modülün kimliği (yukseltme.target)."""
        cbs = getattr(self, 'cbs', None)
        if not cbs:
            return []
        return [self.module_item(iid, m) for iid, m in sorted(cbs.st['moduller'].items(), key=lambda kv: int(kv[0]))
                if not cbs.where(iid)]

    def module_item(self, iid, m):
        msg = self.inv_item(int(iid), m['loot'], 1, level=int(m.get('seviye', 0)))
        msg[1]['item']['inventoryItemAttributes'] = [mod('InventoryItemAttributeModule', key=0, value=str(int(m.get('can', 0))))]
        return msg

    def ship_count_msgs(self, loots):
        """Gemi kazanılınca/harcanınca Assembly sayacı (yalnız tariflerde taban gemi olanlar; envanter.client_count)."""
        import assembly as ASM
        import envanter as INV
        return [self.inv_item(self.item_id(l), l, INV.client_count(self.p, l)) for l in sorted(set(loots)) if l in ASM.INGREDIENTS]

    def formation_wait(self, loot, now=None):
        """Wait between two formation changes (esyalar.json savas_esyalari.formasyon; client CooldownType DRONE_FORMATION).
        Returns None while the wait runs, else the messages that start it: the shortcut-bar countdown of group 47. The world's
        Esyalar keeps the end in the profile and sends the reset when it ends. Without a world nothing is started."""
        import savas_esya as SE
        now = now or time.time()
        group = SE.item_cooldown(loot)[0]
        if now < SE.ready_at(self.p, group):
            return None
        w = self.world()
        items = getattr(w, 'items', None)
        if items is None:
            return []
        with w.lock:
            return [items.cooldown(loot, now)]

    def change_formation(self, loot):
        """Kısayol çubuğundan formasyon (MenuActionRequest drone_formation_*): DroneFormationChangeCommand, çubukta seçili öğe,
        uzaydaki dizilim ve formasyonun bonuslarıyla hız/kalkan/can."""
        if loot != 'drone_formation_default' and loot not in self.p.d['formasyonlar']:
            self.log('   formasyon yok: %s' % loot)
            return []
        old = self.p.d.get('formasyon', 0)
        new = FORMS[loot]['id']
        if old == new:
            return []
        need = FORM_RULES.get(loot, {}).get('asgari_dron', 0)             # Arrow ve Dome 4, Heart ve Pincer 6 dron (wiki)
        if len(self.p.d['dronlar']) < need:
            self.log('   formasyon yok: %s (en az %d dron gerekir)' % (loot, need))
            return []
        wait = self.formation_wait(loot)
        if wait is None:
            self.log('   formation change refused: still cooling down (%s)' % loot)
            return []
        with self.p.lock:
            self.p.d['formasyon'] = new
            self.p.dirty = True
        msgs = [('DroneFormationChangeCommand', {'uid': self.p.user_id, 'selectedFormationId': new})] + wait
        for k, v in FORMS.items():
            if v['id'] in (old, new):
                st = self.p.menu_status(k)
                if st:
                    msgs.append(('MenuItemStatusCommand', st))
        # kalkan yüzdesi korunur: azami kalkanı artıran formasyon kalkanı doldurmaz (oyuncu bildirimi: düşük kalkanla Heart'tan başka
        # formasyona geçince kalkan tam doluyordu; kalkanı düşüren formasyona girip çıkmak da kalkan kazandırmaz)
        self.keep_shield_ratio = True
        try:
            msgs += self.drone_msgs() + self.apply_stats()
        finally:
            self.keep_shield_ratio = False
        self.log('   formasyon: %s (%d)' % (loot, new))
        self.p.ach('formation', dron=len(self.p.d['dronlar']))
        return msgs

    def favourite(self, f):
        """HangarShipFavouriteRequest {favourite, shipId}: hangarda yıldız. İstemci gemi ışınlamada yalnız favorileri listeler ("You can
        only Warp ships that are marked as your favorites!"). resultId 1 başarı (HangarShipFavouriteCommandHandler; canlı deneme
        2026-10-17: istek hiç işlenmiyordu)."""
        sid = str(f.get('shipId'))
        if sid not in self.p.d['gemiler']:
            return [('HangarShipFavouriteCommand', {'resultId': 0, 'errorMessage': stack_msg('eqt_error_generic')})]
        favs = sum(1 for k, s in self.p.d['gemiler'].items() if s.get('favori') and k != sid)
        if f.get('favourite') and favs >= ESYA.get('favori_gemi_siniri', 10):      # forum 127436: en çok 10 favori gemi
            return [('HangarShipFavouriteCommand', {'resultId': 0, 'errorMessage': stack_msg('items_hangarSlot_max_favs')})]
        with self.p.lock:
            self.p.d['gemiler'][sid]['favori'] = bool(f.get('favourite'))
            self.p.dirty = True
        self.log('   hangar: %s favori %s' % (self.p.ship(sid)['lootId'], 'evet' if f.get('favourite') else 'hayır'))
        return [('HangarShipFavouriteCommand', {'resultId': 1, 'errorMessage': None}), self.ships_cmd()]

    def clear_config(self, f):
        """HangarShipClearConfigRequest {wipe, configId, shipId}: config'teki bütün eşyalar envantere (gemi yuvaları, dronlar
        ve P.E.T.). İstemci başarıda (resultId 1) donanımı yeniden ister (HangarShipClearConfigCommandHandler)."""
        # The client's clear button always sends wipe=0 (gs.log), so drones and P.E.T. are cleared regardless of that flag.
        # Only this config is touched: the other config keeps its ship, drone and P.E.T. items.
        sid = self.ship_sid(f.get('shipId'))
        ship = self.p.ship(sid)
        cid = str(f.get('configId')) if str(f.get('configId')) in ship['konfigler'] else str(ship['aktif_konfig'])
        ids = self.p.ship_items(sid, cid)
        msgs = self.move({'items': ids, 'source': 'ship', 'destination': 'inventory', 'hangarId': ship['hangarId'],
                          'configId': int(cid)}) if ids else []
        self.log('   hangar: %s config %s temizlendi (%d eşya)' % (ship['lootId'], cid, len(ids)))
        return [('HangarShipClearConfigCommand', {'resultId': 1, 'errorMessage': None})] +             [m for m in msgs if m[0] != 'HangarShipMoveItemsCommand']

    # İstemcinin metinleri: "Saves the equipment equipped on both configuration 1 and 2 for this ship." / "Load the equipment saved …" /
    # "Transfer this ship's configuration and equipment to another ship with the same number of slots!" (canlı deneme 2026-10-17:
    # üçü de işlenmiyordu). Kayıt geminin profilinde: kayitli_konfig {config: {yuva: [eşya]}}.
    def save_config(self, f):
        sid = self.ship_sid(f.get('shipId'))
        with self.p.lock:
            ship = self.p.d['gemiler'][sid]
            ship['kayitli_konfig'] = {c: {s: list(v) for s, v in cfg.items()} for c, cfg in ship['konfigler'].items()}
            # Drones and P.E.T. are part of the saved setup too (before, only the ship slots were saved).
            ship['kayitli_dron_konfig'] = {c: {d: list(v) for d, v in cfg.items()} for c, cfg in ship.get('dron_konfig', {}).items()}
            ship['kayitli_dron_tasarim'] = {c: {d: dict(per) for d, per in cfg.items()} for c, cfg in ship.get('dron_tasarim', {}).items()}
            ship['kayitli_pet_konfig'] = {c: {s: list(v) for s, v in cfg.items()} for c, cfg in ship.get('pet_konfig', {}).items()} \
                if self.pet.owned else {}
            self.p.dirty = True
        self.log('   hangar: %s config kaydedildi' % self.p.ship(sid)['lootId'])
        return [('HangarShipSaveConfigCommand', {'title': stack_msg('popup_save_success_title'),
                                                 'description': stack_msg('popup_save_success_description'), 'resultId': 1})]

    def load_config(self, f):
        """Kaydı geri takar: önce iki config'in gemi yuvaları boşalır; kayıttaki eşya artık yoksa (satıldı) ya da başka gemide
        takılıysa atlanır ("Some equipment were not available …")."""
        sid = self.ship_sid(f.get('shipId'))
        ship = self.p.ship(sid)
        saved = ship.get('kayitli_konfig')
        if not saved:
            return [('HangarShipLoadConfigCommand', {'title': stack_msg('eqt_error_generic'), 'description': stack_msg('empty'),
                                                     'resultId': 0})]
        # Drone items, drone designs and P.E.T. items. Saves made before they were stored have no such key: those parts stay as is.
        s_drones = ship.get('kayitli_dron_konfig')
        s_designs = ship.get('kayitli_dron_tasarim')
        s_pet = ship.get('kayitli_pet_konfig') if self.pet.owned else None
        es, hid = self.p.d['esyalar'], ship['hangarId']
        missing = 0
        touched = [i for cfg in ship['konfigler'].values() for ids in cfg.values() for i in ids]
        touched += [i for cfg in saved.values() for ids in cfg.values() for i in ids]
        with self.p.lock:
            for c, cfg in ship['konfigler'].items():
                for s in cfg:
                    cfg[s] = []
            if s_drones is not None:
                for c, cfg in list(ship.get('dron_konfig', {}).items()) + list(s_drones.items()):
                    touched += [i for ids in cfg.values() for i in ids]
                for cfg in ship.get('dron_konfig', {}).values():
                    for d in cfg:
                        cfg[d] = []
            if s_designs is not None:
                for cfg in list(ship.get('dron_tasarim', {}).values()) + list(s_designs.values()):
                    touched += [i for per in cfg.values() for i in per.values() if i]
                ship['dron_tasarim'] = {}
            if s_pet is not None:
                for cfg in list(ship.get('pet_konfig', {}).values()) + list(s_pet.values()):
                    touched += [i for ids in cfg.values() for i in ids]
                for cfg in ship.get('pet_konfig', {}).values():
                    for s in cfg:
                        cfg[s] = []
            busy = self.p.hangar_map()
            used = {}                                   # config -> items already put back (an item is used once per config)

            def free(i, c):
                """The saved item still exists, is not on another ship and is not already used in this config."""
                ok = str(i) in es and busy.get(i, hid) == hid and i not in used.setdefault(str(c), set())
                if ok:
                    used[str(c)].add(i)
                return ok

            for c, slots in saved.items():
                cfg = ship['konfigler'].setdefault(c, {})
                extras = [self.p.d['esyalar'].get(str(i), '') for i in slots.get('extra', [])]     # kayıttaki Slot CPU'suyla
                for s, ids in slots.items():
                    for i in ids:
                        if s == 'upgrades' and GM.type_taken(self.p, i, cfg.get(s, [])):
                            missing += 1                    # her türden bir modül (kural öncesi kaydedilmiş config)
                        elif len(cfg.get(s, [])) < self.capacity(s, sid, extras=extras) and free(i, c):
                            cfg.setdefault(s, []).append(i)
                        else:
                            missing += 1
            for c, per in (s_drones or {}).items():
                dcfg = self.p.drone_config(c, sid)
                for d, ids in per.items():
                    x = self.p.drone(d)                 # the drone may have been sold since
                    lst = dcfg.setdefault(str(d), [])
                    for i in ids:
                        if x and drone_ok(es.get(str(i), '')) and len(lst) < DRONES[x['lootId']]['yuva'] and free(i, c):
                            lst.append(i)
                        else:
                            missing += 1
            for c, cfg in (s_designs or {}).items():
                for d, per in cfg.items():
                    x = self.p.drone(d)
                    for k, i in per.items():
                        d_row = DESIGNS.get(es.get(str(i), ''))
                        if x and d_row and DESIGN_SLOTS.get(k) == d_row['yuva'] and free(i, c):
                            self.p.set_drone_design(x, DESIGN_SLOTS[k], i, c, sid)
                        else:
                            missing += 1
            for c, slots in (s_pet or {}).items():
                pcfg = self.pet.config(c, sid)
                for s, ids in slots.items():
                    for i in ids:
                        if s in pcfg and len(pcfg[s]) < self.pet.open_slots(s) and free(i, c):
                            pcfg[s].append(i)
                        else:
                            missing += 1
            self.p.dirty = True
            self.p.sync_ekipman()
        self.log('   hangar: %s config yüklendi (%d eşya bulunamadı)' % (ship['lootId'], missing))
        desc = self.neden('eksik_yukleme') if missing             else stack_msg('popup_load_success_description')
        msgs = [('HangarShipLoadConfigCommand', {'title': stack_msg('popup_load_success_title'), 'description': desc, 'resultId': 1}),
                self.equipment_cmd(sid)] + self.item_updates(touched)
        if sid != self.p.d['aktif_gemi']:
            return msgs
        msgs += self.apply_stats() + (self.drone_msgs() if s_designs is not None else [])
        return msgs + (self.pet.refresh() if s_pet is not None else [])

    def import_config(self, f):
        """Transfer System: kaynak geminin takılı her şeyi hedef gemiye taşınır (hedefin eski eşyaları envantere): iki config'in gemi
        yuvaları, dronlara takılı lazer/jeneratörler (dron_konfig), dron tasarımları (dron_tasarim) ve P.E.T. donanımı (pet_konfig);
        hepsi gemiye (hangara) bağlı. Kaynakta hiçbir şey takılı kalmaz: hedefe takılamayan gemi modülü ve başka gemiye bağlı QFC
        envantere iner, ekranda uyarı (kullanıcı bildirimi 2026-10-25: tasarımlar, P.E.T. ve bu modüller eski gemide kalıyordu, eski
        gemi seçili değilken normal envanterde görünmüyordu). Hedefin her yuvası taşınan eşya sayısını almalı."""
        import kapi as KAPI
        src, dst = str(f.get('originShipId')), str(f.get('targetShipId'))
        fail = lambda: [('HangarShipImportConfigCommand', {'shipId': int(dst) if dst.isdigit() else 0,
                                                           'errorMessage': stack_msg('error_can_not_equip_to_slot'), 'resultId': 0})]
        if src == dst or src not in self.p.d['gemiler'] or dst not in self.p.d['gemiler']:
            return fail()
        a, b = self.p.ship(src), self.p.ship(dst)
        drop = lambda s, i: ((s == 'upgrades' and not GM.equip_allowed(self.p, i, b['lootId']))
                             or (s == 'QuantumFluidCore' and QF.equip_allowed(self.p, i, b['lootId'], []) is not None))
        go = {c: {s: [i for i in ids if not drop(s, i)] for s, ids in cfg.items()} for c, cfg in a['konfigler'].items()}
        for c, cfg in go.items():
            extras = [self.p.d['esyalar'].get(str(i), '') for i in cfg.get('extra', [])]       # Slot CPU'su da taşınır
            for s, ids in cfg.items():
                if len(ids) > self.capacity(s, dst, extras=extras):
                    self.log('   hangar: aktarım yok: %s %s yuvası %d > %d' % (b['lootId'], s, len(ids), self.capacity(s, dst, extras=extras)))
                    return fail()
        touched = self.p.ship_items(src) + self.p.ship_items(dst)
        dropped = sum(len(ids) - len(go[c][s]) for c, cfg in a['konfigler'].items() for s, ids in cfg.items())
        with self.p.lock:
            for c, cfg in go.items():
                b['konfigler'][c] = cfg
                a['konfigler'][c] = {}
            b['dron_konfig'], a['dron_konfig'] = a.get('dron_konfig', {}), {c: {} for c in a['konfigler']}
            for k in ('dron_tasarim', 'pet_konfig'):
                b[k], a[k] = a.get(k, {}), {}
            self.p.dirty = True
            self.p.sync_ekipman()
        self.log('   hangar: config %s -> %s aktarıldı%s' % (a['lootId'], b['lootId'], ' (%d eşya takılamadı, envantere)' % dropped if dropped else ''))
        msgs = [('HangarShipImportConfigCommand', {'shipId': int(dst), 'errorMessage': None, 'resultId': 1}), self.equipment_cmd(dst)]
        msgs += self.item_updates(touched)                 # aktarılanlar hedef gemide, hedefin eskileri ve takılamayanlar envanterde
        if dropped:
            msgs.append(KAPI.screen(NEDENLER['aktarim_envanter'][1 if self.dil == 'tr' else 0]))
        if self.p.d['aktif_gemi'] in (src, dst):
            msgs += self.apply_stats() + self.drone_msgs() + self.pet.refresh()
        return msgs

    def move(self, f):
        """Takma/çıkarma: istekteki hangarId hangi geminin, configId hangi config'in olduğunu söyler. Hedef/kaynak "ship",
        "inventory", "drone" (+ droneId; lazer/jeneratör "default", tasarım "design", görünüm "visual") ya da "pet" (yuva kümesi
        lasers/generators/gears/protocols; yuvayı eşyanın türü belirler)."""
        ids = [int(x) for x in f.get('items', [])]
        src, dst = (f.get('source') or '').lower(), (f.get('destination') or '').lower()
        sid = self.p.ship_by_hangar(f.get('hangarId')) or self.p.d['aktif_gemi']
        ship = self.p.ship(sid)
        cid = f.get('configId') if str(f.get('configId')) in ship['konfigler'] else ship['aktif_konfig']
        active = sid == self.p.d['aktif_gemi'] and str(cid) == str(ship['aktif_konfig'])
        to_inv = dst in INVENTORY
        drone = self.p.drone(f.get('droneId') or 0) if dst == 'drone' else None
        moved, err, sebep, err_args = [], None, None, {}
        with self.p.lock:
            cfg = self.p.config(cid, sid)
            dcfg = self.p.drone_config(cid, sid)
            pcfg = self.pet.config(cid, sid) if self.pet.owned else {}
            dd = self.p.drone_designs(cid, sid)
            pet_before = {k: list(v) for k, v in pcfg.items()}
            busy = self.p.hangar_map()
            loots = lambda lst: [self.p.d['esyalar'].get(str(i), '') for i in lst]

            def extras_of(lists, skip):
                """Verilen eşya listelerindeki ekstraların lootId'leri, `skip` eşyası hariç (config başına bir tür kuralı)."""
                return [l for l in loots([i for lst in lists for i in lst if i != skip]) if l.startswith('equipment_extra_')]

            def detach(iid):
                """Eşyayı bu config'te bulunduğu yerden (gemi yuvası, dron, P.E.T.) ya da dronun tasarım yuvasından çıkarır."""
                for lst in list(cfg.values()) + list(dcfg.values()) + list(pcfg.values()):
                    if iid in lst:
                        lst.remove(iid)
                        return True
                for d, per in list(dd.items()):
                    for k, v in list(per.items()):
                        if v == iid:
                            del per[k]
                            if not per:
                                del dd[d]
                            return True
                return False

            def fail(why, neden=None):
                nonlocal err, sebep
                err = err or 'error_can_not_equip_to_slot'
                sebep = sebep or neden
                self.log('   hangar: %s' % why)

            for iid in ids:
                loot = self.p.d['esyalar'].get(str(iid)) or ''
                slot = slot_of(loot)
                if not loot:
                    fail('bilinmeyen eşya %s' % iid)
                elif to_inv:
                    rest = [i for i in cfg.get('extra', []) if i not in ids]      # aynı istekle çıkarılanlar sayılmaz (clear_config)
                    if iid in cfg.get('extra', []) and len(rest) > self.capacity('extra', sid, extras=loots(rest)):
                        # açtığı yuvalar doluyken yuva CPU'su çıkmaz (istemcinin metni: "Error: Slot CPU is currently in use.")
                        fail('%s çıkmaz: ekstra yuvaları dolu' % loot)
                        err = 'drone_slotCPUinUse'
                    elif detach(iid):
                        moved.append((iid, loot))
                elif pet_only(loot) and dst != 'pet':
                    fail('%s yalnız P.E.T.\'e takılır' % loot)
                elif loot in DESIGNS:
                    # dron tasarımı: dronun "design" ya da "visual" yuvası (eşyanın türüne göre); eskisi envantere döner
                    if dst != 'drone' or not drone:
                        fail('%s yalnız drona takılır (%r)' % (loot, dst))
                        continue
                    old = self.p.drone_design_id(drone, DESIGNS[loot]['yuva'], cid, sid)
                    if old == iid:
                        continue
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'baska_gemi')
                        continue
                    detach(iid)
                    # yalnız bu geminin bu config'inde (öteki config'in ve öteki gemilerin tasarımı aynı kalır)
                    self.p.set_drone_design(drone, DESIGNS[loot]['yuva'], iid, cid, sid)
                    moved.append((iid, loot))
                    if old:
                        moved.append((old, self.p.d['esyalar'].get(str(old), '')))
                elif dst == 'pet':
                    pslot = PETM.slot_for(loot)
                    if (f.get('slotSet') or '').lower() == 'heat' and PETM.heat_slot_ok(loot):
                        pslot = 'heat'                    # HEAT yuvası: lazer ya da kalkan jeneratörü (HEAT seviyesi 4'ten etkin)
                    if not self.pet.owned or not pslot:
                        fail("%s P.E.T.'e takılamaz" % loot)
                        continue
                    lst = pcfg[pslot]
                    if iid in lst:
                        continue
                    if pslot == 'visual' and lst:         # tek görünüm yuvası: eskisi envantere döner
                        old = lst.pop()
                        moved.append((old, self.p.d['esyalar'].get(str(old), '')))
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'baska_gemi')
                    elif len(lst) >= self.pet.open_slots(pslot):
                        fail('P.E.T. %s yuvaları dolu (%d)' % (pslot, self.pet.open_slots(pslot)), 'pet_dolu')
                    elif pslot in PETM.UNIQUE and loot in [self.p.d['esyalar'].get(str(i)) for i in lst]:
                        fail('%s zaten takılı' % loot, 'pet_zaten')
                    elif self.pet.d['seviye'] < PETM.level_need(self.p.item_level(iid)):
                        fail('%s seviye %d: P.E.T. seviyesi %d gerekir' % (loot, self.p.item_level(iid),
                                                                           PETM.level_need(self.p.item_level(iid))))
                        err = 'pet_gear_requirement'
                        # istemcinin metni "Required: P.E.T. Level %level%" (canlı test: yer tutucu boş kalıyordu)
                        err_args = {'_level_': PETM.level_need(self.p.item_level(iid))}
                    else:
                        detach(iid)
                        lst.append(iid)
                        moved.append((iid, loot))
                elif not slot:
                    fail('%s buraya takılamaz (%r)' % (loot, dst))
                elif dst == 'drone':
                    lst = dcfg.setdefault(str(drone['kimlik']), []) if drone else None
                    if lst is not None and iid in lst:
                        continue
                    held = extras_of([cfg.get('extra', [])] + list(dcfg.values()), iid) if loot in DRONE_EXTRAS else []
                    if not drone or not drone_ok(loot):
                        fail('%s drona takılamaz (dron %s)' % (loot, f.get('droneId')))   # lazer, kalkan jeneratörü ve ekstralar
                    elif busy.get(iid, ship['hangarId']) != ship['hangarId'] or len(lst) >= DRONES[drone['lootId']]['yuva']:
                        fail('dron %s dolu ya da eşya başka gemide' % f.get('droneId'))
                    elif loot in held or (loot.startswith(REPBOT) and any(l.startswith(REPBOT) for l in held)):
                        # config başına her ekstradan bir tane, gemi ve dronlar birlikte (istemci SSS drones_specials_p)
                        fail('%s: config\'te var (gemi ya da dron)' % loot)
                        err = 'special_generic_hint'
                    else:
                        detach(iid)
                        lst.append(iid)
                        moved.append((iid, loot))
                elif dst in PANELS and PANELS[dst] in (None, slot):
                    lst = cfg.setdefault(slot, [])
                    if iid in lst:
                        continue
                    if busy.get(iid, ship['hangarId']) != ship['hangarId']:
                        fail('%s başka gemide takılı' % loot, 'baska_gemi')
                    elif slot == 'upgrades' and not GM.equip_allowed(self.p, iid, ship['lootId']):
                        fail('%s bu gemiye takılmaz (%s)' % (loot, ship['lootId']))      # modülün gemileri
                    elif slot == 'upgrades' and GM.type_taken(self.p, iid, lst):
                        fail('%s: gemide %s türünden modül var' % (loot, GM.kind(loot)), 'ayni_modul')    # her türden bir modül
                    elif slot == 'QuantumFluidCore' and QF.equip_allowed(self.p, iid, ship['lootId'], lst):
                        fail('%s: %s' % (loot, QF.equip_allowed(self.p, iid, ship['lootId'], lst)),     # bağlı gemi, AX/DF birer
                             'qfc_gemi' if (QF.state(self.p, iid) or {}).get('gemi') != ship['lootId'] else 'ayni_qfc')
                    elif slot in PC.SLOTS and PC.equip_allowed(self.p, iid, slot, lst):
                        fail('%s: %s' % (loot, PC.equip_allowed(self.p, iid, slot, lst)), 'ayni_top')   # her türden bir top
                    elif slot == 'extra' and EK.slot_bonus_of([loot]) and EK.slot_bonus_of(loots(lst)):
                        fail('%s: config\'te yuva CPU\'su var' % loot, 'tek_yuva_cpu')       # config başına bir yuva CPU'su (wiki)
                    elif slot == 'extra' and (loot in extras_of(dcfg.values(), iid) or loot in loots(lst) or loot.startswith(REPBOT)
                                              and any(l.startswith(REPBOT) for l in extras_of([lst] + list(dcfg.values()), iid))):
                        # config başına bir onarım robotu (kullanıcı bildirimi 2026-10-24: iki tane takılabiliyordu); istemcinin metni
                        # "Only one of these items is allowed per configuration."
                        fail('%s: config\'te onarım robotu ya da dronda aynı ekstra var' % loot)
                        err = 'special_generic_hint'
                    elif len(lst) >= self.capacity(slot, sid, extras=loots(cfg.get('extra', []))):
                        fail('%s yuvaları dolu' % slot)
                    else:
                        detach(iid)                                       # dronda ya da P.E.T.'te takılıysa oradan alınır
                        lst.append(iid)
                        moved.append((iid, loot))
                else:
                    fail('bilinmeyen panel %r -> %r' % (src, dst))
            if moved:
                self.p.dirty = True
                self.p.sync_ekipman()
            pet_changed = {k: list(v) for k, v in pcfg.items()} != pet_before
        where = ' (dron %s%s)' % (f.get('droneId'), ' ' + f['slotSet'] if f.get('slotSet') else '') if 'drone' in (src, dst) else ''
        self.log('   hangar %s config %s: %s %s -> %s%s%s' % (ship['lootId'], cid, ', '.join(l.rsplit('_', 1)[-1] for i, l in moved) or '-',
                                                            src, dst, where, ' (hata: %s)' % err if err else ''))
        ok = bool(moved) or not err
        msg = self.neden(sebep) if sebep and err == 'error_can_not_equip_to_slot' else stack_msg(err, **err_args) if err else None
        msgs = [('HangarShipMoveItemsCommand', {'result': 1 if ok else 0, 'errorMessage': None if ok else msg})]
        if moved:
            hm = self.p.hangar_map()
            msgs += [self.inv_item(i, l, 1, hm.get(i, 0)) for i, l in moved]
            msgs.append(self.equipment_cmd(sid))
            # istemcinin envanter ızgarası bu paketle yenilenir (kayıt: takmadan sonra o yuvanın eşyaları hangarId ile)
            slots = {slot_of(l) for i, l in moved}
            group = [i for c in ship['konfigler'].values() for s in slots for i in c.get(s, [])]
            group += [i for k in ('dron_konfig', 'pet_konfig') for c in ship.get(k, {}).values() for ids_ in c.values() for i in ids_]
            group += [i for c in ship.get('dron_tasarim', {}).values() for per in c.values() for i in per.values() if i]
            items = list(dict.fromkeys([i for i, l in moved] + group))
            msgs.append(self.pack([self.hangar_item(i, self.p.d['esyalar'][str(i)], 1, hm.get(i, 0)) for i in items]))
            if active:
                msgs += self.apply_stats()
            if active and any(l in DESIGNS for i, l in moved):
                msgs += self.drone_msgs()                  # uzaydaki dronların görünümü
            if pet_changed and sid == self.p.d['aktif_gemi']:
                # uzaydaki P.E.T.'in dişlileri ve değerleri: yalnız P.E.T.'in donanımı değişince (gemiye lazer/jeneratör takmak da
                # P.E.T. yuvası türünden sayılıyordu, her seferinde seviye atlama efekti çıkıyordu)
                msgs += self.pet.refresh()
        return msgs

    # ------------------------------------------------------------ gemi değiştirme ve config geçişi
    def activate(self, f, in_station=True, travel=False):
        """HangarShipActivateShipRequest {shipId} -> HangarShipActivateShipCommand (istemci: result 1 başarı, mesaj penceresi).
        Oyundaki gibi yalnız istasyonda. Başarılıysa (mesajlar, True): oturum gemiyi yeniden yükletir (ShipInitializationCommand).
        Her gemi bırakıldığı yerde kalır (forum 127436: hangardan değiştirince "aktüel gemin aktif haritada bulunduğun yerde kalır");
        travel (hangar) pilotu yeni geminin kayıtlı konumuna götürür, ışınlamada (isinlama.py) gemi pilota gelir."""
        sid = str(f.get('shipId'))
        reply = lambda res, err=None, ok=None: ('HangarShipActivateShipCommand', {
            'errorMessage': err, 'successMessage': ok, 'currentShipLootId': self.p.ship()['lootId'], 'result': res})
        if sid not in self.p.d['gemiler']:
            return [reply(0, stack_msg('eqt_error_generic'))], False
        if sid == self.p.d['aktif_gemi']:
            return [reply(1, ok=stack_msg('info_text_switch_active_hangar_success'))], False
        if not in_station:
            self.log('   gemi değişmedi: istasyonda değil')
            return [reply(0, stack_msg('info_text_switch_hangar_station_only'))], False
        with self.p.lock:
            g = self.p.d['gemi']
            self.p.ship()['govde'] = {'hitPoints': int(g.get('hitPoints', 0)), 'nanoHull': int(g.get('nanoHull', 0))}
            k = self.p.d['konum']
            if H.parked(k.get('mapId')):
                self.p.ship()['konum'] = {'mapId': k['mapId'], 'x': int(k['x']), 'y': int(k['y'])}
            old = self.p.ship()['lootId']
            self.p.d['aktif_gemi'] = sid
            new = self.p.ship()
            dest = new.get('konum')
            if travel and dest and H.parked(dest.get('mapId')):
                k.update(dest)
            row = self.p.ship_row(sid)
            hp = row.get('hp', g.get('hitMax', 0))
            gv = new.get('govde') or {'hitPoints': hp, 'nanoHull': 0}
            cargo = row.get('kargo', g.get('cargoSpaceMax', 0))
            g.update(typeId=self.p.ship_look(sid), hitMax=hp, maxNanoHull=hp, hitPoints=min(gv['hitPoints'], hp), nanoHull=gv['nanoHull'],
                     cargoSpaceMax=cargo)
            self.p.sync_cargo()                                    # boş alan = yeni geminin kargosu - cevherler
            self.p.sync_ekipman()
            self.p.dirty = True
        # apply_stats durumları "gönderildi" diye işaretliyor: mesajları atılırsa yeni geminin AJP-01'i (CPUInitializationCommand)
        # hiç gitmiyordu, uzay haritası eski geminin atlama panelini gösteriyordu (kullanıcı bildirimi 2026-10-25)
        stats = self.apply_stats()
        self.log('   gemi değişti: %s -> %s (shipId %s)' % (old, new['lootId'], sid))
        return [reply(1, ok=stack_msg('info_text_switch_active_hangar_success'))] + stats, True

    def designs(self, sid=None):
        """Hangardaki tasarım listesi (açılır menü): geminin kendi görünümü + satın alınan tasarımlar."""
        s = self.p.ship(sid)
        return [s['lootId']] + list(s.get('tasarimlar', []))

    def change_model(self, f):
        """HangarShipChangeShipModelRequest {shipId, lootId} (hangardaki tasarım menüsü, UINewHangarSystem.DropdownValueChanged)
        -> HangarShipChangeShipModelCommand {resultId 1}. Etkin gemide görünüm değişince (mesajlar, True): oturum gemiyi yeniden
        yükletir (ShipInitializationCommand.typeId = tasarım)."""
        sid = str(f.get('shipId'))
        loot = f.get('lootId', '')
        reply = lambda res, err=None: ('HangarShipChangeShipModelCommand', {'resultId': res, 'errorMessage': err})
        if sid not in self.p.d['gemiler']:
            return [reply(0, stack_msg('dse_ship_not_exist'))], False
        if loot not in self.designs(sid):
            self.log('   tasarım yok: %s (%s)' % (loot, self.p.ship(sid)['lootId']))
            return [reply(0, stack_msg('eqt_error_generic'))], False
        with self.p.lock:
            ship = self.p.ship(sid)
            old = self.p.ship_look(sid)
            ship['tasarim'] = None if loot == ship['lootId'] else loot
            trimmed = self.trim_slots(sid)               # tasarımın yuvası azsa (Tyrannos 15 lazer, *-6 roketsiz) fazlası envantere
            active = sid == self.p.d['aktif_gemi']
            if active:
                self.p.d['gemi']['typeId'] = self.p.ship_look(sid)
                self.p.sync_ekipman()
            self.p.dirty = True
        self.log('   görünüm: %s -> %s' % (old, self.p.ship_look(sid)))
        # envantere inenler istemcide de takılı değil (önceden hangar listesi yeniden istenene dek takılı görünüyordu)
        freed = [self.equipment_cmd(sid)] + self.item_updates(trimmed) if trimmed else []
        # tasarımın kendi değerleri (profil.ship_row): hız, can, yuvalar, bonuslar
        return [reply(1)] + freed + (self.apply_stats() if active else []), active and old != self.p.ship_look(sid)

    def switch_config(self, n):
        """İstemcinin "S|CFG|n|…" isteği (kayıt: t≈591 ve 598). Yanıt kayıttaki sırayla: arayüz yenileme, görünüm, can;
        kalkan, 0|n|e, görünüm, 0|n|INV, 0|S|CFG|n; hız."""
        ship = self.p.ship()
        n = int(n)
        if str(n) not in ship['konfigler']:
            return []
        if n != 1 and ((self.p.d.get('pve') or {}).get('astral') or {}).get('kosu'):     # forum 162090: Astral'da yalnız Ayar 1
            self.log('   Astral: Ayar %d kapalı' % n)
            return [legacy('0|S|CFG|1')]
        now = time.time()
        if now - getattr(self, 'last_config', 0) < CONFIG_COOLDOWN_SN:       # kayıt: 2,4 sn sonraki ikinci geçiş reddedildi
            self.log('   config geçişi bekliyor')
            return [legacy('0|A|STM|config_change_failed_time')]
        self.last_config = now
        g = self.p.d['gemi']
        with self.p.lock:
            # each config keeps its own shield: save the current one before leaving it
            shields = ship.setdefault('kalkanlar', {})
            shields[str(ship['aktif_konfig'])] = int(g.get('shield', 0))
            ship['aktif_konfig'] = n
            self.p.sync_ekipman()
            self.p.dirty = True
        # can, kalkan, hız ve görünüm aşağıda kayıttaki sırayla; ötekiler (config'in CPU'ları ve fırlatıcısı kısayol çubuğunda, modül
        # simgeleri, kargo) atılıyordu: çubuk eski config'in CPU'larını gösteriyordu
        later = [m for m in self.apply_stats() if m[0] not in ('AttributeShipSpeedUpdateCommand', 'HitpointInfoCommand',
                                                                 'AttributeShieldUpdateCommand', 'ShipExtensionsCommand')]
        with self.p.lock:
            # restore the new config's own shield (never used yet: starts empty), capped by its shieldMax
            g['shield'] = max(0, min(int(shields.get(str(n), 0)), g.get('shieldMax', 0)))
        uid = self.p.user_id
        stage = ('ShipExtensionsCommand', {'userId': uid, 'extensionStage': self.p.d.get('uzanti_asamasi', 1)})
        s = self.stats()
        msgs = [('RefreshSelectedUICategoryCommand', {}), stage,
                ('HitpointInfoCommand', dict(hitpoints=int(g.get('hitPoints', 0)), hitpointsMax=g.get('hitMax', 0),
                                             nanoHull=int(g.get('nanoHull', 0)), nanoHullMax=g.get('maxNanoHull', 0))),
                ('AttributeShieldUpdateCommand', {'shieldNow': int(g.get('shield', 0)), 'shieldMax': g.get('shieldMax', 0)}),
                # kalkan yeteneğinin görünümü (kayıttaki yeteneksiz hesapta shieldSkillId 0: istemci varsa ShieldEffect'i kaldırır; K3)
                YT.shield_cmd(self.p),
                legacy('0|n|e|%d|0|0' % uid), stage, legacy('0|n|INV|%d|0' % uid), legacy('0|S|CFG|%d' % n)]
        if s['speed'] is not None:
            msgs.append(('AttributeShipSpeedUpdateCommand', {'newSpeed': s['speed'], 'displaySpeed': s['display']}))
        self.log('   config %d: %s' % (n, ', '.join('%s %d' % (k, len(v)) for k, v in self.p.d['ekipman'].items() if v)))
        # + dronların bu config'teki tasarımları (uzaydaki görünüm) ve P.E.T.'in bu config'teki donanımı (uzaydaysa)
        return msgs + later + self.drone_msgs() + self.pet.refresh()
