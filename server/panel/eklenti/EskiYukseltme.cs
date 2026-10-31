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

static class EskiYukseltme
{
    const string URIDYUM = "currency_uridium";
    static readonly Dictionary<string, int[]> tablo = new();
    static readonly Dictionary<IntPtr, (string, int)[]> asil = new();       // RecipeCosts -> kendi malzemeleri (her seferinde yeni liste kurulur)
    static readonly Dictionary<IntPtr, int> uygulanan = new();                                          // RecipeAttributes -> sürüm
    static readonly Dictionary<string, RecipeAttributes> bilinen = new();   // Upgrade.Initialize'ın tarifleri: dosya değişince hepsi hemen
    static string yol;
    static DateTime okunan = DateTime.MinValue;
    static long bakilan;
    static int surum = 1;

    internal static void Uygula(Harmony h)
    {
        yol = Path.Combine(Paths.BepInExRootPath, "openorbit", "eski_yukseltme.json");
        Type t = typeof(TargetItemRecipeModel);
        MethodBase tarifler = AccessTools.Method(typeof(Upgrade), nameof(Upgrade.Initialize));
        MethodBase kur = AccessTools.Constructor(t, new[] { typeof(ItemVo), typeof(Il2CppSystem.Collections.Generic.List<ItemVo>), typeof(int), typeof(string) }),
            adimlar = AccessTools.Method(t, nameof(TargetItemRecipeModel.CollectSteps)),
            malzeme = AccessTools.Method(t, nameof(TargetItemRecipeModel.GetIngredients));
        Eklenti.Bul(tarifler, kur, adimlar, malzeme);
        h.Patch(tarifler, postfix: new HarmonyMethod(typeof(EskiYukseltme), nameof(Kuruldu)));
        var y = new HarmonyMethod(typeof(EskiYukseltme), nameof(Hazirla));
        h.Patch(kur, postfix: y);
        h.Patch(adimlar, prefix: y);
        h.Patch(malzeme, prefix: y);
    }

    static void Kuruldu(Il2CppSystem.Collections.Generic.Dictionary<string, Item> items)
    {
        foreach (var kv in items)
            if (kv.Key != null && kv.Key.StartsWith("upgrade_", StringComparison.Ordinal) && kv.Value?.Attributes?.TryCast<RecipeAttributes>() is RecipeAttributes a)
                bilinen[kv.Key] = a;
        Oku(true);
        foreach (var kv in bilinen)
            Uyarla(kv.Key, kv.Value);
    }

    static void Hazirla(TargetItemRecipeModel __instance)
    {
        Oku();
        if (__instance != null)
            Uyarla(__instance.LootId, __instance.Attribute);
    }

    static void Uyarla(string loot, RecipeAttributes a)
    {
        if (a?.Costs == null || (uygulanan.TryGetValue(a.Pointer, out int s) && s == surum))
            return;
        uygulanan[a.Pointer] = surum;
        tablo.TryGetValue(loot ?? "", out var bedel);
        foreach (var c in a.Costs)
        {
            if (!asil.TryGetValue(c.Pointer, out var kendi))
            {
                kendi = new (string, int)[c.Parts.Count];
                for (int j = 0; j < kendi.Length; j++)
                    kendi[j] = (c.Parts[j].LootID, c.Parts[j].Ammount);
                asil[c.Pointer] = kendi;
            }
            int i = c.Level - 1;
            var yeni = new Il2CppSystem.Collections.Generic.List<BuildPart>();
            if (bedel == null || i < 0 || i >= bedel.Length)
                foreach (var (l, n) in kendi)
                    yeni.Add(Parca(l, n));
            else if (bedel[i] > 0)
                yeni.Add(Parca(URIDYUM, bedel[i]));
            c.Parts = yeni;
        }
    }

    static BuildPart Parca(string loot, int n)
    {
        var p = new BuildPart();
        p.LootID = loot;
        p.Ammount = n;
        return p;
    }

    internal static void Oku(bool hemen = false)
    {
        long simdi = Environment.TickCount64;
        if (!hemen && simdi - bakilan < 1000)
            return;
        bakilan = simdi;
        var zaman = File.Exists(yol) ? File.GetLastWriteTimeUtc(yol) : DateTime.MinValue;
        if (zaman == okunan)
            return;
        okunan = zaman;
        surum++;
        tablo.Clear();
        if (zaman != DateTime.MinValue)
            Yukle();
        foreach (var kv in bilinen)
            Uyarla(kv.Key, kv.Value);
    }

    static void Yukle()
    {
        try
        {
            using var belge = JsonDocument.Parse(File.ReadAllText(yol));
            foreach (var g in belge.RootElement.EnumerateObject())
            {
                if (g.Value.ValueKind != JsonValueKind.Array)
                    continue;
                var d = new int[g.Value.GetArrayLength()];
                int i = 0;
                foreach (var n in g.Value.EnumerateArray())
                    d[i++] = n.TryGetInt32(out int x) ? x : 0;
                tablo[g.Name] = d;
            }
        }
        catch (Exception e)
        {
            GorselDokumu.Log?.LogWarning("eski yükseltme bedelleri okunamadı: " + e.Message);
        }
    }
}

// dosyaya oyun açıkken de saniyede bir bakar (tarif listesi sunucudan yeniden gelmeden önce veri güncel olsun)
public class EskiYukseltmeIzci : UnityEngine.MonoBehaviour
{
    public EskiYukseltmeIzci(IntPtr p) : base(p) { }

    void Update() => EskiYukseltme.Oku();
}
