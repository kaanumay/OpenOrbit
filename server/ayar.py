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
Oyun sunucusu configure() ile dosyayı bağlar (game.main, --ayarlar=<yol> seçeneği ya da save/ayarlar.json). Bağlanmamışken
(testler, araçlar) bütün ayarlar varsayılandır: kullanıcının ayarları testleri etkilemez.
"""
import json, os, random, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
VARSAYILAN_YOL = os.path.join(HERE, 'save', 'ayarlar.json')
YENILE_SN = 1.0

GRUPLAR = (('gemi', 'Gemin'), ('savas', 'Savaş ve uzaylılar'), ('odul', 'Ödüller'), ('ilerleme', 'İlerleme'), ('dunya', 'Dünya'),
           ('kapi', 'Kapılar ve modlar'), ('ekonomi', 'Ekonomi'), ('sure', 'Süreler'), ('muzayede', 'Müzayede'), ('arayuz', 'Arayüz'),
           ('yonetici', 'Yönetici'), ('gelistirici', 'Geliştirici'))
RAKIP_SEVIYELERI = ('Kapalı', 'Çekingen', 'Ilımlı', 'Rekabetçi', 'Agresif')
UST_SINIR = 10000.0             # çarpanların elle yazılabilen en büyük değeri ('sinir' verilmemişse)
I32 = 2 ** 31 - 1               # istemciye 32 bitlik alanla giden değerlerin üstü (protokol taşırır: can, kalkan, fiyat)


def _c(key, ad, grup, aciklama, uygulama='anında', lo=0.0, hi=10.0, adim=0.1, varsayilan=1.0, sinir=UST_SINIR):
    """Çarpan: panelde sürgü (lo..hi, önerilen) ve sayı kutusu (lo..sinir)."""
    return dict(anahtar=key, ad=ad, grup=grup, tur='carpan', varsayilan=varsayilan, min=lo, max=hi, sinir=max(hi, sinir), adim=adim,
                aciklama=aciklama, uygulama=uygulama)


def _b(key, ad, grup, aciklama, uygulama='anında', varsayilan=False):
    return dict(anahtar=key, ad=ad, grup=grup, tur='bool', varsayilan=varsayilan, aciklama=aciklama, uygulama=uygulama)


def _n(key, ad, grup, aciklama, uygulama='anında', lo=0, hi=10, varsayilan=1, birim='', sinir=None):
    """Tam sayı (adet, saat): panelde sayı kutusu; hi önerilen üst, sinir elle yazılabilen en büyük (yoksa hi)."""
    return dict(anahtar=key, ad=ad, grup=grup, tur='sayi', varsayilan=varsayilan, min=lo, max=hi, sinir=max(hi, sinir or hi),
                birim=birim, aciklama=aciklama, uygulama=uygulama)


SCHEMA = [
    # ---------------------------------------------------------------- gemin
    _c('gemi_can', 'Geminin canı', 'gemi', 'Geminin azami canı (gövde): formasyon, booster ve laboratuvar bonuslarıyla birlikte. '
       'Oyun açıkken de değişir.', lo=0.1, sinir=1000.0),
    _c('gemi_kalkan', 'Geminin kalkanı', 'gemi', 'Geminin azami kalkanı (gemideki ve dronlardaki kalkan jeneratörleri, bonuslarla '
       'birlikte). Oyun açıkken de değişir.', sinir=500.0),
    _c('gemi_hiz', 'Geminin hızı', 'gemi', 'Geminin uçuş hızı (hız jeneratörleri ve bonuslarla birlikte). Yavaşlatma ve Fortify '
       'gibi etkiler yine geçerli.', lo=0.25, hi=3.0, sinir=10.0),
    _c('kalkan_yenilenme', 'Kalkanın dolma hızı', 'gemi', 'Savaş dışında kalkanın kendiliğinden dolması (oyunun değeri saniyede '
       '%4). 0: kalkan kendiliğinden dolmaz.', sinir=100.0),
    _c('onarim_hizi', 'Onarım robotu hızı', 'gemi', 'Onarım robotunun (REP) gövdeyi onarma hızı.', lo=0.1, sinir=1000.0),
    _c('oyuncu_isabet', 'İsabet şansın', 'gemi', "Lazerlerinin, roketlerinin ve P.E.T.'inin isabet olasılığı (oyunun değeri %80, "
       'en çok %100). x1,25: her atış isabet eder.', lo=0.1, hi=2.0, sinir=100.0),
    _c('roket_bekleme', 'Roket bekleme süresi', 'gemi', 'Roketlerin ve roket fırlatıcısının bekleme ve dolma süresi. Düşük değer: '
       'daha sık atış.', lo=0.05, hi=5.0, sinir=100.0),
    _b('dokunulmaz', 'Dokunulmaz gemi', 'gemi', 'Uzaylıların atışları görünür ama gemin can ve kalkan kaybetmez.'),
    _b('sonsuz_cephane', 'Sonsuz cephane', 'gemi', 'Lazer cephanesi, roketler, fırlatıcı cephanesi ve mayınlar harcanmaz (en az '
       'bir tane olmalı).'),
    _b('sonsuz_teknoloji', 'Sonsuz teknoloji', 'gemi', 'Teknoloji eşyaları (Energy Leech, Battle Repair Bot, Speed Burst …) '
       'kullanılınca harcanmaz (en az bir tane olmalı). Bekleme süreleri yine geçerli.'),
    _b('kendi_mayin', 'Kendi mayınların sana zarar verir', 'gemi', 'Kendi bıraktığın mayının patlaması gemine de hasar verir '
       '(oyundaki gibi). Kapatılırsa yalnız uzaylılara.', varsayilan=True),
    _n('yerinde_can', 'Yerinde onarımda can', 'gemi', 'Gemi yok edildikten sonra bulunduğun yerde onarılınca gelen can (oyunun '
       'değeri %10; kalkan boş başlar).', lo=1, hi=100, varsayilan=10, birim='%'),
    _n('yerinde_koruma', 'Yerinde onarım sonrası koruma', 'gemi', 'Bulunduğun yerde onarıldıktan sonra hasar almadığın süre '
       '(oyunun değeri 10 sn). Ateş edince biter.', lo=0, hi=60, varsayilan=10, birim='sn', sinir=3600),
    # ---------------------------------------------------------------- savaş ve uzaylılar
    _c('npc_hasar', 'Uzaylıların verdiği hasar', 'savas', 'Uzaylıların (NPC) gemine, P.E.T.\'ine ve dost gemilere verdiği hasar. '
       '0: hiç hasar almazsın.', sinir=1000.0),
    _c('oyuncu_hasar', 'Verdiğin hasar', 'savas', 'Lazer, roket, fırlatıcı, mayın, Smart Bomb, top, P.E.T. ve yeteneklerle '
       'uzaylılara, oyunculara ve botlara verdiğin hasar.', lo=0.1, sinir=1000.0),
    _c('npc_can', 'Uzaylıların canı ve kalkanı', 'savas', 'Uzaylıların can ve kalkanı. Düşük değer uzaylıları çabuk '
       'öldürür.', uygulama='harita', lo=0.1, sinir=100.0),
    _c('npc_isabet', 'Uzaylıların isabet şansı', 'savas', 'Uzaylıların gemine ve P.E.T.\'ine isabet ettirme olasılığı (oyunun '
       'değeri %60, en çok %100). 0: hiç isabet etmezler.', hi=2.0, sinir=100.0),
    _c('npc_hiz', 'Uzaylıların hızı', 'savas', 'Uzaylıların uçuş hızı (hareketsiz olanlar kıpırdamaz).', lo=0.1, hi=3.0, sinir=10.0),
    dict(anahtar='npc_saldirganlik', ad='Uzaylıların saldırganlığı', grup='savas', tur='seviye', varsayilan=0,
         secenekler=['Türüne göre', 'Hepsi saldırgan', 'Hiçbiri saldırgan'], renkler=['', 'err', 'ok'], uygulama='anında',
         secenek_aciklama=['Oyundaki gibi: saldırgan türler seni görünce saldırır, ötekiler vurulunca karşılık verir.',
                           'Bütün uzaylılar seni fark edince kovalar ve saldırır.',
                           'Hiçbir uzaylı kendiliğinden saldırmaz; vurduğun uzaylı yine karşılık verir.'],
         aciklama='Uzaylıların seni kendiliğinden kovalayıp kovalamadığı (kapı ve mod dalgalarındakiler dahil).'),
    _c('npc_fark', 'Uzaylıların fark etme mesafesi', 'savas', 'Saldırgan uzaylıların seni fark edip kovalamaya başladığı uzaklık '
       '(oyunun değeri 1.000 birim).', lo=0.1, hi=3.0, sinir=20.0),
    _c('npc_menzil', 'Uzaylıların ateş menzili', 'savas', 'Uzaylıların sana lazer, roket ve bomba atabildiği uzaklık (oyunun '
       'değeri çoğunda 450, Kristallon türlerinde 550, hareketsizlerde 1.000 birim; dünya patronlarının saldırıları dahil).', lo=0.1, hi=3.0, sinir=20.0),
    _b('yavaslatan_atis', 'Yavaşlatan uzaylı atışları', 'savas', 'Barb, The Stinger, Saboteur ve Mindfire Behemoth gibi '
       'uzaylıların atışları gemini yavaşlatır. Kapatılırsa yalnız hasar verirler.', varsayilan=True),
    _c('radyasyon', 'Radyasyon hasarı', 'savas', 'Harita sınırının dışındaki radyasyonun gövdeye verdiği hasar. 0: radyasyon '
       'zarar vermez.', lo=0.0, hi=5.0, sinir=100.0),
    # ---------------------------------------------------------------- ödüller
    _c('kredi', 'Kredi kazancı', 'odul', 'Uzaylı, kutu, görev, kapı ve etkinliklerden kazanılan kredi (satış ve iadeler '
       'hariç).', hi=50.0, sinir=100000.0),
    _c('uridyum', 'Uridyum kazancı', 'odul', 'Uzaylı, kutu, görev, kapı ve etkinliklerden kazanılan uridyum.', hi=50.0,
       sinir=100000.0),
    _c('ep', 'Deneyim (EP) kazancı', 'odul', 'Kazanılan deneyim puanı: seviye atlama hızı.', hi=50.0, sinir=100000.0),
    _c('onur', 'Onur kazancı', 'odul', 'Kazanılan onur puanı.', hi=50.0, sinir=100000.0),
    _c('toplama', 'Toplanan eşya miktarı', 'odul', 'Kutulardaki cephane ve eşyalar, uzaylıların kargo kutularındaki ve '
       'madenden toplanan cevher, uzaylıların ek ödülleri (Palladium, etkinlik paraları …). Kutudan çıkan kredi ve uridyum '
       'kendi çarpanıyla.', hi=50.0),
    _c('mod_odul', 'Görev, kapı ve etkinlik eşya ödülleri', 'odul', 'Görevlerin, Galaksi Kapılarının, etkinlik kapılarının, '
       'modların (Astral, EBL, Mimesis, Galaxy Trek …), Acil Görevlerin ve Dispatch\'in verdiği cephane, kaynak, anahtar ve '
       'teknoloji eşyası miktarı. Gemi, lazer ve tasarım gibi tek eşyalar bir tane kalır; para ve EP kendi çarpanıyla.', hi=50.0),
    _c('dusme', 'Eşya düşme şansı', 'odul', 'Uzaylılardan booster, ekipman, kaynak ve etkinlik kutusu düşme olasılığı; '
       'Galaksi Kapısı şanslı ödülleri (en çok %100).', hi=20.0, sinir=1000.0),
    _b('x1_kargo', "X-1'de yüksek seviye kargo ve ödül azalması", 'odul', "X-1 haritalarında seviyen yükseldikçe uzaylıların kargo kutusu "
       'küçülür (seviye 7: %50, 10 ve üstü: hiç), kendi X-1 haritanda öldürme ödülü de azalır (seviye 15 ve üstü: hiç; oyundaki gibi). '
       'Kapatılırsa her seviyede tam kargo ve ödül.', varsayilan=True),
    _b('etiket', 'Uzaylı etiketleme', 'odul', 'Uzaylıya ilk ateş eden onu etiketler: ödülü, görev sayımı ve kargo kutusu onun (ya da '
       'grubunun) olur, başkası bitirse de. Etiket sahibi 15 saniye vurmazsa etiket düşer. Kapatılırsa ödül son vuranın.',
       varsayilan=True),
    _b('kargo_sahipligi', 'Kargo kutusu sahipliği', 'odul', "Uzaylının kargo kutusu yalnız sahibinindir; başkalarına mavi görünür "
       "(oyunun Ayarlar > Ekran'daki başkalarının kargo kutuları seçeneği açıksa). Aynı firmadan birinin kutusunu toplamak onur "
       'kaybettirir: o gün ilki 10, her seferinde iki katı. Kapatılırsa herkes toplar, ceza yok.', varsayilan=True),
    # ---------------------------------------------------------------- ilerleme
    _c('dron_puan', 'Dron deneyimi', 'ilerleme', 'Dronlarının uzaylı öldürünce kazandığı puan: dron seviye atlama hızı.',
       hi=50.0),
    _c('pet_ep', "P.E.T. deneyimi", 'ilerleme', "P.E.T.'in kazandığı deneyim (oyunun değeri kazandığın EP'nin %5'i): P.E.T. "
       'seviye atlama hızı.', hi=50.0),
    _c('sezon_puani', 'Season Pass puanı', 'ilerleme', 'Season Pass görevlerinden kazanılan puan: sezon seviyesi atlama hızı.',
       hi=50.0),
    _n('sezon_suresi', 'Season Pass süresi', 'ilerleme', 'Bir sezonun süresi. Sezon kaydın ilk girişinde 1. günden başlar, bitince '
       'alınmamış ödüller verilir ve sıradaki sezon başlar (gerçek oyunda ~3 ay). Değişiklik süren sezona da uygulanır.',
       lo=1, hi=180, varsayilan=90, birim='gün', sinir=3650),
    _n('savas_bileti_suresi', 'Battle Pass süresi', 'ilerleme', "Battle Pass'in süresi. Pass'li bir etkinlik açılınca kaydın pass'i "
       "1. günden başlar ve bu süre boyunca etkinlikle birlikte sürer (takvimdeki dönemi daha önce bitse de); aynı anda tek "
       "pass (gerçek oyunda ~2 hafta).", lo=1, hi=60, varsayilan=14, birim='gün', sinir=365),
    _c('booster_guc', 'Booster etkisi', 'ilerleme', 'Boosterların bonusu (hasar, can, kalkan, EP, onur …) ve türlerin üst '
       'sınırı. x2: %10 hasar boosterı %20 verir.', hi=10.0, sinir=100.0),
    # ---------------------------------------------------------------- dünya
    _c('kutu_bolluk', 'Bonus kutusu bolluğu', 'dunya', 'Haritalardaki bonus kutusu sayısı (etkinlik kutuları dahil).',
       uygulama='harita', hi=10.0, sinir=100.0),
    _c('kutu_yenilenme', 'Kutuların yeniden çıkma süresi', 'dunya', 'Toplanan kutunun yerine yenisinin gelme süresi. '
       'Düşük değer: daha çabuk.', lo=0.01, hi=5.0, sinir=100.0),
    _c('npc_sayi', 'Uzaylı sayısı', 'dunya', 'Haritalardaki uzaylı sayısı (patronlar dahil; kapı ve mod dalgaları hariç).',
       uygulama='harita', hi=5.0, sinir=50.0),
    _c('npc_yenilenme', 'Uzaylıların yeniden doğma süresi', 'dunya', 'Ölen uzaylının yerine yenisinin gelme süresi. '
       'Düşük değer: daha çabuk.', lo=0.01, hi=5.0, sinir=100.0),
    _c('maden_bolluk', 'Cevher bolluğu', 'dunya', 'Haritalardaki toplanabilir cevher (Prometium, Endurium, Terbium …) sayısı.',
       uygulama='harita', hi=10.0, sinir=50.0),
    _c('maden_yenilenme', 'Cevherlerin yeniden çıkma süresi', 'dunya', 'Toplanan cevherin yerine yenisinin gelme süresi. Düşük '
       'değer: daha çabuk.', lo=0.01, hi=5.0, sinir=100.0),
    _n('en_cok_gorev', 'Aynı anda alınabilen görev', 'dunya', 'Görev penceresinde aynı anda sürdürebileceğin görev sayısı (oyunun '
       'değeri 5). Dolunca yeni görev alınamaz; biri bitince ya da iptal edilince yer açılır. Düşürülürse süren görevler iptal '
       'edilmez.', lo=1, hi=10, varsayilan=5, birim='görev', sinir=100),
    _b('kampanya', 'Başlangıç kampanyası', 'dunya', 'Görev penceresinde "Level N" başlangıç görevleri hep görünür. Kapalıyken '
       'yalnız yeni kayıtta seçildiyse ilk ay görünür; süren görev her durumda bitirilebilir.'),
    _b('atlama_sapma', "Atlama CPU'su ara sıra sapar", 'dunya', "Atlama CPU'su küçük bir olasılıkla (%2) seni Cubikon "
       'Mezarlığına götürür (oyundaki gibi). Kapatılırsa hep seçtiğin haritaya.', varsayilan=True),
    _b('paket_siniri', 'Benzersiz paketler bir kez', 'dunya', "Mağazada içinde gemi, gemi tasarımı, formasyon, P.E.T. ya da tekil "
       'dron olan paketler (Defcom-Raven, Stellar, Dusklight …) oyundaki gibi bir kez alınır, sonra listeden kalkar. Kapatılırsa '
       'tekrar alınabilir (sahip olduğun içerik atlanır).', varsayilan=True),
    _b('portal_hangar', 'Portallarda hangar', 'dunya', "Portalların güvenli bölgesinde de hangara girip donanım değiştirebilirsin "
       '(kolaylık; gerçek oyunda yalnız istasyonda). Kapatılırsa yalnız istasyonda.', varsayilan=True),
    _b('klan_bekleme', 'Klan 48 saat kuralları', 'dunya', 'Klandan ayrılınca 48 saat yeni klan kurulamaz ya da klana katılınamaz; klan '
       'adı/etiketi iki değişim arası 48 saat bekler. Kapalıyken bekleme yok.', varsayilan=True),
    # ---------------------------------------------------------------- kapılar ve modlar
    _c('kapi_parca', 'Kapı parçası şansı', 'kapi', 'Galaksi Kapısı üreticisinde bir enerjiyle kapı parçası çıkma olasılığı '
       '(oyunun değeri %13; pencerenin olasılık listesi de değişir).', lo=0.1, hi=7.0, sinir=1000.0),
    _n('kopya_eksige', 'Kopya parçanın eksiğe dönme şansı', 'kapi', 'Elinde olan bir kapı parçası çıkınca onun yerine eksik bir '
       'parça gelme olasılığı (oyunun değeri %50). %100: hiç kopya parça çıkmaz (kapı kurulana dek).', lo=0, hi=100,
       varsayilan=50, birim='%'),
    _c('kapi_enerji', 'Kapı enerjisi miktarı', 'kapi', 'Bonus kutularından çıkan ücretsiz Galaksi Kapısı enerjisinin miktarı '
       '(5-2 tüccarındaki Palladium takası ve paketler değişmez).', hi=20.0),
    _c('kapi_fiyat', 'Kapı fiyatları', 'kapi', 'Galaksi Kapısı üreticisinde enerjinin ve kapıda ek canların uridyum fiyatı. 0: '
       'bedava.', hi=5.0, sinir=300.0),
    _c('kapi_can', 'Kapılardaki can sayısı', 'kapi', 'Galaksi Kapılarında ve etkinlik kapılarında (Plutus, Quarantine …) kapı '
       'hazırlanınca verilen can (oyunun değeri çoğu kapıda 5).', lo=0.2, hi=10.0, sinir=1000.0),
    _b('sonsuz_can', 'Kapılarda can harcanmaz', 'kapi', 'Galaksi Kapısında ve etkinlik kapılarında yok edilince can eksilmez: '
       'kapı hiç kaybolmaz.'),
    _c('dalga_npc', 'Dalgalardaki uzaylı sayısı', 'kapi', 'Galaksi Kapılarının, etkinlik kapılarının ve modların (Astral, EBL, '
       'Voyagers, Trinity, Echoes) dalgalarındaki uzaylı sayısı. Koruyan patronlar bir tane kalır.', lo=0.1, hi=5.0, sinir=20.0),
    _c('dalga_bekleme', 'Dalgalar arası bekleme', 'kapi', 'Kapı ve mod dalgalarının başlangıç, alt dalga arası ve mola süreleri '
       '(Galaksi Kapısında giriş 6, mola 30 sn). 0: bekleme yok.', hi=5.0, sinir=100.0),
    _b('giris_siniri_yok', 'Kapı ve mod giriş sınırları kapalı', 'kapi', 'Etkinlik kapılarının günlük, yıllık ve tek seferlik '
       'giriş sınırları ve bekleme süreleri, Voyagers ve Trinity\'nin ücretsiz giriş hakları tükenmez.'),
    _n('kapi_bonus_adet', 'Bonuslu Galaksi Kapısı sayısı', 'kapi', 'Kapı penceresinde aynı anda süreli bonus ödülü olan kapı '
       'sayısı. Kapılar ve ödülleri her dönemin başında rastgele seçilir; kapıyı dönem bitmeden tamamlayınca (Dispatch\'in kapı '
       'gönderimi dahil) bonus bir kez verilir. 0: bonus yok.', lo=0, hi=11, varsayilan=3, birim='kapı'),
    _c('kapi_bonus_carpan', 'Kapı bonusu miktarı', 'kapi', 'Kapı bonusunun miktarı (onur, uridyum, cephane, log diski, anahtar); '
       'lazer ve tasarım gibi tek eşyalar bir tane kalır.', lo=0.1, hi=20.0),
    _n('kapi_bonus_saat', 'Kapı bonusu dönemi', 'kapi', 'Bonuslu kapıların değiştiği aralık (gece yarısına hizalı; 24: her gün). '
       'Değiştirilince seçim hemen yenilenir.', lo=1, hi=168, varsayilan=24, birim='saat', sinir=8760),
    # ---------------------------------------------------------------- ekonomi
    _c('magaza_fiyat', 'Mağaza fiyatları', 'ekonomi', 'Mağazada kredi ve uridyumla satılan her şeyin fiyatı.', lo=0.0,
       hi=5.0, sinir=1000.0),
    _b('etkinlik_gorunumleri_magazada', 'Etkinlik görünümleri mağazada', 'ekonomi', "Etkinliklerin gemi, dron ve P.E.T. "
       "tasarımları (Galactic Strife'ın Arios ve Neikos'u, Trial of Terrors'un Dusklight'ı, geçmiş sezonların tasarımları …) mağazada "
       'satılır. Kapatılırsa mağazada görünmez ve satılmazlar, yalnız kendi etkinliklerinde kazanılırlar: Battle Pass anahtar '
       'değişimi, etkinlik ve ganimet kutuları, GG hafta sonu kapıları, Season Pass. Mağazanın kendi tasarımları hep satılır.',
       varsayilan=True),
    _c('hizmet_fiyat', 'Hizmet ücretleri', 'ekonomi', "P.E.T. yuvaları, tamiri ve yakıtı; Skylab yükseltmeleri, anında bitirme, "
       'hızlı taşıma ve robotlar; gemi ışınlama. 0: bedava.', hi=5.0, sinir=1000.0),
    _c('tamir_ucreti', 'Ölüm sonrası tamir ücreti', 'ekonomi', 'Portalda ve bulunduğun yerde tamirin uridyum bedeli.',
       lo=0.0, hi=5.0, sinir=1000.0),
    _c('cevher_fiyat', 'Cevher satış fiyatı', 'ekonomi', 'Rafineride sattığın cevherlerin kredi ve uridyum karşılığı (pencerede de '
       'görünür).', hi=10.0, sinir=10000.0),
    _c('kargo', 'Kargo kapasitesi', 'ekonomi', "Geminin kargo alanı (Logistics, kargo CPU'su ve P.E.T. protokolüyle birlikte).",
       lo=0.5, hi=10.0, sinir=1000.0),
    _b('sonsuz_kargo', 'Sonsuz kargo', 'ekonomi', 'Kargo dolmaz: bütün kutular ve cevherler "kargo dolu" uyarısı almadan her zaman toplanır.'),
    _b('sonsuz_pet_menzili', 'Sonsuz P.E.T. bulucu menzili', 'ekonomi', "P.E.T.'in düşman ve kaynak bulucu dişlileri menzil sınırı olmadan "
       'haritadaki en yakın hedefi gösterir.'),
    _b('assembly_ucretsiz', 'Ücretsiz Assembly', 'ekonomi', 'Assembly ve Upgrade/Disassembly sekmelerinde malzeme harcanmaz; istemci '
       'bütün malzemeleri yeterli gösterir. Üretim ve bekleme süreleri ile günlük kullanım sınırları aynı kalır.'),
    _c('pet_yakit', 'P.E.T. yakıt tüketimi', 'ekonomi', "P.E.T.'in dakikalık yakıt tüketimi. 0: yakıt harcamaz.", lo=0.0, hi=5.0,
       sinir=100.0),
    _c('skylab_uretim', 'Skylab üretimi', 'ekonomi', 'Skylab toplayıcılarının ve rafinerilerinin saatlik üretimi.', hi=20.0),
    _c('skylab_depo', 'Skylab depo kapasitesi', 'ekonomi', 'Skylab deposunun her kaynak için kapasitesi.', hi=20.0,
       sinir=1000.0),
    # ---------------------------------------------------------------- süreler
    _c('bekleme', 'Üretim ve bekleme süreleri', 'sure', 'Assembly üretimi, Skylab yükseltmeleri ve taşıma, Dispatch gönderimleri, '
       'eşya yükseltmeleri. Düşük değer: daha çabuk (yeni başlayanlara uygulanır).', lo=0.0, hi=5.0, sinir=100.0),
    _c('yetenek_bekleme', 'Yetenek ve eşya beklemeleri', 'sure', "Gemi yetenekleri, CPU'lar, mayınlar, Smart Bomb, Insta-Shield, "
       'teknoloji eşyaları ve özel roketlerin bekleme süresi.', lo=0.05, hi=5.0, sinir=100.0),
    _c('booster_sure', 'Booster süresi', 'sure', 'Boosterların etkin kalma süresi (yeni etkinleştirilenlere uygulanır).', lo=0.1,
       hi=10.0, sinir=1000.0),
    _b('seviye_kisiti_yok', 'Seviye kısıtları kapalı', 'sure', "Portalların ve atlama CPU'sunun seviye şartı yok: her haritaya "
       'girebilirsin.'),
    _b('seans_hep_acik', 'Seanslı etkinlikler hep açık', 'sure', 'Saatle açılan etkinlikler (Vortex of Greed, Treacherous Domain, '
       'Mimesis Mutiny) etkinlik süresince her an açık: portal hep açık, seans/savaş/sefer girince başlar. Etkinlik uzaylıları '
       '(Curcubitor, Agatus, Lanatum, Chaos Protegit) da oyundaki saat pencerelerinin dışında doğar.'),
    # ---------------------------------------------------------------- müzayede
    dict(anahtar='muzayede_rakip', ad='Sanal rakipler', grup='muzayede', tur='seviye', varsayilan=0,
         secenekler=list(RAKIP_SEVIYELERI), renkler=['', 'ok', 'ok', 'info', 'err'], uygulama='anında',
         secenek_aciklama=['Rakip yok: teklifleri yalnız sen verirsin.',
                           'Arada bir küçük teklifler verirler; seni hiç geçmezler, teklif verdiğin lot senin.',
                           'Daha sık ve biraz daha yüksek teklifler; seni yine geçmezler.',
                           'Geçtiğinde bir süre sonra karşılık verirler. Bütçelerini aşarsan lot senin; kaybedersen kredin geri gelir.',
                           'Çok sık, yüksek bütçeli ve hızlı karşılık verirler. Kaptırmamak için iyi teklif ver.'],
         aciklama='Müzayedede sana rakip olan sanal teklifçiler. Çekingen ve Ilımlı: biraz teklif verirler ama seni hiç geçmezler, '
                  'teklif verdiğin lot hep senin olur. Rekabetçi ve Agresif: geçtiğinde karşılık verirler; bütçelerini aşmadıkça '
                  'lotu kaybedebilirsin (kredin geri gelir). Dünyada bot paketi açıkken kapalıdır: teklifleri botlar verir.'),
    # ---------------------------------------------------------------- arayüz
    _b('karanlik', 'Karanlık haritalar (el feneri)', 'arayuz', 'Trial of Terrors kapısının haritalarında ekran kararır, yalnız '
       'geminin baktığı yön aydınlıktır (istemcinin el feneri etkisi). Kapatılırsa haritalar aydınlık.', uygulama='harita',
       varsayilan=True),
    _b('sinematik', 'Sinematik patron girişleri', 'arayuz', 'Etkinlik patronu doğunca ve Galaksi Kapısının son dalgasında kamera '
       'birkaç saniye patrona döner (kontroller o sürede kilitli), sonra gemine geri gelir.', varsayilan=True),
    _b('ipuclari', 'Yeni başlayan ipuçları', 'arayuz', 'Bir şey ilk kez olunca (kargo doldu, cephane bitti, başka firmanın haritası) '
       've seviye atladıkça yeni özellikleri anlatan ipucu pencereleri, süren etkinliğin açıklaması. Her biri bir kez; kapattığın '
       'ipuçları açılmaz, ipucu arşivinden yeniden okunabilir.', varsayilan=True),
    _b('seri_oldurme', 'Seri öldürme duyuruları', 'arayuz', 'Kısa aralıklarla art arda uzaylı yok edince ekranda "Triple Kill", '
       '"Unstoppable", "Godlike", "Like a Boss" duyurusu ve sesi (3, 6, 10, 15 öldürme; aralık en çok 10 sn).'),
    _b('reklamsiz', 'Açılış pencerelerini gösterme', 'arayuz', 'Girişte kendiliğinden açılan günlük bonus, ipucu ve Season Pass '
       'pencereleri gönderilmez (menülerden açılabilirler).', uygulama='giriş'),
    # ---------------------------------------------------------------- yönetici (yonetici_modu.py)
    _b('yonetici_modu', 'Yönetici modu', 'yonetici', 'Oyunda yönetici olursun: adının önünde yönetici rozeti (sarı A), rütbe '
       'sistemine, Şeref Salonu sıralamalarına ve şirketteki sıraya girmezsin. Botlar seni yönetici olarak tanır: sana saldırmaz, '
       'sohbetteki uyarılarına uyar, seni görünce tepki verir. Arkadaş sunucusunda yalnız sunucunun oyuncusu için.', uygulama='giriş'),
    dict(anahtar='yonetici_gemisi', ad='Yönetici gemisi', grup='yonetici', tur='seviye', varsayilan=0,
         secenekler=['Kendi gemin', 'UFO', 'Polis', 'G-Admincloak', 'Goliath Admin'], renkler=['', 'info', 'info', 'info', 'info'],
         uygulama='giriş',
         secenek_aciklama=['Yönetici modunda da kendi geminle görünürsün.',
                           'Yönetici gemisi (ship_admin): oyundaki UFO uzaylısıyla aynı model.',
                           'Polis gemisi (ship_police).',
                           'Yöneticinin gizlenme gemisi (ship_g-admincloak).',
                           'Goliath\'ın yönetici tasarımı (admincloak).'],
         aciklama='Yönetici modundayken gemin bu görünümde; değerleri (can, hız, donanım) kendi geminin.'),
    _b('yonetici_izleyici', 'İzleyici (dokunulmaz)', 'yonetici', 'Yönetici modundayken uzaylılar ve botlar sana saldırmaz, hasar '
       'almazsın; haritaları rahatça gezip botları izleyebilirsin.', uygulama='anında'),
    _b('yonetici_sohbet', 'Sohbette yönetici', 'yonetici', 'Yönetici modundayken sohbet mesajların yönetici olarak (oyunun yönetici '
       'rengiyle) görünür.', uygulama='giriş', varsayilan=True),
    _b('gm_konsol', 'GM konsolu', 'yonetici', 'Oyunun gizli yönetici penceresi: oyunda Ctrl, ardından Shift, ardından Z. Haritaya '
       'ışınlanma, uzaylı ve kutu doğurma, eşya ve paket verme, görevleri bitirme, kapı kurma, bekleme sürelerini sıfırlama, '
       'dokunulmazlık. Açıkken adının önünde yönetici rozeti görünür (istemci yöneticiyi rütbe 6000 ile tanıyor).', uygulama='giriş'),
    # ---------------------------------------------------------------- geliştirici
    _b('yakin_npc', 'Yakında uzaylı doğur', 'gelistirici', 'Test kolaylığı: ilk dört uzaylı türünden birer tane geminin hemen '
       'yanında doğar.', uygulama='harita'),
    _b('kontrol', 'Canlı test kontrol kanalı', 'gelistirici', 'Geliştirici aracı (kontrol.py, 127.0.0.1:8099): mesaj izi ve '
       'istek enjeksiyonu.', uygulama='başlatma'),
]

# alt ayarlar: üst çarpan -> kaynakları [(kaynak, ad, açıklama)]; oyundaki karşılığı carpan(üst, kaynak) çağıran yerler
_NPC = ('npc', 'Uzaylılar', 'Uzaylı (NPC) öldürünce.')
_KUTU = ('kutu', 'Kutular ve sandıklar', 'Bonus kutuları, etkinlik kutuları ve ganimet sandıkları.')
_GOREV = ('gorev', 'Görevler', 'Görev penceresinin görevleri ve Acil Görevler.')
_KAPI = ('kapi', 'Kapılar', "Galaksi Kapıları (Dispatch'in kapı gönderimi dahil) ve etkinlik kapıları (Plutus, Quarantine …) "
         'tamamlanınca.')
_MOD = ('mod', 'Modlar ve etkinlikler', 'Astral, EBL, Galaxy Trek, Mimesis, Apotheosis, Voyagers, Trinity, Deep Space Echoes, '
        'Labirent, dünya patronları, Battle Station, Dispatch ve etkinliklerin ödülleri.')
_EK = ('ek', 'Uzaylıların ek ödülleri', 'Uzaylı öldürünce gelen Palladium, etkinlik paraları ve kaynaklar.')
_YER = (('harita', 'Haritalarda', 'Haritalarda dolaşan uzaylılar ve patronlar.'),
        ('dalga', 'Kapı ve mod dalgalarında', 'Galaksi Kapılarının, etkinlik kapılarının ve modların (Astral, EBL, Voyagers, '
         'Trinity, Mimesis …) dalgalarındaki uzaylılar.'))
_PARA = (_NPC, _KUTU, _GOREV, _KAPI, _MOD)
ALTLAR = {
    'kredi': _PARA, 'uridyum': _PARA, 'ep': _PARA, 'onur': _PARA,
    'toplama': (_KUTU, ('kargo', 'Uzaylıların kargo kutuları', 'Uzaylının bıraktığı kargo kutusundaki cevher.'),
                ('maden', 'Cevher toplama', 'Haritadaki cevherlerden toplanan miktar.'), _EK),
    'mod_odul': (_GOREV, _KAPI, _MOD),
    'dusme': (('booster', 'Booster', 'Patron ve Uber uzaylılardan booster düşmesi.'), _EK,
              ('etkinlik', 'Etkinlik düşmeleri', 'Etkinlik ve etkinlik kapısı uzaylılarının kutuları, Chromin kutuları, Hitac '
               'piyangosunun harfleri.'),
              ('kapi', 'Kapılar', 'Galaksi Kapılarının ve etkinlik kapılarının şanslı ödülleri (tasarımlar, LF-4 …).'),
              ('mod', 'Modlar', "Astral'ın kurtarma çekirdeği ve anahtarları, EBL'nin ek ödülü.")),
    'npc_hasar': _YER, 'npc_can': _YER,
    'oyuncu_hasar': (('pve', 'Uzaylılara (PvE)', 'Uzaylılara (NPC) verdiğin hasar.'),
                     ('pvp', 'Oyunculara (PvP)', 'Başka oyunculara lazer ve roketlerle verdiğin hasar.'),
                     ('bot', 'Botlara', 'Botlara verdiğin hasar.')),
    'kutu_bolluk': (('bonus', 'Bonus kutuları', 'Haritalara dağılan bonus kutuları.'),
                    ('ganimet', 'Ganimet sandıkları', 'Anahtarla açılan ganimet sandıkları.'),
                    ('etkinlik', 'Etkinlik kutuları', 'Etkinliklerin haritalara getirdiği kutular.')),
    'npc_sayi': (('harita', 'Haritaların uzaylıları', 'Haritanın kendi uzaylıları ve patronları.'),
                 ('etkinlik', 'Etkinlik uzaylıları', 'Etkinliklerin haritalara getirdiği uzaylılar.')),
    'magaza_fiyat': (('kredi', 'Kredi ile satılanlar', 'Mağazada kredi fiyatlı her şey.'),
                     ('uridyum', 'Uridyum ile satılanlar', 'Mağazada uridyum fiyatlı her şey.')),
    'hizmet_fiyat': (('pet', 'P.E.T.', "P.E.T.'in yuvaları, tamiri ve yakıtı."),
                     ('skylab', 'Skylab', 'Yükseltmeler, anında bitirme, hızlı taşıma ve robotlar.'),
                     ('isinlama', 'Gemi ışınlama', 'Başka bir gemini hangara gitmeden bulunduğun yere getirme.')),
    'bekleme': (('assembly', 'Assembly üretimi', "Assembly'de eşya üretimi."),
                ('skylab', 'Skylab', 'Modül yükseltmeleri ve taşıma.'),
                ('dispatch', 'Dispatch', 'Gönderimler ve kapı gönderimleri.'),
                ('yukseltme', 'Eşya yükseltmeleri', 'Lazerlerin, jeneratörlerin, dronların ve modüllerin seviye yükseltmeleri.')),
    'yetenek_bekleme': (('yetenek', 'Gemi yetenekleri', 'Geminin kendi yetenekleri.'),
                        ('esya', "Savaş eşyaları ve CPU'lar", "Mayınlar, Smart Bomb, Insta-Shield, EMP, özel roketler ve CPU'lar."),
                        ('teknoloji', 'Teknoloji eşyaları', 'Energy Leech, Chain Impulse, Battle Repair Bot, Speed Burst …'),
                        ('parcacik', 'Parçacık topları ve sürücü', 'Parçacık silahları ve Singularity Drive.')),
}
SCHEMA = [x for s in SCHEMA for x in [s] + [dict(s, anahtar='%s_%s' % (s['anahtar'], k), ad=ad, aciklama=aciklama, varsayilan=1.0,
                                                 ust=s['anahtar'], kaynak=k) for k, ad, aciklama in ALTLAR.get(s['anahtar'], ())]]
ALT = {(s['ust'], s['kaynak']): s['anahtar'] for s in SCHEMA if s.get('ust')}
BY_KEY = {s['anahtar']: s for s in SCHEMA}
DEFAULTS = {s['anahtar']: s['varsayilan'] for s in SCHEMA}
ETKINLIK_DURUMLARI = ('acik', 'kapali')         # yoksa takvime göre

# hazır ayarlar (panelin "Hazır ayarlar" listesi): yalnız değişen anahtarlar, ötekiler varsayılan
HAZIR = {
    'varsayilan': {'ad': 'Varsayılan', 'aciklama': 'Oyunun kendi değerleri.', 'degerler': {}},
    'rahat': {'ad': 'Rahat', 'aciklama': 'Daha az hasar alırsın, ödüller ve kutular bol.',
              'degerler': {'npc_hasar': 0.5, 'kredi': 2.0, 'uridyum': 2.0, 'ep': 2.0, 'onur': 2.0, 'toplama': 2.0, 'dusme': 2.0,
                           'kutu_bolluk': 2.0, 'kutu_yenilenme': 0.5, 'mod_odul': 2.0, 'dron_puan': 2.0, 'pet_ep': 2.0,
                           'kalkan_yenilenme': 2.0}},
    'hizli': {'ad': 'Hızlı ilerleme', 'aciklama': 'Ödüller beş kat, uzaylılar kalabalık ve çabuk doğar.',
              'degerler': {'kredi': 5.0, 'uridyum': 5.0, 'ep': 5.0, 'onur': 5.0, 'toplama': 5.0, 'dusme': 3.0, 'kutu_bolluk': 3.0,
                           'kutu_yenilenme': 0.3, 'npc_sayi': 1.5, 'npc_yenilenme': 0.3, 'magaza_fiyat': 0.5, 'mod_odul': 5.0,
                           'dron_puan': 5.0, 'pet_ep': 5.0, 'sezon_puani': 3.0, 'skylab_uretim': 3.0, 'maden_bolluk': 2.0,
                           'dalga_bekleme': 0.5}},
    'zorlu': {'ad': 'Zorlu', 'aciklama': 'Uzaylılar daha sert vurur ve dayanıklıdır, ödüller az, rakipler agresif.',
              'degerler': {'npc_hasar': 2.0, 'npc_can': 1.5, 'kredi': 0.75, 'uridyum': 0.75, 'kutu_bolluk': 0.5,
                           'tamir_ucreti': 2.0, 'muzayede_rakip': 4, 'npc_isabet': 1.25, 'npc_saldirganlik': 1,
                           'kalkan_yenilenme': 0.5}},
    'yaratici': {'ad': 'Yaratıcı', 'aciklama': 'Gemin yok edilmez, cephane bitmez, mağaza ve hizmetler bedava, bekleme yok.',
                 'degerler': {'dokunulmaz': True, 'sonsuz_cephane': True, 'sonsuz_teknoloji': True, 'magaza_fiyat': 0.0, 'hizmet_fiyat': 0.0,
                              'kapi_fiyat': 0.0, 'tamir_ucreti': 0.0, 'bekleme': 0.0, 'seviye_kisiti_yok': True,
                              'sonsuz_can': True, 'giris_siniri_yok': True, 'pet_yakit': 0.0, 'assembly_ucretsiz': True,
                              'sonsuz_kargo': True, 'sonsuz_pet_menzili': True}},
}

_lock = threading.Lock()
_state = {'yol': None, 'mtime': None, 'okuma': 0.0, 'd': {}}


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
                out[key] = min(s['sinir'], max(s['min'], v))
            elif s['tur'] == 'bool':
                out[key] = bool(v)
            elif s['tur'] == 'seviye':
                out[key] = min(len(s['secenekler']) - 1, max(0, int(v)))
            elif s['tur'] == 'sayi':
                v = float(v)
                if v != v:                                # NaN
                    continue
                out[key] = int(round(min(s['sinir'], max(s['min'], v))))       # sonsuz da sınıra
        except (TypeError, ValueError):
            continue
    ev = raw.get('etkinlikler')
    if isinstance(ev, dict):
        out['etkinlikler'] = {str(k): v for k, v in ev.items() if v in ETKINLIK_DURUMLARI}
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
    """Ayar dosyasını bağla: path, yoksa --ayarlar=<yol> seçeneği, yoksa save/ayarlar.json. path=False: bağı çöz (varsayılanlar)."""
    if path is None:
        argv = sys.argv if argv is None else argv
        path = next((a.split('=', 1)[1] for a in argv if a.startswith('--ayarlar=')), VARSAYILAN_YOL)
    with _lock:
        _state.update(yol=path or None, mtime=None, okuma=0.0, d={})
    return path


def _current():
    with _lock:
        if not _state['yol']:
            return _state['d']
        now = time.monotonic()
        if _state['mtime'] is not None and now - _state['okuma'] < YENILE_SN:
            return _state['d']
        _state['okuma'] = now
        try:
            m = os.stat(_state['yol']).st_mtime_ns
        except OSError:
            m = 0
        if m != _state['mtime']:
            _state['mtime'] = m
            _state['d'] = read(_state['yol']) if m else {}
        return _state['d']


def get(key):
    return _current().get(key, DEFAULTS[key])


def carpan(key, kaynak=None):
    """Çarpan; kaynak verilirse alt ayarıyla çarpılır (carpan('uridyum', 'npc') = uridyum x uridyum_npc). Kaynağın alt ayarı
    yoksa yalnız üst."""
    alt = ALT.get((key, kaynak))
    return float(get(key)) * (float(get(alt)) if alt else 1.0)


def surum():
    """Ayar dosyasının sürümü (değiştirilme anı; bağlı değilse None): oyun açıkken değişen ayarı fark etmek için (dunya.settings_tick)."""
    _current()
    with _lock:
        return _state['mtime']


def fiyat(key, n, kaynak=None):
    """Fiyatı çarpanla ölçekle (hizmet ücretleri …): tam sayı, en az 0, 32 bitlik alana sığar."""
    m = carpan(key, kaynak)
    return n if m == 1.0 or not n else min(I32, max(0, int(round(n * m))))


def adet(key, n, kaynak=None):
    """Sayıyı (uzaylı, kutu adedi) çarpanla ölçekle: yuvarlanır, pozitif sayı en az 1 kalır (patron kaybolmaz); çarpan 0 ise 0."""
    m = carpan(key, kaynak)
    if m == 1.0 or not n or n < 0:
        return n
    return 0 if m <= 0 else max(1, int(round(n * m)))


def miktar(key, n, kaynak=None):
    """Miktarı (ödül, toplanan eşya) çarpanla ölçekle: kesir olasılıkla yuvarlanır (x1,5 ile 1 -> yarı yarıya 1 ya da 2),
    beklenen değer tam çarpan kadar."""
    m = carpan(key, kaynak)
    if m == 1.0 or not n or n < 0:
        return n
    v = n * m
    whole = int(v)
    return whole + (1 if random.random() < v - whole else 0)


def sure(sec, kaynak=None):
    """Üretim ve bekleme süresi (panelin 'bekleme' çarpanı; kaynak: assembly, skylab, dispatch, yukseltme) -> saniye (en az 1)."""
    m = carpan('bekleme', kaynak)
    return sec if m == 1.0 else max(1, int(round(sec * m)))


def chance(key, p, kaynak=None):
    """Olasılığı çarpanla ölçekle (0..1)."""
    m = carpan(key, kaynak)
    return p if m == 1.0 else min(1.0, max(0.0, p * m))


def event_state(key):
    """Oyuncunun etkinlik seçimi: 'acik', 'kapali' ya da None (takvime göre)."""
    return (_current().get('etkinlikler') or {}).get(key)


def tam_ad(s, ad=lambda x: x):
    """Ayarın özetlerdeki adı: alt ayar üstüyle birlikte ('Uridyum kazancı › Uzaylılar'); ad: çeviri (panel)."""
    return ad(BY_KEY[s['ust']]['ad']) + ' › ' + ad(s['ad']) if s.get('ust') else ad(s['ad'])


def summary(values=None):
    """Varsayılandan farklı ayarlar [(ad, değer metni)] (panelin özet çipleri)."""
    d = _current() if values is None else clean(values)
    out = []
    for s in SCHEMA:
        v = d.get(s['anahtar'], s['varsayilan'])
        if v == s['varsayilan']:
            continue
        if s['tur'] == 'carpan':
            out.append((tam_ad(s), 'x%g' % v))
        elif s['tur'] == 'bool':
            out.append((s['ad'], 'açık' if v else 'kapalı'))
        elif s['tur'] == 'sayi':
            out.append((s['ad'], ('%d %s' % (v, s.get('birim', ''))).strip()))
        else:
            out.append((s['ad'], s['secenekler'][v]))
    return out
