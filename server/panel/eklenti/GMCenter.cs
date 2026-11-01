// Lightweight in-game GM Center overlay.
// The overlay is intentionally idle while closed. Network work runs asynchronously;
// Unity GUI and all Unity object access stay on the main thread.
using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using BepInEx;
using UnityEngine;

namespace OpenOrbit;

public sealed class GMCenterOverlay : MonoBehaviour
{
    sealed class PlayerRow
    {
        public string Uid = "", Name = "", MapName = "", Ship = "";
        public int Level, Credits, Uridium, Ep, Honour;
        public bool Online;
    }

    sealed class GateRow
    {
        public string Key = "", Name = "", Status = "", Reason = "";
        public int GateId, Parts, Required, TimeLeft;
        public bool CanSend, CanCollect, Built;
    }

    enum Page { Dashboard, Players, Dispatch, Commands, Logs }

    static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(4) };
    readonly object sync = new();
    readonly List<PlayerRow> players = new();
    readonly List<GateRow> gates = new();

    Rect window = new(0, 0, 1120, 720);
    Vector2 playerScroll, gateScroll, logScroll;
    Page page;
    string token = "", api = "http://127.0.0.1:8098";
    string selectedUid = "", selectedName = "";
    string notice = "GM Center gotowy do połączenia.";
    string error = "";
    bool open, connecting, busy;
    bool oldCursorVisible;
    CursorLockMode oldCursorLock;
    float nextRefresh;

    public GMCenterOverlay(IntPtr ptr) : base(ptr) { }

    void Update()
    {
        if (Input.GetKeyDown(KeyCode.F10))
            SetOpen(!open);

        if (!open)
            return;

        if (Input.GetKeyDown(KeyCode.Escape))
        {
            SetOpen(false);
            return;
        }

        if (string.IsNullOrEmpty(token) && !connecting && Time.unscaledTime >= nextRefresh)
        {
            nextRefresh = Time.unscaledTime + 2f;
            _ = ConnectAsync();
        }
        else if (!busy && !string.IsNullOrEmpty(token) && Time.unscaledTime >= nextRefresh)
        {
            nextRefresh = Time.unscaledTime + 4f;
            if (page == Page.Players || page == Page.Dashboard)
                _ = LoadPlayersAsync();
            else if (page == Page.Dispatch && !string.IsNullOrEmpty(selectedUid))
                _ = LoadGatesAsync();
        }
    }

    void SetOpen(bool value)
    {
        if (open == value)
            return;
        open = value;
        if (open)
        {
            oldCursorVisible = Cursor.visible;
            oldCursorLock = Cursor.lockState;
            Cursor.lockState = CursorLockMode.None;
            Cursor.visible = true;
            window.x = Math.Max(8, (Screen.width - window.width) * 0.5f);
            window.y = Math.Max(8, (Screen.height - window.height) * 0.5f);
            nextRefresh = 0;
        }
        else
        {
            Cursor.lockState = oldCursorLock;
            Cursor.visible = oldCursorVisible;
        }
    }

    void OnDestroy()
    {
        if (open)
        {
            Cursor.lockState = oldCursorLock;
            Cursor.visible = oldCursorVisible;
        }
    }

    async Task<string> RequestAsync(string method, string path, object body = null, bool bootstrap = false)
    {
        using var request = new HttpRequestMessage(new HttpMethod(method), api + path);
        if (!bootstrap)
        {
            if (string.IsNullOrEmpty(token))
                throw new InvalidOperationException("Brak tokenu GM. Włącz GM konsolę w ustawieniach deweloperskich.");
            request.Headers.Add("X-Anahtar", token);
        }
        if (body != null)
            request.Content = new StringContent(JsonSerializer.Serialize(body), Encoding.UTF8, "application/json");

        using var response = await Http.SendAsync(request);
        var content = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode)
            throw new InvalidOperationException(content);
        return content;
    }

    async Task ConnectAsync()
    {
        connecting = true;
        try
        {
            string json = await RequestAsync("GET", "/gm/bootstrap", null, true);
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            token = Text(root, "token");
            int port = Number(root, "port");
            if (port > 0)
                api = "http://127.0.0.1:" + port;
            if (string.IsNullOrEmpty(token))
                throw new InvalidOperationException("Serwer nie zwrócił tokenu GM.");
            error = "";
            notice = "Połączono z lokalnym serwerem OpenOrbit.";
            await LoadPlayersAsync();
        }
        catch (Exception e)
        {
            error = "Nie można połączyć GM Center: " + e.Message;
            notice = "Sprawdź, czy serwer działa i czy włączono Geliştirici > GM konsolu.";
        }
        finally
        {
            connecting = false;
        }
    }

    async Task LoadPlayersAsync()
    {
        if (busy || string.IsNullOrEmpty(token))
            return;
        busy = true;
        try
        {
            string json = await RequestAsync("GET", "/gm/players");
            using var doc = JsonDocument.Parse(json);
            var fresh = new List<PlayerRow>();
            if (doc.RootElement.TryGetProperty("players", out var list))
            {
                foreach (var item in list.EnumerateArray())
                {
                    fresh.Add(new PlayerRow
                    {
                        Uid = Text(item, "uid"),
                        Name = Text(item, "name"),
                        MapName = Text(item, "map_name"),
                        Ship = Text(item, "ship"),
                        Level = Number(item, "level"),
                        Credits = Number(item, "credits"),
                        Uridium = Number(item, "uridium"),
                        Ep = Number(item, "ep"),
                        Honour = Number(item, "honour"),
                        Online = Flag(item, "online")
                    });
                }
            }
            lock (sync)
            {
                players.Clear();
                players.AddRange(fresh);
                if (string.IsNullOrEmpty(selectedUid) && players.Count > 0)
                {
                    selectedUid = players[0].Uid;
                    selectedName = players[0].Name;
                }
            }
            error = "";
        }
        catch (Exception e)
        {
            error = "Błąd listy graczy: " + e.Message;
        }
        finally
        {
            busy = false;
        }
    }

    async Task LoadGatesAsync()
    {
        if (busy || string.IsNullOrEmpty(token) || string.IsNullOrEmpty(selectedUid))
            return;
        busy = true;
        try
        {
            string path = "/gm/dispatch/gates?uid=" + Uri.EscapeDataString(selectedUid);
            string json = await RequestAsync("GET", path);
            using var doc = JsonDocument.Parse(json);
            var fresh = new List<GateRow>();
            if (doc.RootElement.TryGetProperty("gates", out var list))
            {
                foreach (var item in list.EnumerateArray())
                {
                    fresh.Add(new GateRow
                    {
                        Key = Text(item, "key"),
                        Name = Text(item, "name"),
                        Status = Text(item, "status"),
                        Reason = Text(item, "reason"),
                        GateId = Number(item, "gate_id"),
                        Parts = Number(item, "parts"),
                        Required = Number(item, "required"),
                        TimeLeft = Number(item, "time_left"),
                        CanSend = Flag(item, "can_send"),
                        CanCollect = Flag(item, "can_collect"),
                        Built = Flag(item, "built")
                    });
                }
            }
            lock (sync)
            {
                gates.Clear();
                gates.AddRange(fresh);
            }
            error = "";
        }
        catch (Exception e)
        {
            error = "Błąd listy wrót: " + e.Message;
        }
        finally
        {
            busy = false;
        }
    }

    async Task DispatchActionAsync(GateRow gate, string action)
    {
        if (busy || gate == null)
            return;
        busy = true;
        try
        {
            var payload = new Dictionary<string, object>
            {
                ["uid"] = selectedUid,
                ["gateId"] = gate.GateId,
                ["action"] = action
            };
            string json = await RequestAsync("POST", "/gm/dispatch/gate", payload);
            using var doc = JsonDocument.Parse(json);
            bool ok = Flag(doc.RootElement, "tamam");
            notice = ok
                ? (action == "send" ? "Wrota wysłane do Dispatch." : "Nagroda Dispatch odebrana.")
                : "Serwer odrzucił operację. Sprawdź warunki i logi.";
            error = "";
        }
        catch (Exception e)
        {
            error = "Operacja Dispatch nie powiodła się: " + e.Message;
        }
        finally
        {
            busy = false;
        }
        await LoadGatesAsync();
    }

    static string Text(JsonElement e, string key)
    {
        if (!e.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null)
            return "";
        return value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : value.ToString();
    }

    static int Number(JsonElement e, string key)
    {
        if (!e.TryGetProperty(key, out var value) || value.ValueKind == JsonValueKind.Null)
            return 0;
        return value.ValueKind == JsonValueKind.Number && value.TryGetInt32(out int n)
            ? n : int.TryParse(value.ToString(), out n) ? n : 0;
    }

    static bool Flag(JsonElement e, string key)
    {
        return e.TryGetProperty(key, out var value) &&
               (value.ValueKind == JsonValueKind.True || (value.ValueKind == JsonValueKind.String && value.GetString() == "true"));
    }

    void OnGUI()
    {
        if (!open)
            return;

        Color oldBg = GUI.backgroundColor;
        Color oldContent = GUI.contentColor;
        GUI.backgroundColor = new Color(0.035f, 0.075f, 0.12f, 0.98f);
        GUI.contentColor = new Color(0.86f, 0.94f, 1f, 1f);

        window.width = Mathf.Clamp(window.width, 720, Math.Max(720, Screen.width - 16));
        window.height = Mathf.Clamp(window.height, 500, Math.Max(500, Screen.height - 16));
        window = GUI.Window(817240, window, DrawWindow, "OPENORBIT  //  GM CENTER");

        GUI.backgroundColor = oldBg;
        GUI.contentColor = oldContent;
    }

    void DrawWindow(int id)
    {
        GUILayout.BeginVertical();
        GUILayout.BeginHorizontal();
        GUILayout.Label("ADMINISTRATOR CONTROL SYSTEM", GUILayout.ExpandWidth(true));
        GUILayout.Label(string.IsNullOrEmpty(token) ? "● OFFLINE" : "● CONNECTED", GUILayout.Width(115));
        if (GUILayout.Button("X", GUILayout.Width(34)))
            SetOpen(false);
        GUILayout.EndHorizontal();

        GUILayout.Space(8);
        GUILayout.BeginHorizontal(GUILayout.ExpandHeight(true));

        GUILayout.BeginVertical(GUI.skin.box, GUILayout.Width(185), GUILayout.ExpandHeight(true));
        NavButton("OVERVIEW", Page.Dashboard);
        NavButton("PLAYERS", Page.Players);
        NavButton("DISPATCH / GATES", Page.Dispatch);
        NavButton("GM COMMANDS", Page.Commands);
        NavButton("ACTIVITY LOG", Page.Logs);
        GUILayout.FlexibleSpace();
        GUILayout.Label("F10  ·  Toggle GM Center");
        GUILayout.EndVertical();

        GUILayout.BeginVertical(GUILayout.ExpandWidth(true), GUILayout.ExpandHeight(true));
        if (page == Page.Dashboard)
            DrawDashboard();
        else if (page == Page.Players)
            DrawPlayers();
        else if (page == Page.Dispatch)
            DrawDispatch();
        else if (page == Page.Commands)
            DrawCommands();
        else
            DrawLogs();
        GUILayout.EndVertical();

        GUILayout.EndHorizontal();
        GUILayout.Space(5);
        GUILayout.BeginHorizontal();
        GUILayout.Label(string.IsNullOrEmpty(error) ? notice : error, GUILayout.ExpandWidth(true));
        if (GUILayout.Button("REFRESH", GUILayout.Width(100)))
        {
            if (string.IsNullOrEmpty(token))
                _ = ConnectAsync();
            else if (page == Page.Dispatch)
                _ = LoadGatesAsync();
            else
                _ = LoadPlayersAsync();
        }
        GUILayout.EndHorizontal();
        GUILayout.EndVertical();
        GUI.DragWindow(new Rect(0, 0, window.width, 34));
    }

    void NavButton(string label, Page target)
    {
        Color old = GUI.backgroundColor;
        GUI.backgroundColor = page == target
            ? new Color(0.05f, 0.36f, 0.52f, 1f)
            : new Color(0.08f, 0.15f, 0.22f, 1f);
        if (GUILayout.Button(label, GUILayout.Height(38)))
        {
            page = target;
            if (page == Page.Players || page == Page.Dashboard)
                _ = LoadPlayersAsync();
            if (page == Page.Dispatch)
                _ = LoadGatesAsync();
        }
        GUI.backgroundColor = old;
    }

    void DrawDashboard()
    {
        GUILayout.Label("SERVER OVERVIEW");
        GUILayout.Space(8);
        int count;
        lock (sync) count = players.Count;
        GUILayout.BeginHorizontal();
        Metric("PLAYERS", count.ToString());
        Metric("SELECTED", string.IsNullOrEmpty(selectedName) ? "—" : selectedName);
        Metric("API", string.IsNullOrEmpty(token) ? "Disconnected" : "127.0.0.1");
        GUILayout.EndHorizontal();
        GUILayout.Space(12);
        GUILayout.BeginVertical(GUI.skin.box);
        GUILayout.Label("QUICK ACCESS");
        if (GUILayout.Button("Open player management", GUILayout.Height(36)))
            page = Page.Players;
        if (GUILayout.Button("Open Dispatch and gate diagnostics", GUILayout.Height(36)))
        {
            page = Page.Dispatch;
            _ = LoadGatesAsync();
        }
        GUILayout.EndVertical();
        GUILayout.Space(8);
        GUILayout.Label("The original GM console remains available with Ctrl + Shift + Z.");
        GUILayout.Label("This overlay is the new host-only administration interface.");
    }

    void Metric(string label, string value)
    {
        GUILayout.BeginVertical(GUI.skin.box, GUILayout.ExpandWidth(true), GUILayout.Height(78));
        GUILayout.Label(label);
        GUILayout.Label(value);
        GUILayout.EndVertical();
    }

    void DrawPlayers()
    {
        GUILayout.Label("CONNECTED AND KNOWN PLAYERS");
        GUILayout.BeginHorizontal(GUILayout.ExpandHeight(true));
        GUILayout.BeginVertical(GUI.skin.box, GUILayout.Width(330), GUILayout.ExpandHeight(true));
        playerScroll = GUILayout.BeginScrollView(playerScroll);
        lock (sync)
        {
            foreach (var player in players)
            {
                string label = (player.Online ? "●  " : "○  ") + player.Name + "   Lv." + player.Level;
                if (GUILayout.Button(label, GUILayout.Height(34)))
                {
                    selectedUid = player.Uid;
                    selectedName = player.Name;
                    page = Page.Players;
                    _ = LoadGatesAsync();
                }
            }
        }
        GUILayout.EndScrollView();
        GUILayout.EndVertical();

        GUILayout.BeginVertical(GUI.skin.box, GUILayout.ExpandWidth(true), GUILayout.ExpandHeight(true));
        PlayerRow selected = null;
        lock (sync)
            selected = players.Find(p => p.Uid == selectedUid);
        if (selected == null)
        {
            GUILayout.Label("Select a player from the list.");
        }
        else
        {
            GUILayout.Label(selected.Name + "  //  " + (selected.Online ? "ONLINE" : "OFFLINE"));
            GUILayout.Label("UID: " + selected.Uid);
            GUILayout.Space(8);
            GUILayout.Label("Level: " + selected.Level + "     Map: " + selected.MapName);
            GUILayout.Label("Ship: " + selected.Ship);
            GUILayout.Label("Credits: " + selected.Credits.ToString("N0") + "     Uridium: " + selected.Uridium.ToString("N0"));
            GUILayout.Label("EP: " + selected.Ep.ToString("N0") + "     Honour: " + selected.Honour.ToString("N0"));
            GUILayout.Space(10);
            GUILayout.Label("Profile editing is the next implementation layer. This first increment is read-only.");
        }
        GUILayout.EndVertical();
        GUILayout.EndHorizontal();
    }

    void DrawDispatch()
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label("DISPATCH GATE STATUS", GUILayout.ExpandWidth(true));
        GUILayout.Label("Target: " + (string.IsNullOrEmpty(selectedName) ? "not selected" : selectedName));
        GUILayout.EndHorizontal();
        if (string.IsNullOrEmpty(selectedUid))
        {
            GUILayout.Label("Select a player in PLAYERS first.");
            return;
        }
        gateScroll = GUILayout.BeginScrollView(gateScroll);
        lock (sync)
        {
            foreach (var gate in gates)
            {
                GUILayout.BeginHorizontal(GUI.skin.box);
                GUILayout.BeginVertical(GUILayout.ExpandWidth(true));
                GUILayout.Label(gate.Name + "   " + gate.Parts + " / " + gate.Required);
                GUILayout.Label(gate.Status + "  ·  " + gate.Reason);
                GUILayout.EndVertical();

                if (gate.CanSend)
                {
                    if (GUILayout.Button("SEND · 1 GGEU", GUILayout.Width(150), GUILayout.Height(38)))
                        _ = DispatchActionAsync(gate, "send");
                }
                else if (gate.CanCollect)
                {
                    if (GUILayout.Button("COLLECT", GUILayout.Width(150), GUILayout.Height(38)))
                        _ = DispatchActionAsync(gate, "collect");
                }
                else
                {
                    GUILayout.Label(gate.Built ? "LOCKED" : "BUILDING", GUILayout.Width(100));
                }
                GUILayout.EndHorizontal();
            }
        }
        GUILayout.EndScrollView();
    }

    void DrawCommands()
    {
        GUILayout.Label("NATIVE GM COMMANDS");
        GUILayout.Label("Current commands remain available in the game's original GM window:");
        GUILayout.Label("jump · kill · quest · book · spawn · box · god · cooldown · pet · galaxyGates");
        GUILayout.Space(10);
        GUILayout.Label("The new typed command builder and player-target selection will be added after the player and Dispatch API is validated.");
        if (GUILayout.Button("Open player list", GUILayout.Height(34)))
            page = Page.Players;
    }

    void DrawLogs()
    {
        GUILayout.Label("ACTIVITY");
        GUILayout.Label(notice);
        if (!string.IsNullOrEmpty(error))
            GUILayout.Label(error);
        GUILayout.Label("Detailed audit history will be connected to the server log in a later increment.");
    }
}
