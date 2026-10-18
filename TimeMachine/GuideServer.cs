using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Net;
using System.Reflection;
using System.Text;
using System.Threading;
using HarmonyLib;
using Mortal.Core;
using Mortal.Story;
using UnityEngine;

namespace LOM.TimeMachine;

// 本機網頁服務：提供流程圖頁面、遊戲即時狀態與時光機讀檔。
// HTTP 在背景執行緒處理；遊戲狀態只在主執行緒讀取（Tick），背景執行緒只拿快取好的 JSON。
internal sealed class GuideServer
{
    private readonly int _port;
    private readonly string _pageDir;
    private HttpListener _listener;
    private Thread _thread;

    private volatile string _stateJson = "{\"live\":false}";
    private volatile string _timeMachineJson = "[]";
    private long _lastRequestTicks;
    private float _nextSnapshot;
    private readonly ConcurrentQueue<string> _loadRequests = new ConcurrentQueue<string>();
    private volatile string _lastLoadResult = "";
    private volatile string _positionsJson = "{\"groups\":{}}";
    private long _lastPositionsRequestTicks;
    // 角色頭像（遊戲裡的小頭像轉成 PNG，只放記憶體）：網頁第一次來要時才在主執行緒轉
    private readonly ConcurrentDictionary<string, byte[]> _icons = new ConcurrentDictionary<string, byte[]>();
    private volatile bool _iconsWanted;
    private volatile bool _iconsReady;

    internal string Url => $"http://localhost:{_port}/";

    internal GuideServer(int port, string pageDir)
    {
        _port = port;
        _pageDir = pageDir;
    }

    internal void Start()
    {
        try
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add(Url);
            _listener.Start();
            _thread = new Thread(Loop) { IsBackground = true, Name = "TimeMachineGuide" };
            _thread.Start();
            Plugin.Log.LogInfo($"[Guide] 網頁服務啟動：{Url}");
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[Guide] 網頁服務啟動失敗：{e.Message}");
        }
    }

    internal void Stop()
    {
        try
        {
            _listener?.Stop();
        }
        catch
        {
        }
    }

    // 主執行緒：網頁最近 10 秒內有來要資料時，每秒更新一次快照；處理讀檔要求
    internal void Tick()
    {
        while (_loadRequests.TryDequeue(out string key))
        {
            _lastLoadResult = LoadByKey(key);
        }
        if (_iconsWanted && !_iconsReady)
        {
            BuildIcons();
        }
        bool active = DateTime.UtcNow.Ticks - Interlocked.Read(ref _lastRequestTicks) < TimeSpan.FromSeconds(10).Ticks;
        if (!active || Time.unscaledTime < _nextSnapshot)
        {
            return;
        }
        _nextSnapshot = Time.unscaledTime + 1f;
        try
        {
            _stateJson = BuildState();
            _timeMachineJson = BuildTimeMachineList();
            // 地點隨機事件的目前權重：只有網頁正在看「唐門地點事件」時才算
            if (DateTime.UtcNow.Ticks - Interlocked.Read(ref _lastPositionsRequestTicks) < TimeSpan.FromSeconds(10).Ticks)
            {
                _positionsJson = BuildPositions();
            }
        }
        catch (Exception e)
        {
            _stateJson = "{\"live\":true,\"error\":" + Json.Str(e.Message) + "}";
        }
    }

    private void Loop()
    {
        while (_listener != null && _listener.IsListening)
        {
            HttpListenerContext context;
            try
            {
                context = _listener.GetContext();
            }
            catch
            {
                return;
            }
            try
            {
                Handle(context);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[Guide] 請求處理失敗：{e.Message}");
                try
                {
                    context.Response.StatusCode = 500;
                    context.Response.Close();
                }
                catch
                {
                }
            }
        }
    }

    private void Handle(HttpListenerContext context)
    {
        string path = context.Request.Url.AbsolutePath;
        Interlocked.Exchange(ref _lastRequestTicks, DateTime.UtcNow.Ticks);
        switch (path)
        {
            case "/":
            case "/index.html":
                ServeFile(context, Path.Combine(_pageDir, "index.html"), "text/html; charset=utf-8");
                return;
            case "/api/state":
                Write(context, _stateJson, "application/json; charset=utf-8");
                return;
            case "/api/timemachine":
                Write(context, _timeMachineJson, "application/json; charset=utf-8");
                return;
            case "/api/positions":
                Interlocked.Exchange(ref _lastPositionsRequestTicks, DateTime.UtcNow.Ticks);
                string positions = _positionsJson;
                Write(context, positions.Substring(0, positions.Length - 1) + ",\"draws\":" + DrawLog.Json() + "}", "application/json; charset=utf-8");
                return;
            case "/api/load":
                string key = context.Request.QueryString["key"] ?? "";
                if (context.Request.HttpMethod != "POST" || key.Length == 0)
                {
                    context.Response.StatusCode = 400;
                    context.Response.Close();
                    return;
                }
                _lastLoadResult = "";
                _loadRequests.Enqueue(key);
                Write(context, "{\"queued\":true}", "application/json; charset=utf-8");
                return;
            case "/api/lastload":
                Write(context, "{\"result\":" + Json.Str(_lastLoadResult) + "}", "application/json; charset=utf-8");
                return;
            case "/api/icons":
                _iconsWanted = true;
                StringBuilder names = new StringBuilder();
                foreach (string name in _icons.Keys)
                {
                    names.Append(names.Length > 0 ? "," : "").Append(Json.Str(name));
                }
                Write(context, "{\"ready\":" + (_iconsReady ? "true" : "false") + ",\"names\":[" + names + "]}", "application/json; charset=utf-8");
                return;
            case "/api/icon":
                // 中文名字自己解碼，不靠 QueryString 的預設編碼
                string query = context.Request.Url.Query;
                string iconName = query.StartsWith("?name=") ? Uri.UnescapeDataString(query.Substring(6)) : "";
                if (_icons.TryGetValue(iconName, out byte[] png))
                {
                    context.Response.ContentType = "image/png";
                    context.Response.Headers["Cache-Control"] = "max-age=86400";
                    context.Response.ContentLength64 = png.Length;
                    context.Response.OutputStream.Write(png, 0, png.Length);
                    context.Response.Close();
                    return;
                }
                break;
        }
        context.Response.StatusCode = 404;
        context.Response.Close();
    }

    private static void ServeFile(HttpListenerContext context, string file, string type)
    {
        if (!File.Exists(file))
        {
            Write(context, "找不到頁面檔案：" + file, "text/plain; charset=utf-8");
            return;
        }
        byte[] bytes = File.ReadAllBytes(file);
        context.Response.ContentType = type;
        context.Response.ContentLength64 = bytes.Length;
        context.Response.OutputStream.Write(bytes, 0, bytes.Length);
        context.Response.Close();
    }

    private static void Write(HttpListenerContext context, string text, string type)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(text);
        context.Response.ContentType = type;
        context.Response.Headers["Cache-Control"] = "no-store";
        context.Response.ContentLength64 = bytes.Length;
        context.Response.OutputStream.Write(bytes, 0, bytes.Length);
        context.Response.Close();
    }

    // 用遊戲本身的存檔資料結構取目前狀態（旗標、數值、好感、天賦、時間）
    private static string BuildState()
    {
        SceneController sceneController = SceneController.Instance;
        bool inGame = sceneController != null && sceneController.CurrentScene != GameBridge.TitleScene;
        StringBuilder sb = new StringBuilder(64 * 1024);
        sb.Append("{\"live\":true,\"inGame\":").Append(inGame ? "true" : "false");
        // 講經堂圖鑑（跨存檔共用）：死法、汗青書、結局 CG 已取得的項目
        LibrarySystem library = LibrarySystem.Instance;
        if (library != null)
        {
            sb.Append(",\"lib\":{");
            List<LibraryItemData> got = new List<LibraryItemData>();
            foreach (LibraryItemCollection collection in new[] { library.Dead, library.EndGame, library.EndCg })
            {
                got.AddRange(collection.List.FindAll(item => item.Count > 0));
            }
            AppendPairs(sb, got, item => item.name, item => item.Count);
            sb.Append('}');
        }
        if (!inGame)
        {
            return sb.Append('}').ToString();
        }
        GameSave save = GameBridge.CreateSaveData();
        sb.Append(",\"time\":{\"y\":").Append(save.CurrentYear).Append(",\"m\":").Append(save.CurrentMonth)
          .Append(",\"s\":").Append((int)save.CurrentStage).Append('}');
        sb.Append(",\"scene\":").Append(Json.Str(save.CurrentScene));
        sb.Append(",\"script\":").Append(Json.Str(PlayerStatManagerData.Instance.CurrentStoryScript));
        sb.Append(",\"mode\":").Append(Json.Str(TimeStore.CurrentMode()));
        sb.Append(",\"route\":").Append(Json.Str(TimeStore.CurrentRoute));
        sb.Append(",\"flags\":{");
        AppendPairs(sb, save.EventFlags, f => f.Name, f => f.State);
        sb.Append("},\"stats\":{");
        AppendPairs(sb, save.Stats, s => s.Key, s => s.Value);
        sb.Append("},\"rel\":{");
        AppendPairs(sb, save.Relationships, r => r.Key, r => r.Value);
        sb.Append("},\"talents\":{");
        AppendPairs(sb, save.Talents, t => t.Id, t => t.Level);
        sb.Append("},\"missions\":{");
        AppendPairs(sb, save.SubMissions, m => m.Name, m => 0, m => Json.Str(m.Key));
        sb.Append("},\"main\":").Append(Json.Str(save.MainMission.Key));
        return sb.Append('}').ToString();
    }

    // 好感度資料裡每個角色的小頭像（沒有就用半身頭像），以角色名（列舉名稱）為鍵
    private void BuildIcons()
    {
        _iconsReady = true;
        RelationshipData relationships = PlayerStatManagerData.Instance?.Relationships;
        if (relationships?.List == null)
        {
            return;
        }
        foreach (RelationshipStat stat in relationships.List)
        {
            Sprite sprite = stat == null ? null : stat.Icon != null ? stat.Icon : stat.HeadIcon;
            if (sprite == null)
            {
                continue;
            }
            try
            {
                _icons[stat.Type.ToString()] = SpriteToPng(sprite);
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[Guide] 頭像轉換失敗（{stat.Type}）：{e.Message}");
            }
        }
        Plugin.Log.LogInfo($"[Guide] 已轉換 {_icons.Count} 個角色頭像");
    }

    // 圖集裡的貼圖通常不可讀：先畫到 RenderTexture 再讀回該 Sprite 的範圍
    private static byte[] SpriteToPng(Sprite sprite)
    {
        Texture2D source = sprite.texture;
        Rect rect = sprite.textureRect;
        RenderTexture rt = RenderTexture.GetTemporary(source.width, source.height, 0, RenderTextureFormat.ARGB32);
        RenderTexture previous = RenderTexture.active;
        Texture2D copy = new Texture2D((int)rect.width, (int)rect.height, TextureFormat.RGBA32, false);
        try
        {
            Graphics.Blit(source, rt);
            RenderTexture.active = rt;
            copy.ReadPixels(rect, 0, 0);
            copy.Apply();
            return copy.EncodeToPNG();
        }
        finally
        {
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(rt);
            UnityEngine.Object.Destroy(copy);
        }
    }

    private static readonly FieldInfo ToggleConditionField = AccessTools.Field(typeof(PositionEventData), "_toggleCondition");
    private static readonly FieldInfo ActiveConditionField = AccessTools.Field(typeof(PositionEventData), "_activeCondition");
    private static readonly FieldInfo RateItemsField = AccessTools.Field(typeof(PositionEventData), "_eventRateItem");
    private static readonly FieldInfo ConditionItemsField = AccessTools.Field(typeof(ConditionResultItem), "_items");

    // 用遊戲本身的判斷算每個地點候選事件的目前權重（GetRate），並逐條回報啟用條件與加權條件是否成立
    private static string BuildPositions()
    {
        StringBuilder sb = new StringBuilder(64 * 1024);
        sb.Append("{\"groups\":{");
        bool firstGroup = true;
        foreach (PositionResultData group in Resources.FindObjectsOfTypeAll<PositionResultData>())
        {
            if (group.List == null)
            {
                continue;
            }
            if (!firstGroup)
            {
                sb.Append(',');
            }
            firstGroup = false;
            sb.Append(Json.Str(group.name)).Append(":[");
            bool first = true;
            foreach (PositionEventData item in group.List)
            {
                if (item == null)
                {
                    continue;
                }
                if (!first)
                {
                    sb.Append(',');
                }
                first = false;
                sb.Append("{\"id\":").Append(Json.Str(item.name)).Append(",\"code\":").Append(Json.Str(item.ResultType));
                try
                {
                    sb.Append(",\"rate\":").Append(item.GetRate());
                    bool toggle = (bool)ToggleConditionField.GetValue(item);
                    ConditionResultItem active = (ConditionResultItem)ActiveConditionField.GetValue(item);
                    sb.Append(",\"atoms\":").Append(toggle && active != null ? Bools(active) : "[]");
                    sb.Append(",\"bonus\":[");
                    PositionEventRateItem[] rateItems = (PositionEventRateItem[])RateItemsField.GetValue(item) ?? new PositionEventRateItem[0];
                    for (int i = 0; i < rateItems.Length; i++)
                    {
                        sb.Append(i > 0 ? "," : "").Append(rateItems[i].Condition != null && rateItems[i].Condition.Check() ? "true" : "false");
                    }
                    sb.Append(']');
                }
                catch (Exception e)
                {
                    sb.Append(",\"error\":").Append(Json.Str(e.Message));
                }
                sb.Append('}');
            }
            sb.Append(']');
        }
        return sb.Append("}}").ToString();
    }

    private static string Bools(ConditionResultItem condition)
    {
        StringBuilder sb = new StringBuilder("[");
        bool first = true;
        foreach (object entry in (IEnumerable)ConditionItemsField.GetValue(condition) ?? new object[0])
        {
            sb.Append(first ? "" : ",").Append(entry is StatCompareItem compare && compare.Check() ? "true" : "false");
            first = false;
        }
        return sb.Append(']').ToString();
    }

    private static void AppendPairs<T>(StringBuilder sb, List<T> list, Func<T, string> key, Func<T, int> value, Func<T, string> raw = null)
    {
        bool first = true;
        HashSet<string> seen = new HashSet<string>();
        foreach (T item in list)
        {
            string k = key(item);
            if (string.IsNullOrEmpty(k) || !seen.Add(k))
            {
                continue;
            }
            if (!first)
            {
                sb.Append(',');
            }
            first = false;
            sb.Append(Json.Str(k)).Append(':').Append(raw != null ? raw(item) : value(item).ToString(CultureInfo.InvariantCulture));
        }
    }

    private static string BuildTimeMachineList()
    {
        StringBuilder sb = new StringBuilder("[");
        bool first = true;
        foreach (TimeEntry e in TimeStore.List(TimeStore.CurrentMode()))
        {
            if (!first)
            {
                sb.Append(',');
            }
            first = false;
            sb.Append("{\"key\":").Append(Json.Str($"{e.Mode}|{e.Year}|{e.Month}|{(int)e.Stage}"))
              .Append(",\"y\":").Append(e.Year).Append(",\"m\":").Append(e.Month).Append(",\"s\":").Append((int)e.Stage)
              .Append(",\"scene\":").Append(Json.Str(e.Scene))
              .Append(",\"saved\":").Append(Json.Str(e.SavedAt.ToString("yyyy-MM-dd HH:mm")))
              .Append('}');
        }
        return sb.Append(']').ToString();
    }

    // 主執行緒：依「模式|年|月|旬」讀時光機存檔
    private static string LoadByKey(string key)
    {
        string[] parts = key.Split('|');
        if (parts.Length != 4 || !int.TryParse(parts[1], out int y) || !int.TryParse(parts[2], out int m) || !int.TryParse(parts[3], out int s))
        {
            return "格式錯誤";
        }
        if (!GameBridge.CanLoad(out string reason))
        {
            return reason;
        }
        string path = TimeStore.PathFor(parts[0], y, m, (MonthStageType)s);
        if (!File.Exists(path))
        {
            return "沒有這一旬的時光機存檔";
        }
        try
        {
            AutoGameSave save = TimeStore.Read(path);
            Plugin.Log.LogInfo($"[Guide] 從網頁讀取 {parts[0]} 第{y}年{m}月 旬{s}");
            GameBridge.Load(save);
            return "ok";
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[Guide] 讀檔失敗：{e}");
            return "讀檔失敗：" + e.Message;
        }
    }
}

internal static class Json
{
    internal static string Str(string s)
    {
        if (s == null)
        {
            return "null";
        }
        StringBuilder sb = new StringBuilder(s.Length + 2);
        sb.Append('"');
        foreach (char c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20)
                    {
                        sb.Append("\\u").Append(((int)c).ToString("x4"));
                    }
                    else
                    {
                        sb.Append(c);
                    }
                    break;
            }
        }
        return sb.Append('"').ToString();
    }
}
