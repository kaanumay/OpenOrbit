// Old upgrade system (panel: eski_yukseltme; user request 2026-10-31): the 2018 Skylab > Tech Factory > Item Upgrading window is
// not in the Unity client; upgrades stay in the Assembly's Upgrade tab, and the cost is uridium only. The client shows the cost from its own recipe
// and checks affordability against it (TargetItemRecipeModel.CollectSteps / GetIngredients: RecipeAttributes.Costs[level].Parts;
// recipes are built in DarkOrbit.Upgrade.Initialize).
// On PLAY and when settings are saved, the panel writes the server's costs (yukseltme.eski_tablo) to <client>/BepInEx/openorbit/eski_yukseltme.json:
// {"upgrade_upgrade-class1": [level 1's U., level 2's U., ...]}; {} when off. E1: once recipes are built, once the recipe model is
// built and before the cost is calculated, the recipe's Parts list is replaced with the uridium from the table (0: free, an empty list); a recipe not in the table returns to the client's
// own ingredients (a new list each time). The skip cost (Isochronate) does not change. The file is checked once a second (OldUpgradeWatcher), and when it changes
// all recipes are adapted at once. The recipe model builds the ingredient rows (Ingredients) in its constructor from the recipe's ingredients at that moment; afterwards
// if the ingredient type changes GetIngredients throws NullReferenceException, the window stays at the old cost (live 2026-11-01: on the switch
// from on to off uridium stayed). So when the setting changes the server resends the recipe list (after 2 s) (yukseltme.Yukseltme.tick):
// the models are rebuilt with the current recipe.
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
    static readonly Dictionary<IntPtr, (string, int)[]> original = new();       // RecipeCosts -> its own ingredients (a new list is built each time)
    static readonly Dictionary<IntPtr, int> applied = new();                                          // RecipeAttributes -> version
    static readonly Dictionary<string, RecipeAttributes> known = new();   // Upgrade.Initialize's recipes: all at once when the file changes
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

// checks the file once a second even while the game is open (so the data is current before the recipe list comes from the server again)
public class OldUpgradeWatcher : UnityEngine.MonoBehaviour
{
    public OldUpgradeWatcher(IntPtr p) : base(p) { }

    void Update() => OldUpgrade.Read();
}
