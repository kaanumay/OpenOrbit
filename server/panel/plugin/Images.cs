// Oyun içi görsellerin dökümü (panelin Mağaza / Hangar / Skylab sayfaları; kullanıcı isteği 2026-10-28): simgeler istemcinin
// Addressables paketindeki sprite atlaslarında (StreamingAssets/aa/BuildTarget/atlas_assets_all.bundle; dokular Crunch / BC7, Python'la
// çözülemiyor). İstemci açılınca atlas sayfaları bir kez Unity'nin kendisiyle PNG'ye çevrilir: <istemci>/BepInEx/openorbit/images/
// (oyunun telifli görselleri: depoya girmez, istemci klasörü .gitignore'da). dizin.json en son yazılır: sprite adı -> [sayfa, x, y, g, y,
// tam g, tam y, ox, oy] (üst sol kökenli piksel; atlaslar dikdörtgen paketli, döndürme yok). Paketin boyutu ve tarihi değişmedikçe
// (ve atlas listesi) değişmedikçe yeniden dökülmez. Atlasın sprite'ları geç bağlanıyor (Sprite.texture boş): sayfalar SpriteAtlas.GetSprites'ın kopyalarından.
// Eşya adları da panelin dillerinde: adlar_<dil>.json (lootId -> ad; istemcinin resource_items'ındaki items_<lootId>_fullname).
// Panelin eşya ipucunun metinleri: metinler_<dil>.json {"e": {lootId: [ad, tür, ipucu açıklaması, açıklama, not, kaynak]},
// "n": {nitelik: ad}} (items_<lootId>_fullname/_short/_tooltip_description/_description/_hint/_sources; nitelik adları
// items_equipment_shipupgrade_modifiertype_<nitelik>: kararsız modül, QFC ve parçacık silahı nitelikleri).
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using BepInEx;
using UnityEngine;
using UnityEngine.U2D;
using DarkOrbit;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;

namespace OpenOrbit;

public class ImageDump : MonoBehaviour
{
    public ImageDump(IntPtr p) : base(p) { }

    static readonly string[] ATLASES = { "Items", "hanger", "Shop", "UI", "CommonUI", "Misc", "Boosters", "FeatureMenu" };
    static readonly string[] LANGUAGES = { "tr", "en", "de", "es", "fr", "pl", "pt", "ru" };     // panelin dilleri (panel/lang.py)

    internal static BepInEx.Logging.ManualLogSource Log;
    static string folder, version;
    static readonly Queue<Texture2D> pages = new();
    static readonly StringBuilder index = new();
    static readonly StringBuilder sizes = new();
    static int state;                   // 0 bekliyor, 1 sayfalar yazılıyor, 2 bitti

    void Update()
    {
        if (state == 2 || Time.realtimeSinceStartup < 5f)
            return;
        try
        {
            if (state == 0)
                Start();
            else if (pages.Count > 0)
                Write(pages.Dequeue());
            else
                Finish();
        }
        catch (Exception e)
        {
            state = 2;
            Log.LogError("görsel dökümü: " + e);
        }
    }

    static void Start()
    {
        folder = Path.Combine(Paths.BepInExRootPath, "openorbit", "gorsel");
        var fi = new FileInfo(Path.Combine(Application.streamingAssetsPath, "aa", "BuildTarget", "atlas_assets_all.bundle"));
        version = fi.Length + "-" + fi.LastWriteTimeUtc.Ticks + "-" + string.Join(",", ATLASES) + "-metin1";   // atlas listesi ya da döküm biçimi değişince de yeniden
        string d = Path.Combine(folder, "dizin.json");
        if (File.Exists(d) && File.ReadAllText(d).Contains("\"surum\": \"" + version + "\""))
        {
            state = 2;
            return;
        }
        Directory.CreateDirectory(folder);
        var names = new HashSet<string>();
        Package("atlas_assets_all", "Assets/Res/UI/Images/Atlas/Items.spriteatlas", ab => Atlases(ab, names));
        Package("localizations_assets_all", "Assets/Res/Localization/Data/en/data/resource_items.asset", Names);
        Log.LogInfo($"görsel dökümü: {names.Count} sprite, {pages.Count} sayfa -> {folder}");
        state = 1;
    }

    // Addressables yüklediyse (paketin yüklü adı dosyanınki değil: içindeki bir varlıkla bulunur) o; yoksa biz yükler, işimiz bitince
    // bırakırız (sonra o yükleyebilsin; dokular bellekte kalır)
    static void Package(string name, string asset, Action<AssetBundle> job)
    {
        AssetBundle ab = null;
        foreach (var b in AssetBundle.GetAllLoadedAssetBundles_Native())
            if (b != null && b.Contains(asset))
                ab = b;
        bool ours = ab == null;
        if (ours)
            ab = AssetBundle.LoadFromFile(Path.Combine(Application.streamingAssetsPath, "aa", "BuildTarget", name + ".bundle"));
        if (ab == null)
            throw new FileLoadException("paket yüklenemedi: " + name);
        try
        {
            job(ab);
        }
        finally
        {
            if (ours)
                ab.Unload(false);
        }
    }

    static void Atlases(AssetBundle ab, HashSet<string> names)
    {
        var seen = new HashSet<IntPtr>();
        foreach (var o in ab.LoadAllAssets(Il2CppType.Of<SpriteAtlas>()))
        {
            var atlas = o.Cast<SpriteAtlas>();
            if (Array.IndexOf(ATLASES, atlas.name) < 0)
                continue;
            var arr = new Il2CppReferenceArray<Sprite>(atlas.spriteCount);
            atlas.GetSprites(arr);
            foreach (var s in arr)
            {
                var t = s.texture;
                string name = s.name.Replace("(Clone)", "");
                if (t != null && names.Add(name))
                {
                    if (seen.Add(t.Pointer))
                    {
                        pages.Enqueue(t);
                        sizes.Append(sizes.Length > 0 ? ",\n" : "").Append($"  \"{t.name}\": [{t.width}, {t.height}]");
                    }
                    Rect r = s.textureRect, full = s.rect;
                    Vector2 off = s.textureRectOffset;
                    index.Append(index.Length > 0 ? ",\n" : "").Append(
                        $"  \"{Escape(name)}\": [\"{t.name}\", {Y(r.x)}, {Y(t.height - r.y - r.height)}, {Y(r.width)}, {Y(r.height)}, "
                        + $"{Y(full.width)}, {Y(full.height)}, {Y(off.x)}, {Y(full.height - off.y - r.height)}]");
                }
                UnityEngine.Object.Destroy(s);
            }
        }
    }

    static void Names(AssetBundle ab)
    {
        foreach (var lang in LANGUAGES)
        {
            var o = ab.LoadAsset("Assets/Res/Localization/Data/" + lang + "/data/resource_items.asset", Il2CppType.Of<LocalizationContainer>());
            if (o == null)
                continue;
            var sb = new StringBuilder();
            var item = new SortedDictionary<string, string[]>(StringComparer.Ordinal);
            var attribute = new StringBuilder();
            foreach (var kv in o.Cast<LocalizationContainer>().data)
            {
                if (!kv.key.StartsWith("items_"))
                    continue;
                if (kv.key.EndsWith("_fullname"))
                    sb.Append(sb.Length > 0 ? ",\n" : "").Append($"  \"{Escape(kv.key[6..^9])}\": \"{Escape(kv.value)}\"");
                if (kv.key.StartsWith(ATTRIBUTE))
                {
                    attribute.Append(attribute.Length > 0 ? ",\n" : "").Append($"  \"{Escape(kv.key[ATTRIBUTE.Length..])}\": \"{Escape(kv.value)}\"");
                    continue;
                }
                for (int i = 0; i < SUFFIXES.Length; i++)
                    if (kv.key.EndsWith(SUFFIXES[i]))
                    {
                        string loot = kv.key[6..^SUFFIXES[i].Length];
                        if (!item.TryGetValue(loot, out var m))
                            item[loot] = m = new string[SUFFIXES.Length];
                        m[i] = kv.value;
                        break;
                    }
            }
            File.WriteAllText(Path.Combine(folder, "adlar_" + lang + ".json"), "{\n" + sb + "\n}\n");
            var mb = new StringBuilder();
            foreach (var kv in item)
                mb.Append(mb.Length > 0 ? ",\n" : "").Append($"  \"{Escape(kv.Key)}\": [")
                  .Append(string.Join(", ", Array.ConvertAll(kv.Value, v => v == null ? "null" : "\"" + Escape(v) + "\""))).Append(']');
            File.WriteAllText(Path.Combine(folder, "metinler_" + lang + ".json"), "{\"e\": {\n" + mb + "\n},\n\"n\": {\n" + attribute + "\n}}\n");
        }
    }

    // ipucu metinleri, metinler_<dil>.json'daki sırayla; _tooltip_description _description'dan önce denenir (ikisi de _description ile biter)
    static readonly string[] SUFFIXES = { "_fullname", "_short", "_tooltip_description", "_description", "_hint", "_sources" };
    const string ATTRIBUTE = "items_equipment_shipupgrade_modifiertype_";

    static void Write(Texture2D t)
    {
        var rt = RenderTexture.GetTemporary(t.width, t.height, 0, RenderTextureFormat.ARGB32, RenderTextureReadWrite.sRGB);
        var once = RenderTexture.active;
        Graphics.Blit(t, rt);
        RenderTexture.active = rt;
        var output = new Texture2D(t.width, t.height, TextureFormat.RGBA32, false);
        output.ReadPixels(new Rect(0, 0, t.width, t.height), 0, 0);
        output.Apply(false);
        RenderTexture.active = once;
        RenderTexture.ReleaseTemporary(rt);
        File.WriteAllBytes(Path.Combine(folder, t.name + ".png"), ImageConversion.EncodeToPNG(output));
        UnityEngine.Object.Destroy(output);
    }

    static void Finish()
    {
        string d = Path.Combine(folder, "dizin.json");
        File.WriteAllText(d + ".tmp", "{\"surum\": \"" + version + "\",\n\"sayfalar\": {\n" + sizes + "\n},\n\"sprite\": {\n" + index + "\n}}\n");
        File.Move(d + ".tmp", d, true);
        index.Clear();
        sizes.Clear();
        Resources.UnloadUnusedAssets();
        state = 2;
        Log.LogInfo("görsel dökümü bitti");
    }

    static string Y(float v) => Math.Round(v).ToString(System.Globalization.CultureInfo.InvariantCulture);

    static string Escape(string s) => s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "").Replace("\t", " ");
}
