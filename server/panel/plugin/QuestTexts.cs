// The World Editor's quest texts (2026-10-29): the client looks up a quest's title and description by quest id in its own texts
// (DarkOrbit.QuestLocale.GetTitleEx / GetTitle / GetDescriptionEx / GetDescription; Quest.get_Description first
// tries GetLabelEx("quest_description", quest, ...) and if non-empty does not fall to GetDescription); quests added to the world had no text (the title
// line was empty, live 2026-10-28). On PLAY the panel writes the world's quest texts to <client>/BepInEx/openorbit/gorev_metinleri.json:
// {"<quest>": {"title": "...", "description": "..."}} (panel/dunyalar.gorev_metinleri). It is re-read when the file changes (checked at most once
// a second); a quest not in the file and an empty field use the client's own text.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text.Json;
using BepInEx;
using DarkOrbit;
using HarmonyLib;

namespace OpenOrbit;

static class QuestTexts
{
    static readonly Dictionary<int, string> titles = new(), descriptions = new();
    static string route;
    static DateTime lastRead = DateTime.MinValue;
    static long lastCheck;

    internal static void Apply(Harmony h)
    {
        route = Path.Combine(Paths.BepInExRootPath, "openorbit", "quest_texts.json");
        Type t = typeof(QuestLocale);
        MethodBase titleEx = AccessTools.Method(t, "GetTitleEx"), title = AccessTools.Method(t, "GetTitle"),
            descriptionEx = AccessTools.Method(t, "GetDescriptionEx"), description = AccessTools.Method(t, "GetDescription"),
            tag = AccessTools.Method(t, "GetLabelEx");
        Plugin.Find(titleEx, title, descriptionEx, description, tag);
        h.Patch(titleEx, prefix: Y(nameof(Title)));
        h.Patch(title, prefix: Y(nameof(Title)));
        h.Patch(descriptionEx, prefix: Y(nameof(Description)));
        h.Patch(description, prefix: Y(nameof(Description)));
        h.Patch(tag, prefix: Y(nameof(Label)));
    }

    static HarmonyMethod Y(string name) => new HarmonyMethod(typeof(QuestTexts), name);

    static bool Title(int __0, ref string __result) => Give(titles, __0, ref __result);

    static bool Description(int __0, ref string __result) => Give(descriptions, __0, ref __result);

    // GetLabelEx(label, quest, text key, ...): only the description label
    static bool Label(string __0, int __1, ref string __result) => __0 != "quest_description" || Give(descriptions, __1, ref __result);

    static bool Give(Dictionary<int, string> mapping, int quest, ref string result)
    {
        Read();
        if (!mapping.TryGetValue(quest, out var text))
            return true;
        result = text;
        return false;
    }

    static void Read()
    {
        long now = Environment.TickCount64;
        if (now - lastCheck < 1000)
            return;
        lastCheck = now;
        try
        {
            var timestamp = File.Exists(route) ? File.GetLastWriteTimeUtc(route) : DateTime.MinValue;
            if (timestamp == lastRead)
                return;
            lastRead = timestamp;
            titles.Clear();
            descriptions.Clear();
            if (timestamp == DateTime.MinValue)
                return;
            using var doc = JsonDocument.Parse(File.ReadAllText(route));
            foreach (var g in doc.RootElement.EnumerateObject())
            {
                if (!int.TryParse(g.Name, out int uid))
                    continue;
                if (g.Value.TryGetProperty("title", out var b) && b.ValueKind == JsonValueKind.String && b.GetString().Length > 0)
                    titles[uid] = b.GetString();
                if (g.Value.TryGetProperty("description", out var a) && a.ValueKind == JsonValueKind.String && a.GetString().Length > 0)
                    descriptions[uid] = a.GetString();
            }
        }
        catch (Exception e)
        {
            ImageDump.Log?.LogWarning("görev metinleri okunamadı: " + e.Message);
        }
    }
}
