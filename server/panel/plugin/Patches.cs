// İstemcinin düzeltmeleri: BepInEx 6 (IL2CPP) eklentisi, Harmony yamaları. Panel BepInEx'i istemci klasörüne kurar, bu klasördeki
// derlenmiş OpenOrbitPatch.dll'i BepInEx/plugins'e koyar ve Doorstop'u yalnız kendi açtığı istemcide etkinleştirir
// (panel/client_patch.py). İstemcinin kendi dosyaları değişmez, yamalar bellekte. 1.1.115 için yazıldı: bir yamanın hedeflerinden biri
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

[BepInPlugin("openorbit.patch", "OpenOrbit istemci yamaları", "1.0.0")]
public class Plugin : BasePlugin
{
    public override void Load()
    {
        var h = new Harmony("openorbit.patch");
        Apply("müzayede sayacı", () => Auction.Apply(h));
        Apply("rütbe penceresi", () => RankWindow.Apply(h));
        Apply("mağaza tutarı", () => ShopAmount.Apply(h));
        Apply("otomatik pilot kaçışı", () => AutopilotEscape.Apply(h));
        Apply("sohbet moderatörü rengi", () => ModeratorColor.Apply(h));
        Apply("otomatik kuşanma ayarı", () => AutoEquip.Apply(h));
        Apply("görev metinleri", () => QuestTexts.Apply(h));
        Apply("eski yükseltme sistemi", () =>
        {
            OldUpgrade.Apply(h);
            AddComponent<OldUpgradeWatcher>();
        });
        Apply("görsel dökümü", () =>
        {
            ImageDump.Log = Log;
            AddComponent<ImageDump>();
        });
    }

    void Apply(string name, Action patch)
    {
        try
        {
            patch();
            Log.LogInfo("istemci yaması: " + name);
        }
        catch (Exception e)
        {
            Log.LogError("istemci yaması uygulanmadı (" + name + "): " + e);
        }
    }

    // Hedefler bulunmazsa hiçbir şey yamalanmadan hata
    internal static void Find(params MethodBase[] targets)
    {
        if (Array.IndexOf(targets, null) >= 0)
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
static class Auction
{
    static IntPtr last;                  // son kurulan sayacın kapanış nesnesi
    static bool inTab, fromList;      // OnChickBTN sürüyor; onu P1 çağırdı

    internal static void Apply(Harmony h)
    {
        Type s = typeof(UIAuctionSystem), k = typeof(UIAuctionSystem.__c__DisplayClass26_0);
        MethodBase info = AccessTools.Method(s, nameof(UIAuctionSystem.SetAuctionInfo)),
            tab = AccessTools.Method(s, nameof(UIAuctionSystem.OnChickBTN)),
            counter = AccessTools.Method(s, nameof(UIAuctionSystem.StartCountdown)),
            to = AccessTools.Method(typeof(DOTween), nameof(DOTween.To),
                new[] { typeof(DOGetter<int>), typeof(DOSetter<int>), typeof(int), typeof(float) }),
            writer = AccessTools.Method(k, nameof(UIAuctionSystem.__c__DisplayClass26_0._StartCountdown_b__1)),
            end_time = AccessTools.Method(k, nameof(UIAuctionSystem.__c__DisplayClass26_0._StartCountdown_b__2));
        Plugin.Find(info, tab, counter, to, writer, end_time);
        h.Patch(info, prefix: Y(nameof(InfoBefore)), postfix: Y(nameof(InfoAfter)));
        h.Patch(tab, prefix: Y(nameof(TabBefore)), finalizer: Y(nameof(TabAfter)));
        h.Patch(counter, prefix: Y(nameof(CounterBefore)));
        h.Patch(to, prefix: Y(nameof(CounterInstalled)));
        h.Patch(writer, prefix: Y(nameof(OnlyLast)));
        h.Patch(end_time, prefix: Y(nameof(OnlyLast)));
    }

    static HarmonyMethod Y(string name) => new HarmonyMethod(typeof(Auction), name);

    // P1: TabType yoksa (ilk liste) istemcinin kendi yolu (ilk sekme; P5 liste ister); varsa sekmenin sırası (0 saat, 1 gün, 2 hafta)
    static void InfoBefore(UIAuction self, out string __state) => __state = self.TabType;

    static void InfoAfter(UIAuction self, string __state)
    {
        if (__state == null)
            return;
        fromList = true;
        try
        {
            UIAuctionSystem.OnChickBTN(self, true, __state == "day" ? 1 : __state == "week" ? 2 : 0);
        }
        finally
        {
            fromList = false;
        }
    }

    static void TabBefore() => inTab = true;

    static void TabAfter() => inTab = false;

    // P5: OnChickBTN'un içindeki sayaç P1'den geliyorsa kurulur, sekme tıklamasıysa liste istenir (ShowEndTime'ınki değişmez)
    static bool CounterBefore(UIAuction self)
    {
        if (!inTab || fromList)
            return true;
        UIAuctionSystem.RefreshUI(self);
        return false;
    }

    static void CounterInstalled(DOGetter<int> getter)
    {
        var k = getter.Target?.TryCast<UIAuctionSystem.__c__DisplayClass26_0>();
        if (k != null)
            last = k.Pointer;
    }

    static bool OnlyLast(UIAuctionSystem.__c__DisplayClass26_0 __instance) => __instance.Pointer == last;
}

// Rütbe penceresi (Hall of Fame "Your Rank"; kullanıcı bildirimi 2026-10-24: Sergeant olunca da "You currently have the lowest rank."):
//   UIHallOfFameSystem.UpdateDailyRankForServer alt satırı yourRanking'e göre kurar ("hof_your_rank_below" rütbe 2-20, "hof_rank_lowest" 1,
//   "hof_rank_highest" 21) ama sonucu atıp metin dizisine hep GetTextById("hof_rank_lowest") koyar. Dizi birleşip MiddleDesc'e yazılır
//   (ipucu, boş satır, üst rütbe satırı, satır sonu, alt satır, boş satır, ...): R1 metindeki "hof_rank_lowest" satırı kurulan satır olur.
static class RankWindow
{
    internal static void Apply(Harmony h)
    {
        MethodBase target = AccessTools.Method(typeof(UIHallOfFameSystem), nameof(UIHallOfFameSystem.UpdateDailyRankForServer));
        Plugin.Find(target);
        h.Patch(target, postfix: new HarmonyMethod(typeof(RankWindow), nameof(After)));
    }

    static void After(UIHallOfFame self, HallOfFameTopDataListCommand info)
    {
        var p = info.myRankingPoints;
        if (p.yourRanking <= 1)
            return;
        string row = p.yourRanking >= 21 ? LocalizationManager.GetTextById("hof_rank_highest", Category.Resource)
            : LocalizationManager.GetTextById("hof_your_rank_below", Category.Resource)
                .Replace("%RANK_BELOW%", LocalizationManager.GetTextById("rang_" + (p.yourRanking - 1), Category.Resource_system_inc))
                .Replace("%RANKPOINTS_BELOW%", p.belowPoints.ToString());
        var text = self.View.MiddleDescTextMeshProUGUI;
        string old = "\r\n" + LocalizationManager.GetTextById("hof_rank_lowest", Category.Resource) + "\r\n\r\n", t = text.text;
        int i = t.IndexOf(old, StringComparison.Ordinal);
        if (i >= 0)
            text.text = t.Substring(0, i) + "\r\n" + row + "\r\n\r\n" + t.Substring(i + old.Length);
    }
}

// Mağaza tutarı (kullanıcı bildirimi 2026-10-25, CANLI_TEST H233): bedava üründe sunucu price[0]'ı 1e-9 gönderir (magaza.BEDAVA_FIYAT;
//   0 olsa istemci adet seçicili üründe Buy'u kapatıyor). Ürüne tıklanınca toplam kutusu UIShopSystem.ReturnPriceName'den gelir ve fiyatı
//   yuvarlamadan biçimler ("0.000000001 U."); adet değişince istemci tutarı 2 haneye yuvarlıyor (CalculatePurchaseCost: Decimal.Round(x,
//   2, AwayFromZero)). M1: ReturnPriceName'in ReturnCostStr çağrısı aynı yuvarlamadan geçer ("0 U."). Mağazanın öteki fiyatlarında 2
//   haneden fazla ondalık yok: değişmez.
static class ShopAmount
{
    static bool inPrice;                // ReturnPriceName sürüyor

    internal static void Apply(Harmony h)
    {
        MethodBase price = AccessTools.Method(typeof(UIShopSystem), nameof(UIShopSystem.ReturnPriceName)),
            amount = AccessTools.Method(typeof(UIShopSystem), nameof(UIShopSystem.ReturnCostStr));
        Plugin.Find(price, amount);
        h.Patch(price, prefix: Y(nameof(PriceBefore)), finalizer: Y(nameof(PriceAfter)));
        h.Patch(amount, prefix: Y(nameof(AmountBefore)));
    }

    static HarmonyMethod Y(string name) => new HarmonyMethod(typeof(ShopAmount), name);

    static void PriceBefore() => inPrice = true;

    static void PriceAfter() => inPrice = false;

    static void AmountBefore(ref Il2CppSystem.Decimal cost)
    {
        if (inPrice)
            cost = Il2CppSystem.Decimal.Round(cost, 2, Il2CppSystem.MidpointRounding.AwayFromZero);
    }
}

// Otomatik pilot kaçışı (Omega AutoTactic; kullanıcı bildirimi 2026-10-28: uzaylıdan hızlı gemi ateş edemeden sonsuza kaçıyordu):
//   HangUpAI.ExecuteAttackAction hedef attackRange içindeyken ateş eder ve ardından UpdateCloseRangeEscapeMovement'ı çağırır. O, en
//   yakın tehdit attackRange - 5'ten (birden çok tehditte + 45) yakınsa gemiyi tehditten (aralık - uzaklık) + 120 (çok tehditte 250)
//   birim, en az o kadar en çok 650 uzağa kaçırır: kaçış her seferinde menzil + 115 / + 290'da biter, hedef menzil dışına düşer, kovalanır,
//   yine yaklaşınca kaçılır. O1: kaçış hesaplanırken attackRange KACIS_PAYI düşük: kaçış ancak tehdit gerçekten yakınken başlar ve gemiyi
//   menzil içinde (çok tehditte menzil - 10) bırakır; ateş ve kovalama kendi menzille (finalizer geri koyar).
static class AutopilotEscape
{
    const float ESCAPE_MARGIN = 300f;      // 250 kaçış + 45 grup aralığı + 5 pay
    static float reach = -1f;

    internal static void Apply(Harmony h)
    {
        MethodBase target = AccessTools.Method(typeof(HangUpAI), nameof(HangUpAI.UpdateCloseRangeEscapeMovement));
        Plugin.Find(target);
        h.Patch(target, prefix: new HarmonyMethod(typeof(AutopilotEscape), nameof(Once)),
            finalizer: new HarmonyMethod(typeof(AutopilotEscape), nameof(Last)));
    }

    static void Once(HangUpAI __instance)
    {
        reach = __instance.attackRange;
        __instance.attackRange = Math.Max(0f, reach - ESCAPE_MARGIN);
    }

    static void Last(HangUpAI __instance)
    {
        if (reach >= 0f)
            __instance.attackRange = reach;
        reach = -1f;
    }
}

// Sohbet moderatörü rengi (kullanıcı isteği 2026-10-31): sunucunun moderatör botları sohbette "mod" rolüyle ve [CM] etiketiyle yazar
// (server/bot/moderation.py). İstemcinin UIChatSystem.BuildMessageText'i rengi role göre seçer: admin #FF0000 (etiketi gizler, kanal
// yerine "Yönetici" yazar), system gri, chatter firma rengi, öteki roller (mod dahil) #FFFFFF. R1: "mod" rolündeki göndericinin
// satırı RENK ile çizilir; etiket ve kanal adı olduğu gibi kalır ("[Global] [CM] Ad").
static class ModeratorColor
{
    const string ROLE = "mod", COLOR = "#FFC83D", WHITE = "<color=#FFFFFF>";

    internal static void Apply(Harmony h)
    {
        MethodBase target = AccessTools.Method(typeof(UIChatSystem), nameof(UIChatSystem.BuildMessageText));
        Plugin.Find(target);
        h.Patch(target, postfix: new HarmonyMethod(typeof(ModeratorColor), nameof(Last)));
    }

    static void Last(ChatMessageVo message, ref string __result)
    {
        var u = message?.User;
        if (u == null || u.Usertype != ROLE || __result == null)
            return;
        int i = __result.IndexOf(WHITE, StringComparison.Ordinal);
        if (i >= 0)
            __result = __result.Substring(0, i) + "<color=" + COLOR + ">" + __result.Substring(i + WHITE.Length);
    }
}

// Otomatik kuşanma ayarı (kullanıcı bildirimi 2026-10-31: "Auto-equip new items" kapalıyken de ödül eşyaları takılıyordu): Ayarlar >
//   Gameplay'deki kutu (Tog9GameplayToggle) istemcide yalnız etiketle kurulur (UISettingsSystem.InitGameplay; dinleyicisi yok, kaydedilmez,
//   GameplaySettingsRequest'te alanı yok), sunucu ödül ekipmanını boş yuvaya hep takıyordu (magaza._reward). K1: InitGameplay'den sonra
//   kutu PlayerPrefs'teki değerle kurulur (varsayılan açık); değişince kaydedilir. Kurulunca ve değişince sunucuya LegacyModule
//   "AEQ|1" / "AEQ|0" gider (game.py -> profil otomatik_kusan).
static class AutoEquip
{
    const string KEY = "openorbit_autoEquip";

    internal static void Apply(Harmony h)
    {
        MethodBase target = AccessTools.Method(typeof(UISettingsSystem), nameof(UISettingsSystem.InitGameplay));
        Plugin.Find(target);
        h.Patch(target, postfix: new HarmonyMethod(typeof(AutoEquip), nameof(After)));
    }

    static void After(UISettings self)
    {
        var box = self?.View?.Tog9GameplayToggle;
        if (box == null)
            return;
        bool is_open = PlayerPrefs.GetInt(KEY, 1) != 0;
        box.onValueChanged.RemoveAllListeners();
        box.SetIsOnWithoutNotify(is_open);
        box.onValueChanged.AddListener(DelegateSupport.ConvertDelegate<UnityAction<bool>>(new Action<bool>(Changed)));
        Send(is_open);
    }

    static void Changed(bool is_open)
    {
        PlayerPrefs.SetInt(KEY, is_open ? 1 : 0);
        PlayerPrefs.Save();
        Send(is_open);
    }

    static void Send(bool is_open)
    {
        var parts = new Il2CppSystem.Collections.Generic.List<string>();
        parts.Add("AEQ");
        parts.Add(is_open ? "1" : "0");
        NetConnectionHelper.SendLegacyModule(parts);
    }
}
