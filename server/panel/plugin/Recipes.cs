// World Editor recipes (Assembly). The client keeps the recipes in its own code (Recipe.Initialize fills ItemDataProvider.Items): the Assembly window
// takes ingredients, results and build time from there, the server only sends the recipe ids and states. So a world's changed or new recipes are
// sent by the server at login (assembly.client_overrides, before the recipe list) as old-protocol lines, and put into the client's data here:
//   0|OOR|reset                                              the client's own data back (another world may have been played since it started)
//   0|OOR|set|<recipe>|<seconds>|<loot>:<n>,...|<loot>:<n>,...   build time, ingredients, results
// R1: NetConnectionHelper.OnData handles these lines (the client does not know them). An existing recipe's data is replaced (the original is kept for
// reset); an unknown key (recipe_custom_<n>) becomes a new item made after an always-usable game recipe. Its name and picture in the window come from
// its first result.
using System;
using System.Collections.Generic;
using BepInEx.Logging;
using DarkOrbit;
using HarmonyLib;
using Parts = Il2CppSystem.Collections.Generic.List<DarkOrbit.BuildPart>;

namespace OpenOrbit;

static class WorldRecipes
{
    internal static ManualLogSource Log;
    const string PREFIX = "0|OOR|", TEMPLATE = "recipe_blueprint-upgrade-resource-isochronate";

    class Original
    {
        public RecipeAttributes attributes;
        public int seconds;
        public Parts parts, result;
        public bool stackable;
    }

    static readonly Dictionary<string, Original> changed = new();
    static readonly List<string> added = new();

    internal static void Apply(Harmony h)
    {
        var target = AccessTools.Method(typeof(NetConnectionHelper), nameof(NetConnectionHelper.OnData));
        Plugin.Find(target);
        h.Patch(target, prefix: new HarmonyMethod(typeof(WorldRecipes), nameof(Before)));
    }

    static bool Before(string cmd)
    {
        if (cmd == null || !cmd.StartsWith(PREFIX, StringComparison.Ordinal))
            return true;
        try
        {
            var f = cmd.Split('|');
            if (f[2] == "reset")
                Reset();
            else if (f[2] == "set" && f.Length >= 7)
                Set(f[3], int.Parse(f[4]), Read(f[5]), Read(f[6]));
        }
        catch (Exception e)
        {
            Log?.LogError("world recipes (" + cmd + "): " + e);
        }
        return false;
    }

    static Parts Read(string text)
    {
        var list = new Parts();
        foreach (var pair in text.Split(','))
        {
            var p = pair.Split(':');
            var part = new BuildPart();
            part.LootID = p[0];
            part.Ammount = int.Parse(p[1]);
            list.Add(part);
        }
        return list;
    }

    // several at once only for results that stack (the server's rule, worlds.py)
    static bool Stacks(Parts result)
    {
        for (int i = 0; i < result.Count; i++)
        {
            var loot = result[i].LootID;
            if (!loot.StartsWith("ammunition_", StringComparison.Ordinal) && !loot.StartsWith("resource_", StringComparison.Ordinal))
                return false;
        }
        return true;
    }

    static RecipeAttributes Attributes(string key)
    {
        var items = ItemDataProvider.Items;
        return items.ContainsKey(key) ? items[key].Attributes?.TryCast<RecipeAttributes>() : null;
    }

    static void Set(string key, int seconds, Parts parts, Parts result)
    {
        var a = Attributes(key);
        if (a == null)
        {
            if (ItemDataProvider.Items.ContainsKey(key))
                throw new InvalidOperationException(key + " is not a recipe");
            Add(key, seconds, parts, result);
            return;
        }
        var cost = a.Costs[0];
        if (!added.Contains(key) && !changed.ContainsKey(key))
            changed[key] = new Original { attributes = a, seconds = cost.BuildTimeSec, parts = cost.Parts, result = a.Result, stackable = a.Stackable };
        bool sameResult = Same(a.Result, result);
        cost.BuildTimeSec = seconds;
        cost.Parts = parts;
        a.Result = result;
        if (!sameResult)
            a.Stackable = Stacks(result);
        Log?.LogInfo("world recipes: " + key);
    }

    static bool Same(Parts a, Parts b)
    {
        if (a.Count != b.Count)
            return false;
        for (int i = 0; i < a.Count; i++)
            if (a[i].LootID != b[i].LootID || a[i].Ammount != b[i].Ammount)
                return false;
        return true;
    }

    static void Add(string key, int seconds, Parts parts, Parts result)
    {
        var items = ItemDataProvider.Items;
        var model = items[TEMPLATE];
        var from = model.Attributes.Cast<RecipeAttributes>();
        var a = new RecipeAttributes();
        a.LootId = key;
        a.Name = from.Name;
        a.Group = from.Group;
        a.ParentGroup = from.ParentGroup;
        a.TypeClass = from.TypeClass;
        a.TypeValue = from.TypeValue;
        a.IsFractionDependent = from.IsFractionDependent;
        a.Levels = from.Levels;
        a.MaxQuantity = from.MaxQuantity;
        a.Credits = from.Credits;
        a.Uridium = from.Uridium;
        a.Damage = from.Damage;
        a.Abilities = from.Abilities;
        a.CostScalingFactor = from.CostScalingFactor;
        a.MaxUses = from.MaxUses;
        a.UsingStrategy = from.UsingStrategy;
        a.Visibility = from.Visibility;
        a.Targets = from.Targets;
        a.Stackable = Stacks(result);
        a.Result = result;
        var cost = new RecipeCosts();
        cost.BuildTimeSec = seconds;
        cost.Level = from.Costs[0].Level;
        cost.Parts = parts;
        cost.SkipCosts = from.Costs[0].SkipCosts;
        var costs = new Il2CppSystem.Collections.Generic.List<RecipeCosts>();
        costs.Add(cost);
        a.Costs = costs;
        items[key] = new Item(a, model.Traits, model.Levels);
        added.Add(key);
        Log?.LogInfo("world recipes: new " + key);
    }

    static void Reset()
    {
        foreach (var o in changed.Values)
        {
            var cost = o.attributes.Costs[0];
            cost.BuildTimeSec = o.seconds;
            cost.Parts = o.parts;
            o.attributes.Result = o.result;
            o.attributes.Stackable = o.stackable;
        }
        changed.Clear();
        foreach (var key in added)
            ItemDataProvider.Items.Remove(key);
        added.Clear();
    }
}
