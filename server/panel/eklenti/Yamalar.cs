// İstemcinin düzeltmeleri: BepInEx 6 (IL2CPP) eklentisi, Harmony yamaları. Panel BepInEx'i istemci klasörüne kurar, bu klasördeki
// derlenmiş OpenOrbitYama.dll'i BepInEx/plugins'e koyar ve Doorstop'u yalnız kendi açtığı istemcide etkinleştirir
// (panel/istemci_yama.py). İstemcinin kendi dosyaları değişmez, yamalar bellekte. 1.1.115 için yazıldı: bir yamanın hedeflerinden biri
// bulunmazsa o yama hiç uygulanmaz; günlük BepInEx/LogOutput.log. README'deki "istemci yamalanmaz" kuralının kullanıcı onaylı istisnası
// (2026-10-24; BepInEx'e geçiş 2026-10-25).
using System;
using System.Reflection;
using BepInEx;
using BepInEx.Unity.IL2CPP;
using DarkOrbit;
using DG.Tweening;
using DG.Tweening.Core;
using HarmonyLib;
using Il2CppInterop.Runtime;
using net.bigpoint.darkorbit.com.module.porting.halloffame;
using UnityEngine;
using UnityEngine.Events;

namespace OpenOrbit;

[BepInPlugin("openorbit.yama", "OpenOrbit istemci yamaları", "1.0.0")]
public class Eklenti : BasePlugin
{
    public override void Load()
    {
        var h = new Harmony("openorbit.yama");
        Uygula("müzayede sayacı", () => Muzayede.Uygula(h));
        Uygula("rütbe penceresi", () => RutbePenceresi.Uygula(h));
        Uygula("mağaza tutarı", () => MagazaTutari.Uygula(h));
        Uygula("otomatik pilot kaçışı", () => OtopilotKacisi.Uygula(h));
        Uygula("sohbet moderatörü rengi", () => ModeratorRengi.Uygula(h));
        Uygula("otomatik kuşanma ayarı", () => OtomatikKusanma.Uygula(h));
        Uygula("görev metinleri", () => GorevMetinleri.Uygula(h));
        Uygula("eski yükseltme sistemi", () =>
        {
            EskiYukseltme.Uygula(h);
            AddComponent<EskiYukseltmeIzci>();
        });
        Uygula("görsel dökümü", () =>
        {
            GorselDokumu.Log = Log;
            AddComponent<GorselDokumu>();
        });
        Uygula("GM Center overlay", () => AddComponent<GMCenterOverlay>());
    }

    void Uygula(string ad, Action yama)
    {
        try
        {
            yama();
            Log.LogInfo("istemci yaması: " + ad);
        }
        catch (Exception e)
        {
            Log.LogError("istemci yaması uygulanmadı (" + ad + "): " + e);
        }
    }

    // Hedefler bulunmazsa hiçbir şey yamalanmadan hata
    internal static void Bul(params MethodBase[] hedefler)
    {
        if (Array.IndexOf(hedefler, null) >= 0)
            throw new MissingMethodException("istemcide beklenen metot yok (1.1.115 değil mi?)");
    }
}

// Müzayede sayacı (CANLI_TEST H175; istemcinin kendi hatası, sunucu her listede doğru süreyi gönderiyor):
//   UIAuctionSystem.StartCountdown her çağrıda yeni bir DOTween sayacı kurar, eskisini durdurmaz; sayaçların yazıcısı (b__1) o an seçili
//   sekmenin alanına ve tek süre yazısına yazar. Sayaç yalnız pencerenin ilk listesinde ve sekme tıklamasında kurulur (sonraki listeler,
//   yenile ve sayacın bitince istediği liste kurmaz). Sonuç: saatlik dönem bitince saatlik sekmede günlük sayaç görünür (22:57:22), hiç
//   sekme gezilmediyse 00:00:00'da kalır; sekme tıklaması son listenin bayat süresini kullanır.
//   P1 SetAuctionInfo: her listede seçili sekmenin sayacı listenin süresiyle yeniden kurulur (OnChickBTN; sekme değişmez)
//   P2 DOTween.To: StartCountdown'ın kurduğu son sayaç (kapanış nesnesi) kaydedilir
//   P3, P4 sayacın yazıcısı ve bitişi: son sayaç değilse hiçbir şey yapmaz (eski sayaçlar yazmaz, bitince liste istemez)
//   P5 OnChickBTN: sekme tıklamasında bayat süreyle kurmak yerine liste ister (RefreshUI); yanıtı P1 kurar
static class Muzayede
{
    static IntPtr son;                  // son kurulan sayacın kapanış nesnesi
    static bool sekmede, listeden;      // OnChickBTN sürüyor; onu P1 çağırdı

    internal static void Uygula(Harmony h)
    {
        Type s = typeof(UIAuctionSystem), k = typeof(UIAuctionSystem.__c__DisplayClass26_0);
        MethodBase bilgi = AccessTools.Method(s, nameof(UIAuctionSystem.SetAuctionInfo)),
            sekme = AccessTools.Method(s, nameof(UIAuctionSystem.OnChickBTN)),
            sayac = AccessTools.Method(s, nameof(UIAuctionSystem.StartCountdown)),
            to = AccessTools.Method(typeof(DOTween), nameof(DOTween.To),
                new[] { typeof(DOGetter<int>), typeof(DOSetter<int>), typeof(int), typeof(float) }),
            yazici = AccessTools.Method(k, nameof(UIAuctionSystem.__c__DisplayClass26_0._StartCountdown_b__1)),
            bitis = AccessTools.Method(k, nameof(UIAuctionSystem.__c__DisplayClass26_0._StartCountdown_b__2));
        Eklenti.Bul(bilgi, sekme, sayac, to, yazici, bitis);
        h.Patch(bilgi, prefix: Y(nameof(BilgiOnce)), postfix: Y(nameof(BilgiSonra)));
        h.Patch(sekme, prefix: Y(nameof(SekmeOnce)), finalizer: Y(nameof(SekmeSon)));
        h.Patch(sayac, prefix: Y(nameof(SayacOnce)));
        h.Patch(to, prefix: Y(nameof(SayacKuruldu)));
        h.Patch(yazici, prefix: Y(nameof(YalnizSon)));
        h.Patch(bitis, prefix: Y(nameof(YalnizSon)));
    }

    static HarmonyMethod Y(string ad) => new HarmonyMethod(typeof(Muzayede), ad);

    // P1: TabType yoksa (ilk liste) istemcinin kendi yolu (ilk sekme; P5 liste ister); varsa sekmenin sırası (0 saat, 1 gün, 2 hafta)
    static void BilgiOnce(UIAuction self, out string __state) => __state = self.TabType;

    static void BilgiSonra(UIAuction self, string __state)
    {
        if (__state == null)
            return;
        listeden = true;
        try
        {
            UIAuctionSystem.OnChickBTN(self, true, __state == "day" ? 1 : __state == "week" ? 2 : 0);
        }
        finally
        {
            listeden = false;
        }
    }

    static void SekmeOnce() => sekmede = true;

    static void SekmeSon() => sekmede = false;

    // P5: OnChickBTN'un içindeki sayaç P1'den geliyorsa kurulur, sekme tıklamasıysa liste istenir (ShowEndTime'ınki değişmez)
    static bool SayacOnce(UIAuction self)
    {
        if (!sekmede || listeden)
            return true;
        UIAuctionSystem.RefreshUI(self);
        return false;
    }

    static void SayacKuruldu(DOGetter<int> getter)
    {
        var k = getter.Target?.TryCast<UIAuctionSystem.__c__DisplayClass26_0>();
        if (k != null)
            son = k.Pointer;
    }

    static bool YalnizSon(UIAuctionSystem.__c__DisplayClass26_0 __instance) => __instance.Pointer == son;
}

// Rütbe penceresi (Hall of Fame "Your Rank"; kullanıcı bildirimi 2026-10-24: Sergeant olunca da "You currently have the lowest rank."):
//   UIHallOfFameSystem.UpdateDailyRankForServer alt satırı yourRanking'e göre kurar ("hof_your_rank_below" rütbe 2-20, "hof_rank_lowest" 1,
//   "hof_rank_highest" 21) ama sonucu atıp metin dizisine hep GetTextById("hof_rank_lowest") koyar. Dizi birleşip MiddleDesc'e yazılır
//   (ipucu, boş satır, üst rütbe satırı, satır sonu, alt satır, boş satır, ...): R1 metindeki "hof_rank_lowest" satırı kurulan satır olur.
static class RutbePenceresi
{
    internal static void Uygula(Harmony h)
    {
        MethodBase hedef = AccessTools.Method(typeof(UIHallOfFameSystem), nameof(UIHallOfFameSystem.UpdateDailyRankForServer));
        Eklenti.Bul(hedef);
        h.Patch(hedef, postfix: new HarmonyMethod(typeof(RutbePenceresi), nameof(Sonra)));
    }

    static void Sonra(UIHallOfFame self, HallOfFameTopDataListCommand info)
    {
        var p = info.myRankingPoints;
        if (p.yourRanking <= 1)
            return;
        string satir = p.yourRanking >= 21 ? LocalizationManager.GetTextById("hof_rank_highest", Category.Resource)
            : LocalizationManager.GetTextById("hof_your_rank_below", Category.Resource)
                .Replace("%RANK_BELOW%", LocalizationManager.GetTextById("rang_" + (p.yourRanking - 1), Category.Resource_system_inc))
                .Replace("%RANKPOINTS_BELOW%", p.belowPoints.ToString());
        var metin = self.View.MiddleDescTextMeshProUGUI;
        string eski = "\r\n" + LocalizationManager.GetTextById("hof_rank_lowest", Category.Resource) + "\r\n\r\n", t = metin.text;
        int i = t.IndexOf(eski, StringComparison.Ordinal);
        if (i >= 0)
            metin.text = t.Substring(0, i) + "\r\n" + satir + "\r\n\r\n" + t.Substring(i + eski.Length);
    }
}

// Mağaza tutarı (kullanıcı bildirimi 2026-10-25, CANLI_TEST H233): bedava üründe sunucu price[0]'ı 1e-9 gönderir (magaza.BEDAVA_FIYAT;
//   0 olsa istemci adet seçicili üründe Buy'u kapatıyor). Ürüne tıklanınca toplam kutusu UIShopSystem.ReturnPriceName'den gelir ve fiyatı
//   yuvarlamadan biçimler ("0.000000001 U."); adet değişince istemci tutarı 2 haneye yuvarlıyor (CalculatePurchaseCost: Decimal.Round(x,
//   2, AwayFromZero)). M1: ReturnPriceName'in ReturnCostStr çağrısı aynı yuvarlamadan geçer ("0 U."). Mağazanın öteki fiyatlarında 2
//   haneden fazla ondalık yok: değişmez.
static class MagazaTutari
{
    static bool fiyatta;                // ReturnPriceName sürüyor

    internal static void Uygula(Harmony h)
    {
        MethodBase fiyat = AccessTools.Method(typeof(UIShopSystem), nameof(UIShopSystem.ReturnPriceName)),
            tutar = AccessTools.Method(typeof(UIShopSystem), nameof(UIShopSystem.ReturnCostStr));
        Eklenti.Bul(fiyat, tutar);
        h.Patch(fiyat, prefix: Y(nameof(FiyatOnce)), finalizer: Y(nameof(FiyatSon)));
        h.Patch(tutar, prefix: Y(nameof(TutarOnce)));
    }

    static HarmonyMethod Y(string ad) => new HarmonyMethod(typeof(MagazaTutari), ad);

    static void FiyatOnce() => fiyatta = true;

    static void FiyatSon() => fiyatta = false;

    static void TutarOnce(ref Il2CppSystem.Decimal cost)
    {
        if (fiyatta)
            cost = Il2CppSystem.Decimal.Round(cost, 2, Il2CppSystem.MidpointRounding.AwayFromZero);
    }
}

// Otomatik pilot kaçışı (Omega AutoTactic; kullanıcı bildirimi 2026-10-28: uzaylıdan hızlı gemi ateş edemeden sonsuza kaçıyordu):
//   HangUpAI.ExecuteAttackAction hedef attackRange içindeyken ateş eder ve ardından UpdateCloseRangeEscapeMovement'ı çağırır. O, en
//   yakın tehdit attackRange - 5'ten (birden çok tehditte + 45) yakınsa gemiyi tehditten (aralık - uzaklık) + 120 (çok tehditte 250)
//   birim, en az o kadar en çok 650 uzağa kaçırır: kaçış her seferinde menzil + 115 / + 290'da biter, hedef menzil dışına düşer, kovalanır,
//   yine yaklaşınca kaçılır. O1: kaçış hesaplanırken attackRange KACIS_PAYI düşük: kaçış ancak tehdit gerçekten yakınken başlar ve gemiyi
//   menzil içinde (çok tehditte menzil - 10) bırakır; ateş ve kovalama kendi menzille (finalizer geri koyar).
static class OtopilotKacisi
{
    const float KACIS_PAYI = 300f;      // 250 kaçış + 45 grup aralığı + 5 pay
    static float menzil = -1f;

    internal static void Uygula(Harmony h)
    {
        MethodBase hedef = AccessTools.Method(typeof(HangUpAI), nameof(HangUpAI.UpdateCloseRangeEscapeMovement));
        Eklenti.Bul(hedef);
        h.Patch(hedef, prefix: new HarmonyMethod(typeof(OtopilotKacisi), nameof(Once)),
            finalizer: new HarmonyMethod(typeof(OtopilotKacisi), nameof(Son)));
    }

    static void Once(HangUpAI __instance)
    {
        menzil = __instance.attackRange;
        __instance.attackRange = Math.Max(0f, menzil - KACIS_PAYI);
    }

    static void Son(HangUpAI __instance)
    {
        if (menzil >= 0f)
            __instance.attackRange = menzil;
        menzil = -1f;
    }
}

// Sohbet moderatörü rengi (kullanıcı isteği 2026-10-31): sunucunun moderatör botları sohbette "mod" rolüyle ve [CM] etiketiyle yazar
// (server/bot/moderasyon.py). İstemcinin UIChatSystem.BuildMessageText'i rengi role göre seçer: admin #FF0000 (etiketi gizler, kanal
// yerine "Yönetici" yazar), system gri, chatter firma rengi, öteki roller (mod dahil) #FFFFFF. R1: "mod" rolündeki göndericinin
// satırı RENK ile çizilir; etiket ve kanal adı olduğu gibi kalır ("[Global] [CM] Ad").
static class ModeratorRengi
{
    const string ROL = "mod", RENK = "#FFC83D", BEYAZ = "<color=#FFFFFF>";

    internal static void Uygula(Harmony h)
    {
        MethodBase hedef = AccessTools.Method(typeof(UIChatSystem), nameof(UIChatSystem.BuildMessageText));
        Eklenti.Bul(hedef);
        h.Patch(hedef, postfix: new HarmonyMethod(typeof(ModeratorRengi), nameof(Son)));
    }

    static void Son(ChatMessageVo message, ref string __result)
    {
        var u = message?.User;
        if (u == null || u.Usertype != ROL || __result == null)
            return;
        int i = __result.IndexOf(BEYAZ, StringComparison.Ordinal);
        if (i >= 0)
            __result = __result.Substring(0, i) + "<color=" + RENK + ">" + __result.Substring(i + BEYAZ.Length);
    }
}

// Otomatik kuşanma ayarı (kullanıcı bildirimi 2026-10-31: "Auto-equip new items" kapalıyken de ödül eşyaları takılıyordu): Ayarlar >
//   Gameplay'deki kutu (Tog9GameplayToggle) istemcide yalnız etiketle kurulur (UISettingsSystem.InitGameplay; dinleyicisi yok, kaydedilmez,
//   GameplaySettingsRequest'te alanı yok), sunucu ödül ekipmanını boş yuvaya hep takıyordu (magaza._reward). K1: InitGameplay'den sonra
//   kutu PlayerPrefs'teki değerle kurulur (varsayılan açık); değişince kaydedilir. Kurulunca ve değişince sunucuya LegacyModule
//   "AEQ|1" / "AEQ|0" gider (game.py -> profil otomatik_kusan).
static class OtomatikKusanma
{
    const string ANAHTAR = "openorbit_autoEquip";

    internal static void Uygula(Harmony h)
    {
        MethodBase hedef = AccessTools.Method(typeof(UISettingsSystem), nameof(UISettingsSystem.InitGameplay));
        Eklenti.Bul(hedef);
        h.Patch(hedef, postfix: new HarmonyMethod(typeof(OtomatikKusanma), nameof(Sonra)));
    }

    static void Sonra(UISettings self)
    {
        var kutu = self?.View?.Tog9GameplayToggle;
        if (kutu == null)
            return;
        bool acik = PlayerPrefs.GetInt(ANAHTAR, 1) != 0;
        kutu.onValueChanged.RemoveAllListeners();
        kutu.SetIsOnWithoutNotify(acik);
        kutu.onValueChanged.AddListener(DelegateSupport.ConvertDelegate<UnityAction<bool>>(new Action<bool>(Degisti)));
        Gonder(acik);
    }

    static void Degisti(bool acik)
    {
        PlayerPrefs.SetInt(ANAHTAR, acik ? 1 : 0);
        PlayerPrefs.Save();
        Gonder(acik);
    }

    static void Gonder(bool acik)
    {
        var parcalar = new Il2CppSystem.Collections.Generic.List<string>();
        parcalar.Add("AEQ");
        parcalar.Add(acik ? "1" : "0");
        NetConnectionHelper.SendLegacyModule(parcalar);
    }
}
