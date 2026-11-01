// Client fixes: a BepInEx 6 (IL2CPP) plugin, Harmony patches. The panel installs BepInEx into the client folder, puts the compiled
// OpenOrbitPatch.dll from this folder into BepInEx/plugins and enables Doorstop only in the client it opened itself
// (panel/client_patch.py). The client's own files do not change, the patches are in memory. Written for 1.1.115: if one of a patch's targets
// is not found that patch is not applied at all; the log is BepInEx/LogOutput.log. A user-approved exception to the README's "the client is not patched" rule
// (2026-10-24; the move to BepInEx 2026-10-25).
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

    // If the targets are not found, an error without patching anything
    internal static void Find(params MethodBase[] targets)
    {
        if (Array.IndexOf(targets, null) >= 0)
            throw new MissingMethodException("istemcide beklenen metot yok (1.1.115 değil mi?)");
    }
}

// Auction counter (CANLI_TEST H175; the client's own bug, the server sends the right time in every list):
//   UIAuctionSystem.StartCountdown sets up a new DOTween counter on every call and does not stop the old one; the counters' writer (b__1) writes to the selected tab's field
//   at that moment and to the single time text. The counter is set up only on the window's first list and on a tab click (later lists,
//   refresh and the list the counter asks for when it ends are not set up). Result: when the hourly period ends the daily counter shows on the hourly tab (22:57:22), if no
//   tab was browsed it stays at 00:00:00; a tab click uses the last list's stale time.
//   P1 SetAuctionInfo: in every list the selected tab's counter is set up again with the list's time (OnChickBTN; the tab does not change)
//   P2 DOTween.To: the last counter StartCountdown set up (the closing object) is recorded
//   P3, P4 the counter's writer and its end: if it is not the last counter it does nothing (old counters do not write, do not ask for a list when they end)
//   P5 OnChickBTN: on a tab click, instead of setting up with a stale time it asks for a list (RefreshUI); P1 sets up on the reply
static class Auction
{
    static IntPtr last;                  // the closing object of the last counter set up
    static bool inTab, fromList;      // OnChickBTN is running; P1 called it

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

    // P1: if there is no TabType (first list) the client's own path (first tab; P5 asks for a list); if there is, the tab's order (0 hour, 1 day, 2 week)
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

    // P5: if the counter inside OnChickBTN comes from P1 it is set up, if it is a tab click a list is asked for (ShowEndTime's does not change)
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

// Rank window (Hall of Fame "Your Rank"; user report 2026-10-24: even when becoming Sergeant it said "You currently have the lowest rank."):
//   UIHallOfFameSystem.UpdateDailyRankForServer builds the bottom line according to yourRanking ("hof_your_rank_below" rank 2-20, "hof_rank_lowest" 1,
//   "hof_rank_highest" 21) but throws the result away and always puts GetTextById("hof_rank_lowest") in the text array. The array is joined and written to MiddleDesc
//   (hint, empty line, upper rank line, line break, bottom line, empty line, ...): R1 makes the "hof_rank_lowest" line in the text the line that was built.
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

// Shop amount (user report 2026-10-25, CANLI_TEST H233): for a free item the server sends price[0] as 1e-9 (shop.FREE_PRICE;
//   with 0 the client disables Buy on an item with a quantity selector). When an item is clicked the total box comes from UIShopSystem.ReturnPriceName and formats the price
//   without rounding ("0.000000001 U."); when the quantity changes the client rounds the amount to 2 digits (CalculatePurchaseCost: Decimal.Round(x,
//   2, AwayFromZero)). M1: ReturnPriceName's ReturnCostStr call goes through the same rounding ("0 U."). The shop's other prices have no more than 2
//   decimals: unchanged.
static class ShopAmount
{
    static bool inPrice;                // ReturnPriceName is running

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

// Autopilot escape (Omega AutoTactic; user report 2026-10-28: a ship faster than the alien fled endlessly without being able to fire):
//   HangUpAI.ExecuteAttackAction fires when the target is within attackRange and then calls UpdateCloseRangeEscapeMovement. If the nearest
//   threat is closer than attackRange - 5 (+ 45 with multiple threats) it makes the ship flee from the threat (range - distance) + 120 (250 with multiple threats)
//   units, at least that much, at most 650 away: the escape ends each time at range + 115 / + 290, the target falls out of range, is chased,
//   and when it comes close again it flees. O1: when computing the escape attackRange is KACIS_PAYI lower: the escape starts only when the threat is really close and leaves the ship
//   within range (range - 10 with multiple threats); firing and chasing use their own range (the finalizer puts it back).
static class AutopilotEscape
{
    const float ESCAPE_MARGIN = 300f;      // 250 escape + 45 group gap + 5 margin
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

// Chat moderator color (user request 2026-10-31): the server's moderator bots write in chat with the "mod" role and the [CM] tag
// (server/bot/moderation.py). The client's UIChatSystem.BuildMessageText chooses the color by role: admin #FF0000 (hides the tag, writes "Yönetici"
// instead of the channel), system gray, chatter the company color, other roles (mod included) #FFFFFF. R1: the line of a sender with the "mod" role
// is drawn with COLOR; the tag and channel name stay as they are ("[Global] [CM] Name").
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

// Auto-equip setting (user report 2026-10-31: even with "Auto-equip new items" off, reward items were being fitted): the box in Settings >
//   Gameplay (Tog9GameplayToggle) is set up on the client only with its label (UISettingsSystem.InitGameplay; no listener, not saved,
//   no field in GameplaySettingsRequest), and the server always fitted reward equipment into an empty slot (shop._reward). K1: after InitGameplay
//   the box is set up with the value in PlayerPrefs (default on); it is saved when it changes. When set up and when changed it sends the server a LegacyModule
//   "AEQ|1" / "AEQ|0" (game.py -> player profile auto_equip).
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
