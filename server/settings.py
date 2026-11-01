"""Oyun ayarları (yönetim paneli, panel/): çarpanlar, etkinlik seçimi, müzayede rakipleri, sunucu seçenekleri.

Ayarların tek tanımı SCHEMA: panel arayüzü bundan kurulur, sunucu değerleri get() ile okur. Değerler save/ayarlar.json'da
({anahtar: değer, 'etkinlikler': {etkinlik: 'acik' | 'kapali'}}); dosyada olmayan anahtar varsayılandır, bilinmeyenler yok sayılır,
sayılar sınırlara kırpılır, bozuk dosya varsayılanlara döner.
Sınırlar (2026-10-19, kullanıcı isteği: "uridyum çarpanını 50'den fazla yapamıyorum"): 'min'..'max' panelin sürgüsünün önerilen
aralığı; sayı kutusuna elle 'sinir'e dek her değer yazılabilir (yoksa UST_SINIR). 'sinir' yalnız güvenlik içindir: istemciye 32 bitlik
alanla giden değerlerin taşması (can, kalkan, hasar), sunucunun yükü (uzaylı ve kutu sayısı) ya da mantıksal üst (kapı sayısı).
Dosya değişince (panelden kaydedilince) en geç YENILE_SN içinde yeniden okunur, oyun açıkken de geçerli olur. Her ayarın
'uygulama' alanı ne zaman etkili olduğunu söyler:
  anında    bir sonraki olayda (hasar, ödül, kutu içeriği …)
  harita    harita yeniden kurulunca (harita değişimi, ölüm sonrası doğma): NPC ve kutu sayısı
  giriş     oyuna yeniden girince (etkinlikler istemciye girişte bildirilir; açılır pencereler)
  başlatma  sunucu yeniden başlayınca
Alt ayarlar (2026-10-24, kullanıcı isteği: uridyumu kutulardan, uzaylılardan, kapılardan ayrı ayrı ayarlamak): ALTLAR'daki
çarpanların kaynaklara göre alt çarpanları var (anahtar <üst>_<kaynak>: uridyum_npc, magaza_fiyat_kredi …; şemada 'ust' ve 'kaynak'
alanlarıyla üstünün hemen ardında). Etkin çarpan üst x alt: carpan('uridyum', 'npc'); kaynağın alt ayarı yoksa yalnız üst. Aralık,
sınır ve uygulama üstünden, varsayılan x1; hazır ayarlar yalnız üstleri değiştirir. Panel alt ayarları üstünün altında açılan
"Kaynağa göre" bölümünde gösterir.
Oyun sunucusu configure() ile dosyayı bağlar (game.main, --settings=<yol> seçeneği ya da save/ayarlar.json). Bağlanmamışken
(testler, araçlar) bütün ayarlar varsayılandır: kullanıcının ayarları testleri etkilemez.
"""
import json, os, random, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATH = os.path.join(HERE, 'save', 'settings.json')
REFRESH_SEC = 1.0

GROUPS = (('gemi', 'Gemin'), ('savas', 'Savaş ve uzaylılar'), ('reward', 'Ödüller'), ('progress', 'İlerleme'), ('world', 'Dünya'),
           ('kapi', 'Kapılar ve modlar'), ('economy', 'Ekonomi'), ('sure', 'Süreler'), ('auction', 'Müzayede'), ('ui', 'Arayüz'),
           ('manager', 'Yönetici'), ('developer', 'Geliştirici'))
RIVAL_LEVELS = ('Kapalı', 'Çekingen', 'Ilımlı', 'Rekabetçi', 'Agresif')
UPPER_LIMIT = 10000.0             # çarpanların elle yazılabilen en büyük değeri ('sinir' verilmemişse)
I32 = 2 ** 31 - 1               # istemciye 32 bitlik alanla giden değerlerin üstü (protokol taşırır: can, kalkan, fiyat)


def _c(key, name, group, description, apply_mode='anında', lo=0.0, hi=10.0, step=0.1, default=1.0, limit=UPPER_LIMIT, condition=None):
    """Çarpan: panelde sürgü (lo..hi, önerilen) ve sayı kutusu (lo..sinir). kosul: yalnız o açma kapama ayarı açıkken görünür."""
    return dict(anahtar=key, ad=name, grup=group, tur='carpan', default=default, min=lo, max=hi, cap=max(hi, limit), step=step,
                aciklama=description, apply_mode=apply_mode, **({'condition': condition} if condition else {}))


def _b(key, name, group, description, apply_mode='anında', default=False):
    return dict(anahtar=key, ad=name, grup=group, tur='bool', default=default, aciklama=description, apply_mode=apply_mode)


def _n(key, name, group, description, apply_mode='anında', lo=0, hi=10, default=1, unit='', limit=None):
    """Tam sayı (adet, saat): panelde sayı kutusu; hi önerilen üst, sinir elle yazılabilen en büyük (yoksa hi)."""
    return dict(anahtar=key, ad=name, grup=group, tur='sayi', default=default, min=lo, max=hi, cap=max(hi, limit or hi),
                unit=unit, aciklama=description, apply_mode=apply_mode)


SCHEMA = [
    # ---------------------------------------------------------------- gemin
    _c('ship_hp', 'Geminin canı', 'gemi', 'Geminin azami canı (gövde): formasyon, booster ve laboratuvar bonuslarıyla birlikte. '
       'Oyun açıkken de değişir.', lo=0.1, limit=1000.0),
    _c('ship_shield', 'Geminin kalkanı', 'gemi', 'Geminin azami kalkanı (gemideki ve dronlardaki kalkan jeneratörleri, bonuslarla '
       'birlikte). Oyun açıkken de değişir.', limit=500.0),
    _c('ship_speed', 'Geminin hızı', 'gemi', 'Geminin uçuş hızı (hız jeneratörleri ve bonuslarla birlikte). Yavaşlatma ve Fortify '
       'gibi etkiler yine geçerli.', lo=0.25, hi=3.0, limit=10.0),
    _c('shield_regen', 'Kalkanın dolma hızı', 'gemi', 'Savaş dışında kalkanın kendiliğinden dolması (oyunun değeri saniyede '
       '%4). 0: kalkan kendiliğinden dolmaz.', limit=100.0),
    _c('repair_speed', 'Onarım robotu hızı', 'gemi', 'Onarım robotunun (REP) gövdeyi onarma hızı.', lo=0.1, limit=1000.0),
    _c('player_hit_chance', 'İsabet şansın', 'gemi', "Lazerlerinin, roketlerinin ve P.E.T.'inin isabet olasılığı (oyunun değeri %80, "
       'en çok %100). x1,25: her atış isabet eder.', lo=0.1, hi=2.0, limit=100.0),
    _c('rocket_cooldown', 'Roket bekleme süresi', 'gemi', 'Roketlerin ve roket fırlatıcısının bekleme ve dolma süresi. Düşük değer: '
       'daha sık atış.', lo=0.05, hi=5.0, limit=100.0),
    _b('immune_until', 'Dokunulmaz gemi', 'gemi', 'Uzaylıların atışları görünür ama gemin can ve kalkan kaybetmez.'),
    _b('infinite_ammo', 'Sonsuz cephane', 'gemi', 'Lazer cephanesi, roketler, fırlatıcı cephanesi ve mayınlar harcanmaz (en az '
       'bir tane olmalı).'),
    _b('infinite_technology', 'Sonsuz teknoloji', 'gemi', 'Teknoloji eşyaları (Energy Leech, Battle Repair Bot, Speed Burst …) '
       'kullanılınca harcanmaz (en az bir tane olmalı). Bekleme süreleri yine geçerli.'),
    _b('own_mine', 'Kendi mayınların sana zarar verir', 'gemi', 'Kendi bıraktığın mayının patlaması gemine de hasar verir '
       '(oyundaki gibi). Kapatılırsa yalnız uzaylılara.', default=True),
    _n('on_spot_hp', 'Yerinde onarımda can', 'gemi', 'Gemi yok edildikten sonra bulunduğun yerde onarılınca gelen can (oyunun '
       'değeri %10; kalkan boş başlar).', lo=1, hi=100, default=10, unit='%'),
    _n('on_spot_protection', 'Yerinde onarım sonrası koruma', 'gemi', 'Bulunduğun yerde onarıldıktan sonra hasar almadığın süre '
       '(oyunun değeri 10 sn). Ateş edince biter.', lo=0, hi=60, default=10, unit='sn', limit=3600),
    # ---------------------------------------------------------------- savaş ve uzaylılar
    _c('npc_damage', 'Uzaylıların verdiği hasar', 'savas', 'Uzaylıların (NPC) gemine, P.E.T.\'ine ve dost gemilere verdiği hasar. '
       '0: hiç hasar almazsın.', limit=1000.0),
    _c('player_damage', 'Verdiğin hasar', 'savas', 'Lazer, roket, fırlatıcı, mayın, Smart Bomb, top, P.E.T. ve yeteneklerle '
       'uzaylılara, oyunculara ve botlara verdiğin hasar.', lo=0.1, limit=1000.0),
    _c('npc_can', 'Uzaylıların canı ve kalkanı', 'savas', 'Uzaylıların can ve kalkanı. Düşük değer uzaylıları çabuk '
       'öldürür.', apply_mode='harita', lo=0.1, limit=100.0),
    _c('npc_hit_chance', 'Uzaylıların isabet şansı', 'savas', 'Uzaylıların gemine ve P.E.T.\'ine isabet ettirme olasılığı (oyunun '
       'değeri %60, en çok %100). 0: hiç isabet etmezler.', hi=2.0, limit=100.0),
    _c('npc_speed', 'Uzaylıların hızı', 'savas', 'Uzaylıların uçuş hızı (hareketsiz olanlar kıpırdamaz).', lo=0.1, hi=3.0, limit=10.0),
    dict(anahtar='npc_aggression', ad='Uzaylıların saldırganlığı', grup='savas', tur='seviye', default=0,
         options=['Türüne göre', 'Hepsi saldırgan', 'Hiçbiri saldırgan'], colors=['', 'err', 'ok'], apply_mode='anında',
         option_description=['Oyundaki gibi: saldırgan türler seni görünce saldırır, ötekiler vurulunca karşılık verir.',
                           'Bütün uzaylılar seni fark edince kovalar ve saldırır.',
                           'Hiçbir uzaylı kendiliğinden saldırmaz; vurduğun uzaylı yine karşılık verir.'],
         aciklama='Uzaylıların seni kendiliğinden kovalayıp kovalamadığı (kapı ve mod dalgalarındakiler dahil).'),
    _c('npc_notice', 'Uzaylıların fark etme mesafesi', 'savas', 'Saldırgan uzaylıların seni fark edip kovalamaya başladığı uzaklık '
       '(oyunun değeri 1.000 birim).', lo=0.1, hi=3.0, limit=20.0),
    _c('npc_range', 'Uzaylıların ateş menzili', 'savas', 'Uzaylıların sana lazer, roket ve bomba atabildiği uzaklık (oyunun '
       'değeri çoğunda 450, Kristallon türlerinde 550, hareketsizlerde 1.000 birim; dünya patronlarının saldırıları dahil).', lo=0.1, hi=3.0, limit=20.0),
    _b('slowing_shots', 'Yavaşlatan uzaylı atışları', 'savas', 'Barb, The Stinger, Saboteur ve Mindfire Behemoth gibi '
       'uzaylıların atışları gemini yavaşlatır. Kapatılırsa yalnız hasar verirler.', default=True),
    _b('company_pvp', 'Kendi şirketine saldırı', 'savas', 'Aynı şirketten oyunculara ve botlara saldırabilirsin (oyundaki gibi): '
       'şirketin X-1 ve X-2 haritalarında yasak, yok etmek ceza getirir. Kapatılırsa kendi şirketine saldıramazsın (savaştaki klanlar '
       'hariç).', default=True),
    _c('radiation', 'Radyasyon hasarı', 'savas', 'Harita sınırının dışındaki radyasyonun gövdeye verdiği hasar. 0: radyasyon '
       'zarar vermez.', lo=0.0, hi=5.0, limit=100.0),
    _c('ksi_can', 'Klan Savaş İstasyonu canı', 'savas', 'Bütün Klan Savaş İstasyonlarının (seninkinin, bot klanlarının ve rakip klanların) '
       'modüllerinin canı ve kalkanı. Değişince modüllerin mevcut canı oranıyla ölçeklenir; istemcide çubuklar haritaya yeniden '
       'girince ya da modül vurulunca yenilenir.', apply_mode='harita', lo=0.1, hi=10.0, limit=1000.0),
    _c('cbs_damage', 'Klan Savaş İstasyonu hasarı', 'savas', 'Bütün Klan Savaş İstasyonlarının silah modüllerinin verdiği hasar '
       '(uzaylılara ve rakip istasyonun sana).', lo=0.0, hi=10.0, limit=1000.0),
    # ---------------------------------------------------------------- ödüller
    _c('kredi', 'Kredi kazancı', 'reward', 'Uzaylı, kutu, görev, kapı ve etkinliklerden kazanılan kredi (satış ve iadeler '
       'hariç).', hi=50.0, limit=100000.0),
    _c('uridyum', 'Uridyum kazancı', 'reward', 'Uzaylı, kutu, görev, kapı ve etkinliklerden kazanılan uridyum.', hi=50.0,
       limit=100000.0),
    _c('ep', 'Deneyim (EP) kazancı', 'reward', 'Kazanılan deneyim puanı: seviye atlama hızı.', hi=50.0, limit=100000.0),
    _c('onur', 'Onur kazancı', 'reward', 'Kazanılan onur puanı.', hi=50.0, limit=100000.0),
    _c('collecting', 'Toplanan eşya miktarı', 'reward', 'Kutulardaki cephane ve eşyalar, uzaylıların kargo kutularındaki ve '
       'madenden toplanan cevher, uzaylıların ek ödülleri (Palladium, etkinlik paraları …). Kutudan çıkan kredi ve uridyum '
       'kendi çarpanıyla.', hi=50.0),
    _c('mode_reward', 'Görev, kapı ve etkinlik eşya ödülleri', 'reward', 'Görevlerin, Galaksi Kapılarının, etkinlik kapılarının, '
       'modların (Astral, EBL, Mimesis, Galaxy Trek …), Acil Görevlerin ve Dispatch\'in verdiği cephane, kaynak, anahtar ve '
       'teknoloji eşyası miktarı. Gemi, lazer ve tasarım gibi tek eşyalar bir tane kalır; para ve EP kendi çarpanıyla.', hi=50.0),
    _c('drop', 'Eşya düşme şansı', 'reward', 'Uzaylılardan booster, ekipman, kaynak ve etkinlik kutusu düşme olasılığı; '
       'Galaksi Kapısı şanslı ödülleri (en çok %100).', hi=20.0, limit=1000.0),
    _b('x1_cargo', "X-1'de yüksek seviye kargo ve ödül azalması", 'reward', "X-1 haritalarında seviyen yükseldikçe uzaylıların kargo kutusu "
       'küçülür (seviye 7: %50, 10 ve üstü: hiç), kendi X-1 haritanda öldürme ödülü de azalır (seviye 15 ve üstü: hiç; oyundaki gibi). '
       'Kapatılırsa her seviyede tam kargo ve ödül.', default=True),
    _b('etiket', 'Uzaylı etiketleme', 'reward', 'Uzaylıya ilk ateş eden onu etiketler: ödülü, görev sayımı ve kargo kutusu onun (ya da '
       'grubunun) olur, başkası bitirse de. Etiket sahibi 15 saniye vurmazsa etiket düşer. Kapatılırsa ödül son vuranın.',
       default=True),
    _b('player_tag', 'Oyuncu bot etiketini alır', 'reward', "Bir botun etiketlediği uzaylıya sen ateş edersen etiket sana geçer: "
       'ödül, görev sayımı ve kargo kutusu senin olur (aynı gruptaki botlar yine paylaşır). Cubikon, Mindfire Behemoth ve dünya '
       'patronları gibi birlikte dövüşülen uzaylılarda etiket geçmez: ödül, verilen hasara göre oyuncu ve botlar arasında bölünür; '
       'kargo kutusu en çok hasar verene gider. Etiket ayarı kapalıysa etkisizdir.', default=False),
    _b('cargo_ownership', 'Kargo kutusu sahipliği', 'reward', "Uzaylının kargo kutusu yalnız sahibinindir; başkalarına mavi görünür "
       "(oyunun Ayarlar > Ekran'daki başkalarının kargo kutuları seçeneği açıksa). Aynı firmadan birinin kutusunu toplamak onur "
       'kaybettirir: o gün ilki 10, her seferinde iki katı. Kapatılırsa herkes toplar, ceza yok.', default=True),
    # ---------------------------------------------------------------- ilerleme
    _c('drone_xp', 'Dron deneyimi', 'progress', 'Dronlarının uzaylı öldürünce kazandığı puan: dron seviye atlama hızı.',
       hi=50.0),
    _c('pet_ep', "P.E.T. deneyimi", 'progress', "P.E.T.'in kazandığı deneyim (oyunun değeri kazandığın EP'nin %5'i): P.E.T. "
       'seviye atlama hızı.', hi=50.0),
    _c('season_points', 'Season Pass puanı', 'progress', 'Season Pass görevlerinden kazanılan puan: sezon seviyesi atlama hızı.',
       hi=50.0),
    _n('season_duration', 'Season Pass süresi', 'progress', 'Bir sezonun süresi. Sezon kaydın ilk girişinde 1. günden başlar, bitince '
       'alınmamış ödüller verilir ve sıradaki sezon başlar (gerçek oyunda ~3 ay). Değişiklik süren sezona da uygulanır.',
       lo=1, hi=180, default=90, unit='gün', limit=3650),
    _n('battle_pass_duration', 'Battle Pass süresi', 'progress', "Battle Pass'in süresi. Pass'li bir etkinlik açılınca kaydın pass'i "
       "1. günden başlar ve bu süre boyunca etkinlikle birlikte sürer (takvimdeki dönemi daha önce bitse de); aynı anda tek "
       "pass (gerçek oyunda ~2 hafta).", lo=1, hi=60, default=14, unit='gün', limit=365),
    _c('booster_power', 'Booster etkisi', 'progress', 'Boosterların bonusu (hasar, can, kalkan, EP, onur …) ve türlerin üst '
       'sınırı. x2: %10 hasar boosterı %20 verir.', hi=10.0, limit=100.0),
    # ---------------------------------------------------------------- dünya
    _c('box_abundance', 'Bonus kutusu bolluğu', 'world', 'Haritalardaki bonus kutusu sayısı (etkinlik kutuları dahil).',
       apply_mode='harita', hi=10.0, limit=100.0),
    _c('box_respawn', 'Kutuların yeniden çıkma süresi', 'world', 'Toplanan kutunun yerine yenisinin gelme süresi. '
       'Düşük değer: daha çabuk.', lo=0.01, hi=5.0, limit=100.0),
    _c('npc_count', 'Uzaylı sayısı', 'world', 'Haritalardaki uzaylı sayısı (patronlar dahil; kapı ve mod dalgaları hariç).',
       apply_mode='harita', hi=5.0, limit=50.0),
    _c('npc_respawn', 'Uzaylıların yeniden doğma süresi', 'world', 'Ölen uzaylının yerine yenisinin gelme süresi. '
       'Düşük değer: daha çabuk.', lo=0.01, hi=5.0, limit=100.0),
    _c('ore_abundance', 'Cevher bolluğu', 'world', 'Haritalardaki toplanabilir cevher (Prometium, Endurium, Terbium …) sayısı.',
       apply_mode='harita', hi=10.0, limit=50.0),
    _c('ore_respawn', 'Cevherlerin yeniden çıkma süresi', 'world', 'Toplanan cevherin yerine yenisinin gelme süresi. Düşük '
       'değer: daha çabuk.', lo=0.01, hi=5.0, limit=100.0),
    _n('max_quests', 'Aynı anda alınabilen görev', 'world', 'Görev penceresinde aynı anda sürdürebileceğin görev sayısı (oyunun '
       'değeri 5). Dolunca yeni görev alınamaz; biri bitince ya da iptal edilince yer açılır. Düşürülürse süren görevler iptal '
       'edilmez.', lo=1, hi=10, default=5, unit='görev', limit=100),
    _b('kampanya', 'Başlangıç kampanyası', 'world', 'Görev penceresinde "Level N" başlangıç görevleri hep görünür. Kapalıyken '
       'yalnız yeni kayıtta seçildiyse ilk ay görünür; süren görev her durumda bitirilebilir.'),
    _b('jump_deviation', "Atlama CPU'su ara sıra sapar", 'world', "Atlama CPU'su küçük bir olasılıkla (%2) seni Cubikon "
       'Mezarlığına götürür (oyundaki gibi). Kapatılırsa hep seçtiğin haritaya.', default=True),
    _b('pack_limit', 'Benzersiz paketler bir kez', 'world', "Mağazada içinde gemi, gemi tasarımı, formasyon, P.E.T. ya da tekil "
       'dron olan paketler (Defcom-Raven, Stellar, Dusklight …) oyundaki gibi bir kez alınır, sonra listeden kalkar. Kapatılırsa '
       'tekrar alınabilir (sahip olduğun içerik atlanır).', default=True),
    _b('portal_hangar', 'Portallarda hangar', 'world', "Portalların güvenli bölgesinde de hangara girip donanım değiştirebilirsin "
       '(kolaylık; gerçek oyunda yalnız istasyonda). Kapatılırsa yalnız istasyonda.', default=True),
    _b('clan_cooldown', 'Klan 48 saat kuralları', 'world', 'Klandan ayrılınca 48 saat yeni klan kurulamaz ya da klana katılınamaz; klan '
       'adı/etiketi iki değişim arası 48 saat bekler. Kapalıyken bekleme yok.', default=True),
    # ---------------------------------------------------------------- kapılar ve modlar
    _c('gate_part', 'Kapı parçası şansı', 'kapi', 'Galaksi Kapısı üreticisinde bir enerjiyle kapı parçası çıkma olasılığı '
       '(oyunun değeri %13; pencerenin olasılık listesi de değişir).', lo=0.1, hi=7.0, limit=1000.0),
    _n('duplicate_to_missing', 'Kopya parçanın eksiğe dönme şansı', 'kapi', 'Elinde olan bir kapı parçası çıkınca onun yerine eksik bir '
       'parça gelme olasılığı (oyunun değeri %50). %100: hiç kopya parça çıkmaz (kapı kurulana dek).', lo=0, hi=100,
       default=50, unit='%'),
    _c('gate_energy', 'Kapı enerjisi miktarı', 'kapi', 'Bonus kutularından çıkan ücretsiz Galaksi Kapısı enerjisinin miktarı '
       '(5-2 tüccarındaki Palladium takası ve paketler değişmez).', hi=20.0),
    _c('gate_price', 'Kapı fiyatları', 'kapi', 'Galaksi Kapısı üreticisinde enerjinin ve kapıda ek canların uridyum fiyatı. 0: '
       'bedava.', hi=5.0, limit=300.0),
    _c('gate_lives', 'Kapılardaki can sayısı', 'kapi', 'Galaksi Kapılarında ve etkinlik kapılarında (Plutus, Quarantine …) kapı '
       'hazırlanınca verilen can (oyunun değeri çoğu kapıda 5).', lo=0.2, hi=10.0, limit=1000.0),
    _b('infinite_lives', 'Kapılarda can harcanmaz', 'kapi', 'Galaksi Kapısında ve etkinlik kapılarında yok edilince can eksilmez: '
       'kapı hiç kaybolmaz.'),
    _c('wave_aliens', 'Dalgalardaki uzaylı sayısı', 'kapi', 'Galaksi Kapılarının, etkinlik kapılarının ve modların (Astral, EBL, '
       'Voyagers, Trinity, Echoes) dalgalarındaki uzaylı sayısı. Koruyan patronlar bir tane kalır.', lo=0.1, hi=5.0, limit=20.0),
    _c('wave_wait', 'Dalgalar arası bekleme', 'kapi', 'Kapı ve mod dalgalarının başlangıç, alt dalga arası ve mola süreleri '
       '(Galaksi Kapısında giriş 6, mola 30 sn). 0: bekleme yok.', hi=5.0, limit=100.0),
    _b('no_entry_limit', 'Kapı ve mod giriş sınırları kapalı', 'kapi', 'Etkinlik kapılarının günlük, yıllık ve tek seferlik '
       'giriş sınırları ve bekleme süreleri, Voyagers ve Trinity\'nin ücretsiz giriş hakları tükenmez.'),
    _n('gate_bonus_count', 'Bonuslu Galaksi Kapısı sayısı', 'kapi', 'Kapı penceresinde aynı anda süreli bonus ödülü olan kapı '
       'sayısı. Kapılar ve ödülleri her dönemin başında rastgele seçilir; kapıyı dönem bitmeden tamamlayınca (Dispatch\'in kapı '
       'gönderimi dahil) bonus bir kez verilir. 0: bonus yok.', lo=0, hi=11, default=3, unit='kapı'),
    _c('gate_bonus_multiplier', 'Kapı bonusu miktarı', 'kapi', 'Kapı bonusunun miktarı (onur, uridyum, cephane, log diski, anahtar); '
       'lazer ve tasarım gibi tek eşyalar bir tane kalır.', lo=0.1, hi=20.0),
    _n('gate_bonus_hours', 'Kapı bonusu dönemi', 'kapi', 'Bonuslu kapıların değiştiği aralık (gece yarısına hizalı; 24: her gün). '
       'Değiştirilince seçim hemen yenilenir.', lo=1, hi=168, default=24, unit='saat', limit=8760),
    # ---------------------------------------------------------------- ekonomi
    _c('shop_price', 'Mağaza fiyatları', 'economy', 'Mağazada kredi ve uridyumla satılan her şeyin fiyatı.', lo=0.0,
       hi=5.0, limit=1000.0),
    _b('event_looks_in_shop', 'Etkinlik görünümleri mağazada', 'economy', "Etkinliklerin gemi, dron ve P.E.T. "
       "tasarımları (Galactic Strife'ın Arios ve Neikos'u, Trial of Terrors'un Dusklight'ı, geçmiş sezonların tasarımları …) mağazada "
       'satılır. Kapatılırsa mağazada görünmez ve satılmazlar, yalnız kendi etkinliklerinde kazanılırlar: Battle Pass anahtar '
       'değişimi, etkinlik ve ganimet kutuları, GG hafta sonu kapıları, Season Pass. Mağazanın kendi tasarımları hep satılır.',
       default=True),
    _c('service_price', 'Hizmet ücretleri', 'economy', "P.E.T. yuvaları, tamiri ve yakıtı; Skylab yükseltmeleri, anında bitirme, "
       'hızlı taşıma ve robotlar; gemi ışınlama. 0: bedava.', hi=5.0, limit=1000.0),
    _c('repair_cost', 'Ölüm sonrası tamir ücreti', 'economy', 'Portalda ve bulunduğun yerde tamirin uridyum bedeli.',
       lo=0.0, hi=5.0, limit=1000.0),
    _c('ore_price', 'Cevher satış fiyatı', 'economy', 'Rafineride sattığın cevherlerin kredi ve uridyum karşılığı (pencerede de '
       'görünür).', hi=10.0, limit=10000.0),
    _c('kargo', 'Kargo kapasitesi', 'economy', "Geminin kargo alanı (Logistics, kargo CPU'su ve P.E.T. protokolüyle birlikte).",
       lo=0.5, hi=10.0, limit=1000.0),
    _b('infinite_cargo', 'Sonsuz kargo', 'economy', 'Kargo dolmaz: bütün kutular ve cevherler "kargo dolu" uyarısı almadan her zaman toplanır.'),
    _b('infinite_pet_range', 'Sonsuz P.E.T. bulucu menzili', 'economy', "P.E.T.'in düşman ve kaynak bulucu dişlileri menzil sınırı olmadan "
       'haritadaki en yakın hedefi gösterir.'),
    _b('assembly_free', 'Ücretsiz Assembly', 'economy', 'Assembly ve Upgrade/Disassembly sekmelerinde malzeme harcanmaz; istemci '
       'bütün malzemeleri yeterli gösterir. Üretim ve bekleme süreleri ile günlük kullanım sınırları aynı kalır.'),
    _b('legacy_upgrade', 'Eski yükseltme sistemi', 'economy', "Eşya yükseltmeleri 2018'deki gibi yalnız uridyumla: Assembly'nin "
       "Upgrade sekmesinde ABR, Indoctrine Oil, Diametrion gibi malzemeler istenmez. Bedel eski Item Upgrading'in %100 başarılı "
       "bedeli (seviye 2'ye 3.905 U., her seviye +435; 16'ya toplam 104.250 U.). Oyun açıkken de değişir."),
    _c('legacy_upgrade_price', 'Eski yükseltme fiyatları', 'economy', 'Eski sistemdeki yükseltmelerin uridyum bedeli (Upgrade '
       'Hour indirimi de geçerli). 0: bedava.',
       lo=0.0, hi=5.0, limit=1000.0, condition='legacy_upgrade'),
    _c('pet_fuel', 'P.E.T. yakıt tüketimi', 'economy', "P.E.T.'in dakikalık yakıt tüketimi. 0: yakıt harcamaz.", lo=0.0, hi=5.0,
       limit=100.0),
    _c('skylab_uretim', 'Skylab üretimi', 'economy', 'Skylab toplayıcılarının ve rafinerilerinin saatlik üretimi.', hi=20.0),
    _c('skylab_storage', 'Skylab depo kapasitesi', 'economy', 'Skylab deposunun her kaynak için kapasitesi.', hi=20.0,
       limit=1000.0),
    # ---------------------------------------------------------------- süreler
    _c('cooldown', 'Üretim ve bekleme süreleri', 'sure', 'Assembly üretimi, Skylab yükseltmeleri ve taşıma, Dispatch gönderimleri, '
       'eşya yükseltmeleri. Düşük değer: daha çabuk (yeni başlayanlara uygulanır).', lo=0.0, hi=5.0, limit=100.0),
    _c('skill_cooldown', 'Yetenek ve eşya beklemeleri', 'sure', "Gemi yetenekleri, CPU'lar, mayınlar, Smart Bomb, Insta-Shield, "
       'teknoloji eşyaları ve özel roketlerin bekleme süresi.', lo=0.05, hi=5.0, limit=100.0),
    _c('booster_sure', 'Booster süresi', 'sure', 'Boosterların etkin kalma süresi (yeni etkinleştirilenlere uygulanır).', lo=0.1,
       hi=10.0, limit=1000.0),
    _b('no_level_limit', 'Seviye kısıtları kapalı', 'sure', "Portalların ve atlama CPU'sunun seviye şartı yok: her haritaya "
       'girebilirsin.'),
    _b('session_always_open', 'Seanslı etkinlikler hep açık', 'sure', 'Saatle açılan etkinlikler (Vortex of Greed, Treacherous Domain, '
       'Mimesis Mutiny) etkinlik süresince her an açık: portal hep açık, seans/savaş/sefer girince başlar. Etkinlik uzaylıları '
       '(Curcubitor, Agatus, Lanatum, Chaos Protegit) da oyundaki saat pencerelerinin dışında doğar.'),
    # ---------------------------------------------------------------- müzayede
    dict(anahtar='auction_rivals', ad='Sanal rakipler', grup='auction', tur='seviye', default=0,
         options=list(RIVAL_LEVELS), colors=['', 'ok', 'ok', 'info', 'err'], apply_mode='anında',
         option_description=['Rakip yok: teklifleri yalnız sen verirsin.',
                           'Arada bir küçük teklifler verirler; seni hiç geçmezler, teklif verdiğin lot senin.',
                           'Daha sık ve biraz daha yüksek teklifler; seni yine geçmezler.',
                           'Geçtiğinde bir süre sonra karşılık verirler. Bütçelerini aşarsan lot senin; kaybedersen kredin geri gelir.',
                           'Çok sık, yüksek bütçeli ve hızlı karşılık verirler. Kaptırmamak için iyi teklif ver.'],
         aciklama='Müzayedede sana rakip olan sanal teklifçiler. Çekingen ve Ilımlı: biraz teklif verirler ama seni hiç geçmezler, '
                  'teklif verdiğin lot hep senin olur. Rekabetçi ve Agresif: geçtiğinde karşılık verirler; bütçelerini aşmadıkça '
                  'lotu kaybedebilirsin (kredin geri gelir). Dünyada bot paketi açıkken kapalıdır: teklifleri botlar verir.'),
    # ---------------------------------------------------------------- arayüz
    _b('dark', 'Karanlık haritalar (el feneri)', 'ui', 'Trial of Terrors kapısının haritalarında ekran kararır, yalnız '
       'geminin baktığı yön aydınlıktır (istemcinin el feneri etkisi). Kapatılırsa haritalar aydınlık.', apply_mode='harita',
       default=True),
    _b('cinematic', 'Sinematik patron girişleri', 'ui', 'Etkinlik patronu doğunca ve Galaksi Kapısının son dalgasında kamera '
       'birkaç saniye patrona döner (kontroller o sürede kilitli), sonra gemine geri gelir.', default=True),
    _b('hints', 'Yeni başlayan ipuçları', 'ui', 'Bir şey ilk kez olunca (kargo doldu, cephane bitti, başka firmanın haritası) '
       've seviye atladıkça yeni özellikleri anlatan ipucu pencereleri, süren etkinliğin açıklaması. Her biri bir kez; kapattığın '
       'ipuçları açılmaz, ipucu arşivinden yeniden okunabilir.', default=True),
    _b('kill_streak', 'Seri öldürme duyuruları', 'ui', 'Kısa aralıklarla art arda uzaylı yok edince ekranda "Triple Kill", '
       '"Unstoppable", "Godlike", "Like a Boss" duyurusu ve sesi (3, 6, 10, 15 öldürme; aralık en çok 10 sn).'),
    _b('no_ads', 'Açılış pencerelerini gösterme', 'ui', 'Girişte kendiliğinden açılan günlük bonus, ipucu ve Season Pass '
       'pencereleri gönderilmez (menülerden açılabilirler).', apply_mode='giriş'),
    # ---------------------------------------------------------------- yönetici (yonetici_modu.py)
    _b('admin_mode', 'Yönetici modu', 'manager', 'Oyunda yönetici olursun: adının önünde yönetici rozeti (sarı A), rütbe '
       'sistemine, Şeref Salonu sıralamalarına ve şirketteki sıraya girmezsin. Botlar seni yönetici olarak tanır: sana saldırmaz, '
       'sohbetteki uyarılarına uyar, seni görünce tepki verir. Arkadaş sunucusunda yalnız sunucunun oyuncusu için.', apply_mode='giriş'),
    dict(anahtar='admin_ship', ad='Yönetici gemisi', grup='manager', tur='seviye', default=0,
         options=['Kendi gemin', 'UFO', 'Polis', 'G-Admincloak', 'Goliath Admin'], colors=['', 'info', 'info', 'info', 'info'],
         apply_mode='giriş',
         option_description=['Yönetici modunda da kendi geminle görünürsün.',
                           'Yönetici gemisi (ship_admin): oyundaki UFO uzaylısıyla aynı model.',
                           'Polis gemisi (ship_police).',
                           'Yöneticinin gizlenme gemisi (ship_g-admincloak).',
                           'Goliath\'ın yönetici tasarımı (admincloak).'],
         aciklama='Yönetici modundayken gemin bu görünümde; değerleri (can, hız, donanım) kendi geminin.'),
    _b('admin_spectator', 'İzleyici (dokunulmaz)', 'manager', 'Yönetici modundayken uzaylılar ve botlar sana saldırmaz, hasar '
       'almazsın; haritaları rahatça gezip botları izleyebilirsin.', apply_mode='anında'),
    _b('admin_chat', 'Sohbette yönetici', 'manager', 'Yönetici modundayken sohbet mesajların yönetici olarak (oyunun yönetici '
       'rengiyle) görünür.', apply_mode='giriş', default=True),
    _b('gm_console', 'GM konsolu', 'manager', 'Oyunun gizli yönetici penceresi: oyunda Ctrl, ardından Shift, ardından Z. Haritaya '
       'ışınlanma, uzaylı ve kutu doğurma, eşya ve paket verme, görevleri bitirme, kapı kurma, bekleme sürelerini sıfırlama, '
       'dokunulmazlık. Açıkken adının önünde yönetici rozeti görünür (istemci yöneticiyi rütbe 6000 ile tanıyor).', apply_mode='giriş'),
    # ---------------------------------------------------------------- geliştirici
    _b('nearby_npc', 'Yakında uzaylı doğur', 'developer', 'Test kolaylığı: ilk dört uzaylı türünden birer tane geminin hemen '
       'yanında doğar.', apply_mode='harita'),
    _b('control', 'Canlı test kontrol kanalı', 'developer', 'Geliştirici aracı (control.py, 127.0.0.1:8099): mesaj izi ve '
       'istek enjeksiyonu.', apply_mode='başlatma'),
]

# alt ayarlar: üst çarpan -> kaynakları [(kaynak, ad, açıklama)]; oyundaki karşılığı carpan(üst, kaynak) çağıran yerler
_NPC = ('npc', 'Uzaylılar', 'Uzaylı (NPC) öldürünce.')
_BOX = ('kutu', 'Kutular ve sandıklar', 'Bonus kutuları, etkinlik kutuları ve ganimet sandıkları.')
_QUEST = ('gorev', 'Görevler', 'Görev penceresinin görevleri ve Acil Görevler.')
_GATE = ('kapi', 'Kapılar', "Galaksi Kapıları (Dispatch'in kapı gönderimi dahil) ve etkinlik kapıları (Plutus, Quarantine …) "
         'tamamlanınca.')
_MOD = ('mod', 'Modlar ve etkinlikler', 'Astral, EBL, Galaxy Trek, Mimesis, Apotheosis, Voyagers, Trinity, Deep Space Echoes, '
        'Labirent, dünya patronları, Battle Station, Dispatch ve etkinliklerin ödülleri.')
_EXTRA = ('ek', 'Uzaylıların ek ödülleri', 'Uzaylı öldürünce gelen Palladium, etkinlik paraları ve kaynaklar.')
_PLACE = (('harita', 'Haritalarda', 'Haritalarda dolaşan uzaylılar ve patronlar.'),
        ('dalga', 'Kapı ve mod dalgalarında', 'Galaksi Kapılarının, etkinlik kapılarının ve modların (Astral, EBL, Voyagers, '
         'Trinity, Mimesis …) dalgalarındaki uzaylılar.'))
_MONEY = (_NPC, _BOX, _QUEST, _GATE, _MOD)
SUBS = {
    'kredi': _MONEY, 'uridyum': _MONEY, 'ep': _MONEY, 'onur': _MONEY,
    'collecting': (_BOX, ('kargo', 'Uzaylıların kargo kutuları', 'Uzaylının bıraktığı kargo kutusundaki cevher.'),
                ('ore', 'Cevher toplama', 'Haritadaki cevherlerden toplanan miktar.'), _EXTRA),
    'mode_reward': (_QUEST, _GATE, _MOD),
    'drop': (('booster', 'Booster', 'Patron ve Uber uzaylılardan booster düşmesi.'), _EXTRA,
              ('etkinlik', 'Etkinlik düşmeleri', 'Etkinlik ve etkinlik kapısı uzaylılarının kutuları, Chromin kutuları, Hitac '
               'piyangosunun harfleri.'),
              ('kapi', 'Kapılar', 'Galaksi Kapılarının ve etkinlik kapılarının şanslı ödülleri (tasarımlar, LF-4 …).'),
              ('mod', 'Modlar', "Astral'ın kurtarma çekirdeği ve anahtarları, EBL'nin ek ödülü.")),
    'npc_damage': _PLACE, 'npc_can': _PLACE,
    'player_damage': (('pve', 'Uzaylılara (PvE)', 'Uzaylılara (NPC) verdiğin hasar.'),
                     ('pvp', 'Oyunculara (PvP)', 'Başka oyunculara lazer ve roketlerle verdiğin hasar.'),
                     ('bot', 'Botlara', 'Botlara verdiğin hasar.')),
    'box_abundance': (('bonus', 'Bonus kutuları', 'Haritalara dağılan bonus kutuları.'),
                    ('booty', 'Ganimet sandıkları', 'Anahtarla açılan ganimet sandıkları.'),
                    ('etkinlik', 'Etkinlik kutuları', 'Etkinliklerin haritalara getirdiği kutular.')),
    'npc_count': (('harita', 'Haritaların uzaylıları', 'Haritanın kendi uzaylıları ve patronları.'),
                 ('etkinlik', 'Etkinlik uzaylıları', 'Etkinliklerin haritalara getirdiği uzaylılar.')),
    'shop_price': (('kredi', 'Kredi ile satılanlar', 'Mağazada kredi fiyatlı her şey.'),
                     ('uridyum', 'Uridyum ile satılanlar', 'Mağazada uridyum fiyatlı her şey.')),
    'service_price': (('pet', 'P.E.T.', "P.E.T.'in yuvaları, tamiri ve yakıtı."),
                     ('skylab', 'Skylab', 'Yükseltmeler, anında bitirme, hızlı taşıma ve robotlar.'),
                     ('warp', 'Gemi ışınlama', 'Başka bir gemini hangara gitmeden bulunduğun yere getirme.')),
    'cooldown': (('assembly', 'Assembly üretimi', "Assembly'de eşya üretimi."),
                ('skylab', 'Skylab', 'Modül yükseltmeleri ve taşıma.'),
                ('dispatch', 'Dispatch', 'Gönderimler ve kapı gönderimleri.'),
                ('upgrade', 'Eşya yükseltmeleri', 'Lazerlerin, jeneratörlerin, dronların ve modüllerin seviye yükseltmeleri.')),
    'skill_cooldown': (('yetenek', 'Gemi yetenekleri', 'Geminin kendi yetenekleri.'),
                        ('esya', "Savaş eşyaları ve CPU'lar", "Mayınlar, Smart Bomb, Insta-Shield, EMP, özel roketler ve CPU'lar."),
                        ('technology', 'Teknoloji eşyaları', 'Energy Leech, Chain Impulse, Battle Repair Bot, Speed Burst …'),
                        ('particle', 'Parçacık topları ve sürücü', 'Parçacık silahları ve Singularity Drive.')),
}
SCHEMA = [x for s in SCHEMA for x in [s] + [dict(s, anahtar='%s_%s' % (s['anahtar'], k), ad=name, aciklama=description, default=1.0,
                                                 parent=s['anahtar'], kaynak=k) for k, name, description in SUBS.get(s['anahtar'], ())]]
SUB = {(s['parent'], s['kaynak']): s['anahtar'] for s in SCHEMA if s.get('parent')}
BY_KEY = {s['anahtar']: s for s in SCHEMA}
DEFAULTS = {s['anahtar']: s['default'] for s in SCHEMA}
EVENT_STATES = ('on', 'off')         # yoksa takvime göre

# hazır ayarlar (panelin "Hazır ayarlar" listesi): yalnız değişen anahtarlar, ötekiler varsayılan
PRESETS = {
    'default': {'ad': 'Varsayılan', 'aciklama': 'Oyunun kendi değerleri.', 'values': {}},
    'casual': {'ad': 'Rahat', 'aciklama': 'Daha az hasar alırsın, ödüller ve kutular bol.',
              'values': {'npc_damage': 0.5, 'kredi': 2.0, 'uridyum': 2.0, 'ep': 2.0, 'onur': 2.0, 'collecting': 2.0, 'drop': 2.0,
                           'box_abundance': 2.0, 'box_respawn': 0.5, 'mode_reward': 2.0, 'drone_xp': 2.0, 'pet_ep': 2.0,
                           'shield_regen': 2.0}},
    'fast': {'ad': 'Hızlı ilerleme', 'aciklama': 'Ödüller beş kat, uzaylılar kalabalık ve çabuk doğar.',
              'values': {'kredi': 5.0, 'uridyum': 5.0, 'ep': 5.0, 'onur': 5.0, 'collecting': 5.0, 'drop': 3.0, 'box_abundance': 3.0,
                           'box_respawn': 0.3, 'npc_count': 1.5, 'npc_respawn': 0.3, 'shop_price': 0.5, 'mode_reward': 5.0,
                           'drone_xp': 5.0, 'pet_ep': 5.0, 'season_points': 3.0, 'skylab_uretim': 3.0, 'ore_abundance': 2.0,
                           'wave_wait': 0.5}},
    'hard': {'ad': 'Zorlu', 'aciklama': 'Uzaylılar daha sert vurur ve dayanıklıdır, ödüller az, rakipler agresif.',
              'values': {'npc_damage': 2.0, 'npc_can': 1.5, 'kredi': 0.75, 'uridyum': 0.75, 'box_abundance': 0.5,
                           'repair_cost': 2.0, 'auction_rivals': 4, 'npc_hit_chance': 1.25, 'npc_aggression': 1,
                           'shield_regen': 0.5}},
    'creative': {'ad': 'Yaratıcı', 'aciklama': 'Gemin yok edilmez, cephane bitmez, mağaza ve hizmetler bedava, bekleme yok.',
                 'values': {'immune_until': True, 'infinite_ammo': True, 'infinite_technology': True, 'shop_price': 0.0, 'service_price': 0.0,
                              'gate_price': 0.0, 'repair_cost': 0.0, 'cooldown': 0.0, 'no_level_limit': True,
                              'infinite_lives': True, 'no_entry_limit': True, 'pet_fuel': 0.0, 'assembly_free': True,
                              'infinite_cargo': True, 'infinite_pet_range': True}},
}

_lock = threading.Lock()
_state = {'route': None, 'mtime': None, 'read_at': 0.0, 'd': {}}


def clean(raw):
    """Dosyadan gelen sözlük -> geçerli değerler (bilinmeyen anahtar yok, sayılar sınırda, türler doğru)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, v in raw.items():
        s = BY_KEY.get(key)
        if s is None:
            continue
        try:
            if s['tur'] == 'carpan':
                v = float(v)
                if v != v:                                # NaN
                    continue
                out[key] = min(s['cap'], max(s['min'], v))
            elif s['tur'] == 'bool':
                out[key] = bool(v)
            elif s['tur'] == 'seviye':
                out[key] = min(len(s['options']) - 1, max(0, int(v)))
            elif s['tur'] == 'sayi':
                v = float(v)
                if v != v:                                # NaN
                    continue
                out[key] = int(round(min(s['cap'], max(s['min'], v))))       # sonsuz da sınıra
        except (TypeError, ValueError):
            continue
    ev = raw.get('events')
    if isinstance(ev, dict):
        out['events'] = {str(k): v for k, v in ev.items() if v in EVENT_STATES}
    return out


def read(path):
    """Dosyadaki ayarlar (temizlenmiş); dosya yoksa ya da bozuksa {}."""
    try:
        with open(path, encoding='utf8') as fh:
            return clean(json.load(fh))
    except (OSError, ValueError):
        return {}


def write(path, values):
    """Ayarları atomik yaz (panel). Varsayılana eşit değerler de yazılır: dosya kullanıcının seçimidir."""
    d = clean(values)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf8', newline='\n') as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return d


def configure(argv=None, path=None):
    """Ayar dosyasını bağla: path, yoksa --settings=<yol> seçeneği, yoksa save/ayarlar.json. path=False: bağı çöz (varsayılanlar)."""
    if path is None:
        argv = sys.argv if argv is None else argv
        path = next((a.split('=', 1)[1] for a in argv if a.startswith('--settings=')), DEFAULT_PATH)
    with _lock:
        _state.update(route=path or None, mtime=None, read_at=0.0, d={})
    return path


def _current():
    with _lock:
        if not _state['route']:
            return _state['d']
        now = time.monotonic()
        if _state['mtime'] is not None and now - _state['read_at'] < REFRESH_SEC:
            return _state['d']
        _state['read_at'] = now
        try:
            m = os.stat(_state['route']).st_mtime_ns
        except OSError:
            m = 0
        if m != _state['mtime']:
            _state['mtime'] = m
            _state['d'] = read(_state['route']) if m else {}
        return _state['d']


def get(key):
    return _current().get(key, DEFAULTS[key])


def multiplier(key, source=None):
    """Çarpan; kaynak verilirse alt ayarıyla çarpılır (carpan('uridyum', 'npc') = uridyum x uridyum_npc). Kaynağın alt ayarı
    yoksa yalnız üst."""
    sub = SUB.get((key, source))
    return float(get(key)) * (float(get(sub)) if sub else 1.0)


def version():
    """Ayar dosyasının sürümü (değiştirilme anı; bağlı değilse None): oyun açıkken değişen ayarı fark etmek için (dunya.settings_tick)."""
    _current()
    with _lock:
        return _state['mtime']


def price(key, n, source=None):
    """Fiyatı çarpanla ölçekle (hizmet ücretleri …): tam sayı, en az 0, 32 bitlik alana sığar."""
    m = multiplier(key, source)
    return n if m == 1.0 or not n else min(I32, max(0, int(round(n * m))))


def count(key, n, source=None):
    """Sayıyı (uzaylı, kutu adedi) çarpanla ölçekle: yuvarlanır, pozitif sayı en az 1 kalır (patron kaybolmaz); çarpan 0 ise 0."""
    m = multiplier(key, source)
    if m == 1.0 or not n or n < 0:
        return n
    return 0 if m <= 0 else max(1, int(round(n * m)))


def amount(key, n, source=None):
    """Miktarı (ödül, toplanan eşya) çarpanla ölçekle: kesir olasılıkla yuvarlanır (x1,5 ile 1 -> yarı yarıya 1 ya da 2),
    beklenen değer tam çarpan kadar."""
    m = multiplier(key, source)
    if m == 1.0 or not n or n < 0:
        return n
    v = n * m
    whole = int(v)
    return whole + (1 if random.random() < v - whole else 0)


def duration(sec, source=None):
    """Üretim ve bekleme süresi (panelin 'bekleme' çarpanı; kaynak: assembly, skylab, dispatch, yukseltme) -> saniye (en az 1)."""
    m = multiplier('cooldown', source)
    return sec if m == 1.0 else max(1, int(round(sec * m)))


def chance(key, p, source=None):
    """Olasılığı çarpanla ölçekle (0..1)."""
    m = multiplier(key, source)
    return p if m == 1.0 else min(1.0, max(0.0, p * m))


def event_state(key):
    """Oyuncunun etkinlik seçimi: 'acik', 'kapali' ya da None (takvime göre)."""
    return (_current().get('events') or {}).get(key)


def full_name(s, name=lambda x: x):
    """Ayarın özetlerdeki adı: alt ayar üstüyle birlikte ('Uridyum kazancı › Uzaylılar'); ad: çeviri (panel)."""
    return name(BY_KEY[s['parent']]['ad']) + ' › ' + name(s['ad']) if s.get('parent') else name(s['ad'])


def summary(values=None):
    """Varsayılandan farklı ayarlar [(ad, değer metni)] (panelin özet çipleri)."""
    d = _current() if values is None else clean(values)
    out = []
    for s in SCHEMA:
        v = d.get(s['anahtar'], s['default'])
        if v == s['default']:
            continue
        if s['tur'] == 'carpan':
            out.append((full_name(s), 'x%g' % v))
        elif s['tur'] == 'bool':
            out.append((s['ad'], 'açık' if v else 'kapalı'))
        elif s['tur'] == 'sayi':
            out.append((s['ad'], ('%d %s' % (v, s.get('unit', ''))).strip()))
        else:
            out.append((s['ad'], s['options'][v]))
    return out
