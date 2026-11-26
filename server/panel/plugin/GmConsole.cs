// GM console (client 1.1.119; user report 2026-11-21: Ctrl+Shift+Z does nothing). Two blocks in the client (found by disassembling GameAssembly.dll):
//   1. ClientDebugHelper.ShowGmWindow (the hotkey's handler) is compiled as an empty "ret" in the release build, and the linker folded it together with ~1750 other
//      empty methods into one shared function. It must NOT be patched (a patch would hit all of them): the hotkey is watched here instead.
//   2. UIComponentSystem.IsAdminToolsDisabled(id) returns true for window 82 (WindowIDAdminTools): the window cannot be shown. G1: it returns false.
// The window itself (UIAdminTools prefab, UIAdminToolsSystem, GmComponentSystem) is intact in the client; the server side is gm_console.py
// (the client treats the player as admin when ShipInitializationCommand.dailyRank is 6000, sent when the panel's "GM console" setting is on).
// Hotkey: hold Ctrl and Shift, press Z (read from the OS, works whatever the client's input handler is). The result is in BepInEx/LogOutput.log.
using System;
using System.Runtime.InteropServices;
using BepInEx.Logging;
using DarkOrbit;
using HarmonyLib;
using UnityEngine;

namespace OpenOrbit;

static class GmConsole
{
    internal static ManualLogSource Log;

    internal static void Apply(Harmony h)
    {
        var target = AccessTools.Method(typeof(UIComponentSystem), nameof(UIComponentSystem.IsAdminToolsDisabled));
        Plugin.Find(target);
        h.Patch(target, prefix: new HarmonyMethod(typeof(GmConsole), nameof(Enable)));
    }

    // G1: the admin window is never "disabled"
    static bool Enable(ref bool __result)
    {
        __result = false;
        return false;
    }

    internal static void Open()
    {
        UIComponent ui = null;
        foreach (var scene in new[] { Game.Scene, Game.ZoneScene })
        {
            if (scene == null)
                continue;
            ui = scene.GetComponent<UIComponent>();
            if (ui != null)
                break;
        }
        if (ui == null)
        {
            Log?.LogWarning("GM konsolu: UIComponent bulunamadı (oyun henüz açılmadı mı?)");
            return;
        }
        if (UIComponentSystem.IsWindowVisible(ui, WindowId.WindowIDAdminTools))
        {
            UIComponentSystem.HideWindow(ui, WindowId.WindowIDAdminTools);
            Log?.LogInfo("GM konsolu: pencere kapatıldı");
            return;
        }
        // The "Quest" and "Box" pages stay grey until the server's CCInitCommand (their value lists) arrives; the request (CCInitRequest) was sent by the
        // original ShowGmWindow, which is empty now: the first time the window is opened it is sent here (gm_console.py answers it).
        SendInit();
        // UIComponentSystem.ShowWindow returns right away for window 82 (and 107): "cmp id, 0x52 / cmp id, 0x6b" is inlined at its start (not the
        // IsAdminToolsDisabled call), so G1 alone is not enough. The two calls ShowWindow makes after that check are made directly.
        var data = new ShowWindowData();
        var baseWindow = UIComponentSystem.ReadyToShowBaseWindow(ui, WindowId.WindowIDAdminTools, data);
        if (baseWindow == null)
        {
            Log?.LogWarning("GM konsolu: ReadyToShowBaseWindow = null (pencere yüklenemedi, istemci günlüğüne bakın)");
            return;
        }
        UIComponentSystem.RealShowWindow(ui, baseWindow, WindowId.WindowIDAdminTools, data);
        Log?.LogInfo("GM konsolu: pencere açıldı");
        Report("hemen");
    }

    static void SendInit()
    {
        try
        {
            GmComponent gm = null;
            foreach (var scene in new[] { Game.Scene, Game.ZoneScene })
            {
                gm = scene?.GetComponent<GmComponent>();
                if (gm != null)
                    break;
            }
            if (gm == null)
            {
                Log?.LogWarning("GM konsolu: GmComponent bulunamadı (Quest/Box listeleri gelmeyecek)");
                return;
            }
            if (gm.IsInit)
                return;
            GmComponentSystem.SendInitRequest(gm);
            Log?.LogInfo("GM konsolu: CCInitRequest gönderildi");
        }
        catch (Exception e)
        {
            Log?.LogError("GM konsolu başlatma isteği: " + e);
        }
    }

    // Diagnostics: what the client has after ShowWindow (right away and a second later; the load may be asynchronous)
    internal static void Report(string when)
    {
        try
        {
            UIComponent ui = null;
            foreach (var scene in new[] { Game.Scene, Game.ZoneScene })
            {
                ui = scene?.GetComponent<UIComponent>();
                if (ui != null)
                    break;
            }
            var w = ui == null ? null : UIComponentSystem.GetUIBaseWindow(ui, WindowId.WindowIDAdminTools);
            if (w == null)
            {
                Log?.LogInfo("GM konsolu [" + when + "]: GetUIBaseWindow = null (pencere hiç oluşmadı)");
                return;
            }
            var go = w.UIPrefabGameObject;
            var tr = w.UITransform;
            Log?.LogInfo("GM konsolu [" + when + "]: IsOpen=" + w.IsOpen + " IsPreLoad=" + w.IsPreLoad + " sorting=" + w.SortingOrder
                + " prefab=" + (go == null ? "null" : go.name + " activeSelf=" + go.activeSelf + " inHierarchy=" + go.activeInHierarchy)
                + " transform=" + (tr == null ? "null" : "pos=" + tr.position + " scale=" + tr.localScale + " parent=" + (tr.parent == null ? "null" : tr.parent.name)));
            if (go != null)
            {
                var canvas = go.GetComponent<Canvas>();
                if (canvas != null)
                    Log?.LogInfo("GM konsolu [" + when + "]: Canvas enabled=" + canvas.enabled + " renderMode=" + canvas.renderMode + " sortingOrder=" + canvas.sortingOrder);
            }
        }
        catch (Exception e)
        {
            Log?.LogError("GM konsolu raporu: " + e);
        }
    }
}

public class GmWatcher : MonoBehaviour
{
    public GmWatcher(IntPtr p) : base(p) { }

    [DllImport("user32.dll")]
    static extern short GetAsyncKeyState(int key);

    const int CTRL = 0x11, SHIFT = 0x10, Z = 0x5A;
    bool was;
    float report = -1f;

    static bool Down(int key) => (GetAsyncKeyState(key) & 0x8000) != 0;

    void Update()
    {
        if (report > 0f && Time.realtimeSinceStartup >= report)
        {
            report = -1f;
            GmConsole.Report("1 sn sonra");
        }
        bool now = Application.isFocused && Down(CTRL) && Down(SHIFT) && Down(Z);
        if (now && !was)
        {
            try
            {
                GmConsole.Open();
                report = Time.realtimeSinceStartup + 1f;
            }
            catch (Exception e)
            {
                GmConsole.Log?.LogError("GM konsolu açılamadı: " + e);
            }
        }
        was = now;
    }
}
