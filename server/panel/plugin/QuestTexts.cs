// Dünya Editörü'nün görev metinleri (2026-10-29): istemci görevin başlığını ve açıklamasını kendi metinlerinden görev kimliğiyle arar
// (DarkOrbit.QuestLocale.GetTitleEx / GetTitle / GetDescriptionEx / GetDescription; Quest.get_Description önce
// GetLabelEx("quest_description", görev, ...) dener, boş değilse GetDescription'a inmez); dünyaya eklenen görevlerin metni yoktu (başlık
// satırı boş, canlı 2026-10-28). Panel OYNA'da dünyanın görev metinlerini <istemci>/BepInEx/openorbit/gorev_metinleri.json'a yazar:
// {"<görev>": {"baslik": "...", "aciklama": "..."}} (panel/dunyalar.gorev_metinleri). Dosya değişince yeniden okunur (en çok saniyede
// bir bakılır); dosyada olmayan görev ve boş alan istemcinin kendi metniyle.
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

    // GetLabelEx(etiket, görev, metin anahtarı, ...): yalnız açıklama etiketi
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
                if (g.Value.TryGetProperty("baslik", out var b) && b.ValueKind == JsonValueKind.String && b.GetString().Length > 0)
                    titles[uid] = b.GetString();
                if (g.Value.TryGetProperty("aciklama", out var a) && a.ValueKind == JsonValueKind.String && a.GetString().Length > 0)
                    descriptions[uid] = a.GetString();
            }
        }
        catch (Exception e)
        {
            ImageDump.Log?.LogWarning("görev metinleri okunamadı: " + e.Message);
        }
    }
}
