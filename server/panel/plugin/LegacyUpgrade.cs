// Eski yükseltme sistemi (panel: eski_yukseltme; kullanıcı isteği 2026-10-31): 2018'in Skylab > Tech Factory > Item Upgrading penceresi
// Unity istemcisinde yok; yükseltmeler Assembly'nin Upgrade sekmesinde kalır, bedeli yalnız uridyum olur. İstemci bedeli kendi tarifinden
// gösterir ve yeterliliği ona göre denetler (TargetItemRecipeModel.CollectSteps / GetIngredients: RecipeAttributes.Costs[seviye].Parts;
// tarifler DarkOrbit.Upgrade.Initialize'da kurulur).
// Panel OYNA'da ve ayarlar kaydedilince sunucunun bedellerini (yukseltme.eski_tablo) <istemci>/BepInEx/openorbit/eski_yukseltme.json'a
// yazar: {"upgrade_upgrade-class1": [seviye 1'in U., seviye 2'nin U., ...]}; kapalıyken {}. E1: tarifler kurulunca, tarif modeli
// kurulunca ve bedel hesaplanmadan önce tarifin Parts listesi tablodaki uridyumla değiştirilir (0: bedava, boş liste); tabloda olmayan tarif istemcinin
// kendi malzemelerine döner (her seferinde yeni liste). Atlama bedeli (Isochronate) değişmez. Dosyaya saniyede bir bakılır (İzci), değişince
// bütün tarifler hemen uyarlanır. Tarif modeli malzeme satırlarını (Ingredients) kurucuda tarifin o anki malzemeleriyle kurar; sonra
// malzeme türü değişirse GetIngredients NullReferenceException atar, pencere eski bedelde kalır (canlı 2026-11-01: açıktan kapalıya
// geçişte uridyum kalıyordu). Bu yüzden sunucu ayar değişince (2 sn sonra) tarif listesini yeniden gönderir (yukseltme.Yukseltme.tick):
// modeller güncel tarifle yeniden kurulur.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.Json;
using BepInEx;
using DarkOrbit;
using HarmonyLib;

namespace OpenOrbit;

static class OldUpgrade
{
    const string URIDIUM = "currency_uridium";
    static readonly Dictionary<string, int[]> table = new();
    static readonly Dictionary<IntPtr, (string, int)[]> original = new();       // RecipeCosts -> kendi malzemeleri (her seferinde yeni liste kurulur)
    static readonly Dictionary<IntPtr, int> applied = new();                                          // RecipeAttributes -> sürüm
    static readonly Dictionary<string, RecipeAttributes> known = new();   // Upgrade.Initialize'ın tarifleri: dosya değişince hepsi hemen
    static string route;
    static DateTime lastRead = DateTime.MinValue;
    static long lastCheck;
    static int version = 1;

    internal static void Apply(Harmony h)
    {
        route = Path.Combine(Paths.BepInExRootPath, "openorbit", "legacy_upgrade.json");
        Type t = typeof(TargetItemRecipeModel);
        MethodBase recipes = AccessTools.Method(typeof(Upgrade), nameof(Upgrade.Initialize));
        MethodBase ctor = AccessTools.Constructor(t, new[] { typeof(ItemVo), typeof(Il2CppSystem.Collections.Generic.List<ItemVo>), typeof(int), typeof(string) }),
            steps = AccessTools.Method(t, nameof(TargetItemRecipeModel.CollectSteps)),
            ingredient = AccessTools.Method(t, nameof(TargetItemRecipeModel.GetIngredients));
        Plugin.Find(recipes, ctor, steps, ingredient);
        h.Patch(recipes, postfix: new HarmonyMethod(typeof(OldUpgrade), nameof(Installed)));
        var y = new HarmonyMethod(typeof(OldUpgrade), nameof(Prepare));
        h.Patch(ctor, postfix: y);
        h.Patch(steps, prefix: y);
        h.Patch(ingredient, prefix: y);
    }

    static void Installed(Il2CppSystem.Collections.Generic.Dictionary<string, Item> items)
    {
        foreach (var kv in items)
            if (kv.Key != null && kv.Key.StartsWith("upgrade_", StringComparison.Ordinal) && kv.Value?.Attributes?.TryCast<RecipeAttributes>() is RecipeAttributes a)
                known[kv.Key] = a;
        Read(true);
        foreach (var kv in known)
            Adapt(kv.Key, kv.Value);
    }

    static void Prepare(TargetItemRecipeModel __instance)
    {
        Read();
        if (__instance != null)
            Adapt(__instance.LootId, __instance.Attribute);
    }

    static void Adapt(string loot, RecipeAttributes a)
    {
        if (a?.Costs == null || (applied.TryGetValue(a.Pointer, out int s) && s == version))
            return;
        applied[a.Pointer] = version;
        table.TryGetValue(loot ?? "", out var cost);
        foreach (var c in a.Costs)
        {
            if (!original.TryGetValue(c.Pointer, out var own))
            {
                own = new (string, int)[c.Parts.Count];
                for (int j = 0; j < own.Length; j++)
                    own[j] = (c.Parts[j].LootID, c.Parts[j].Ammount);
                original[c.Pointer] = own;
            }
            int i = c.Level - 1;
            var new_ = new Il2CppSystem.Collections.Generic.List<BuildPart>();
            if (cost == null || i < 0 || i >= cost.Length)
                foreach (var (l, n) in own)
                    new_.Add(Part(l, n));
            else if (cost[i] > 0)
                new_.Add(Part(URIDIUM, cost[i]));
            c.Parts = new_;
        }
    }

    static BuildPart Part(string loot, int n)
    {
        var p = new BuildPart();
        p.LootID = loot;
        p.Ammount = n;
        return p;
    }

    internal static void Read(bool immediate = false)
    {
        long now = Environment.TickCount64;
        if (!immediate && now - lastCheck < 1000)
            return;
        lastCheck = now;
        var timestamp = File.Exists(route) ? File.GetLastWriteTimeUtc(route) : DateTime.MinValue;
        if (timestamp == lastRead)
            return;
        lastRead = timestamp;
        version++;
        table.Clear();
        if (timestamp != DateTime.MinValue)
            Load();
        foreach (var kv in known)
            Adapt(kv.Key, kv.Value);
    }

    static void Load()
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(route));
            foreach (var g in doc.RootElement.EnumerateObject())
            {
                if (g.Value.ValueKind != JsonValueKind.Array)
                    continue;
                var d = new int[g.Value.GetArrayLength()];
                int i = 0;
                foreach (var n in g.Value.EnumerateArray())
                    d[i++] = n.TryGetInt32(out int x) ? x : 0;
                table[g.Name] = d;
            }
        }
        catch (Exception e)
        {
            ImageDump.Log?.LogWarning("eski yükseltme bedelleri okunamadı: " + e.Message);
        }
    }
}

// dosyaya oyun açıkken de saniyede bir bakar (tarif listesi sunucudan yeniden gelmeden önce veri güncel olsun)
public class OldUpgradeWatcher : UnityEngine.MonoBehaviour
{
    public OldUpgradeWatcher(IntPtr p) : base(p) { }

    void Update() => OldUpgrade.Read();
}
