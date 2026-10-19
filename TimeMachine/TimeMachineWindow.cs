using System;
using System.Collections.Generic;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Unity.Mono;
using BepInEx.Unity.Mono.Bootstrap;
using Mortal.Core;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.Controls;

namespace LOM.TimeMachine;

internal sealed class TimeMachineWindow
{
    private const int WindowId = 0x544D31;
    private const float WindowWidth = 1460f;
    private const float WindowHeight = 710f;
    private const float UiScale = 1.15f;
    private const float DoubleClickSeconds = 0.4f;
    private const float YearLabelWidth = 72f;
    private const float StageWidth = 32f;
    private const float CellWidth = StageWidth * 3 + 4f;
    private const float CellHeight = 44f;
    private const float NodeRowHeight = 30f;

    private static readonly string[] StageShort = { "", "上", "中", "下" };

    private static readonly string[] FontNames =
    {
        "Microsoft JhengHei UI", "Microsoft JhengHei", "Microsoft YaHei UI", "Microsoft YaHei", "PMingLiU", "SimSun", "Arial"
    };

    private readonly InputBlocker _blocker = new InputBlocker();
    private bool _open;
    private Rect _rect;
    private Vector2 _scroll;
    private string _mode;
    private List<string> _modes = new List<string>();
    private List<TimeEntry> _entries = new List<TimeEntry>();
    private TimeEntry _selected;
    private Dictionary<string, TimeEntry> _nodeEntries = new Dictionary<string, TimeEntry>();
    private KeyNode _selectedNode;
    private readonly float[,] _stageX = new float[13, 4];
    private bool _stageXReady;
    private bool _confirm;
    private TimeEntry _pendingLoad;
    private string _message;
    private string _newRoute = "";
    private string _deleteRoute;
    private ConfigEntry<Key> _capturing;
    private float _viewWidth;

    private bool _stylesReady;
    private GUIStyle _dim;
    private GUIStyle _window;
    private GUIStyle _label;
    private GUIStyle _small;
    private GUIStyle _header;
    private GUIStyle _button;
    private GUIStyle _cell;
    private GUIStyle _cellSelected;
    private GUIStyle _cellCurrent;
    private GUIStyle _empty;
    private GUIStyle _field;
    private GUIStyle _toggle;
    private GUIStyle _warn;
    private GUIStyle _nowrap;
    private TimeEntry _lastClicked;
    private float _lastClickTime;
    private GUIStyle _node;
    private GUIStyle _nodeDim;
    private Texture2D _lineOn;
    private Texture2D _lineOff;

    public void Toggle()
    {
        if (_open)
        {
            Close();
        }
        else
        {
            Open();
        }
    }

    private void Open()
    {
        _message = null;
        _selected = null;
        _selectedNode = null;
        _confirm = false;
        try
        {
            _mode = TimeStore.CurrentMode();
            Refresh();
        }
        catch (Exception e)
        {
            _message = "無法讀取時光機資料：" + e.Message;
            Plugin.Log.LogError($"[TimeMachine] {e}");
        }
        _open = true;
        _blocker.Block();
    }

    private void Close()
    {
        _open = false;
        _confirm = false;
        _deleteRoute = null;
        _capturing = null;
        _blocker.Restore();
    }

    private void Refresh()
    {
        _modes = TimeStore.Modes();
        if (!_modes.Contains(_mode))
        {
            _modes.Insert(0, _mode);
        }
        _entries = TimeStore.List(_mode);
        _nodeEntries = _mode == TimeStore.MainMode ? TimeStore.ListNodes(_mode) : new Dictionary<string, TimeEntry>();
        if (_selectedNode != null)
        {
            _selected = _nodeEntries.TryGetValue(_selectedNode.Id, out TimeEntry nodeEntry) ? nodeEntry : null;
        }
        else if (_selected != null)
        {
            _selected = _entries.Find(e => e.Path == _selected.Path);
        }
    }

    // 正在等使用者按新的快捷鍵（這段期間 Plugin 不處理快捷鍵）
    public bool CapturingKey => _capturing != null;

    public void Update()
    {
        if (_pendingLoad != null)
        {
            TimeEntry entry = _pendingLoad;
            _pendingLoad = null;
            DoLoad(entry);
            return;
        }
        if (_capturing != null)
        {
            PollCapture();
            return;
        }
        if (_open && Keyboard.current is not null && Keyboard.current.escapeKey.wasPressedThisFrame)
        {
            Close();
        }
    }

    // ---------- 快捷鍵設定：按按鈕後按下新按鍵，寫回 BepInEx 設定檔 ----------
    private void PollCapture()
    {
        Keyboard keyboard = Keyboard.current;
        if (keyboard == null)
        {
            return;
        }
        if (keyboard.escapeKey.wasPressedThisFrame)
        {
            _capturing = null;
            _message = "已取消變更快捷鍵。";
            return;
        }
        foreach (KeyControl control in keyboard.allKeys)
        {
            if (control == null || control.keyCode == Key.None || !control.wasPressedThisFrame)
            {
                continue;
            }
            Key key = control.keyCode;
            ConfigEntry<Key> target = _capturing;
            _capturing = null;
            string conflict = FindKeyConflict(target, key);
            if (conflict != null)
            {
                _message = $"不能用 {key}：{conflict}。";
                return;
            }
            target.Value = key;
            _message = $"「{KeyName(target)}」改為 {key}（已寫入設定檔）。";
            Plugin.Log.LogInfo($"[TimeMachine] {target.Definition.Key} = {key}");
            return;
        }
    }

    private static string KeyName(ConfigEntry<Key> entry)
    {
        return entry == Plugin.ToggleKey ? "時光機" : "五塊錢";
    }

    private string FindKeyConflict(ConfigEntry<Key> target, Key key)
    {
        ConfigEntry<Key> other = target == Plugin.ToggleKey ? Plugin.GuideKey : Plugin.ToggleKey;
        if (other.Value == key)
        {
            return $"已經是「{KeyName(other)}」的快捷鍵";
        }
        string action = _blocker.FindBinding(key);
        if (action != null)
        {
            return $"遊戲本身用在「{action}」";
        }
        // 其他插件設定裡名稱含 Key 的項目（Key、KeyCode 或字串）
        try
        {
            foreach (PluginInfo info in UnityChainloader.Instance.Plugins.Values)
            {
                if (info.Metadata.GUID == Plugin.GUID || info.Instance is not BaseUnityPlugin plugin)
                {
                    continue;
                }
                foreach (KeyValuePair<ConfigDefinition, ConfigEntryBase> pair in plugin.Config)
                {
                    object value = pair.Value.BoxedValue;
                    if (value != null && pair.Key.Key.IndexOf("key", StringComparison.OrdinalIgnoreCase) >= 0
                        && string.Equals(value.ToString().Trim(), key.ToString(), StringComparison.OrdinalIgnoreCase))
                    {
                        return $"插件「{info.Metadata.Name}」的 {pair.Key.Key} 已經使用";
                    }
                }
            }
        }
        catch (Exception e)
        {
            Plugin.Log.LogWarning($"[TimeMachine] 無法檢查其他插件的快捷鍵：{e.Message}");
        }
        return null;
    }

    private void DoLoad(TimeEntry entry)
    {
        if (!GameBridge.CanLoad(out string reason))
        {
            _message = reason;
            return;
        }
        AutoGameSave save;
        try
        {
            save = TimeStore.Read(entry.Path);
        }
        catch (Exception e)
        {
            _message = "讀取存檔失敗：" + e.Message;
            return;
        }
        Close();
        Plugin.Log.LogInfo($"[TimeMachine] 讀取 {entry.Mode} 第{entry.Year}年{entry.Month}月{entry.Stage}");
        try
        {
            GameBridge.Load(save);
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[TimeMachine] 讀檔失敗：{e}");
        }
    }

    public void OnGUI()
    {
        if (!_open)
        {
            return;
        }
        EnsureStyles();
        float scale = Mathf.Max(0.5f, Mathf.Min(Screen.height / 1080f * UiScale, Screen.width / (WindowWidth + 40f)));
        Matrix4x4 previous = GUI.matrix;
        GUI.matrix = Matrix4x4.TRS(Vector3.zero, Quaternion.identity, new Vector3(scale, scale, 1f));
        float width = Screen.width / scale;
        float height = Screen.height / scale;
        GUI.Box(new Rect(0f, 0f, width, height), GUIContent.none, _dim);
        if (_rect.width <= 0f)
        {
            _rect = new Rect((width - WindowWidth) / 2f, (height - WindowHeight) / 2f, WindowWidth, WindowHeight);
        }
        _rect = GUI.Window(WindowId, _rect, DrawWindow, "時光機", _window);
        GUI.matrix = previous;
    }

    private void DrawWindow(int id)
    {
        DrawHeader();
        GUILayout.Space(6f);
        DrawRoutes();
        GUILayout.Space(8f);
        _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.Height(390f));
        DrawGrid();
        GUILayout.EndScrollView();
        if (Event.current.type == EventType.Repaint)
        {
            _viewWidth = GUILayoutUtility.GetLastRect().width;
        }
        GUILayout.FlexibleSpace();
        DrawDetails();
        if (!string.IsNullOrEmpty(_message))
        {
            GUILayout.Label(_message, _small);
        }
        GUI.DragWindow(new Rect(0f, 0f, WindowWidth, 34f));
    }

    private void DrawHeader()
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label(CurrentTimeText(), _nowrap);
        if (!Plugin.AutoCapture.Value)
        {
            GUILayout.Space(12f);
            GUILayout.Label("自動存檔暫停中", _warn);
        }
        GUILayout.FlexibleSpace();
        if (_modes.Count > 1)
        {
            foreach (string mode in _modes)
            {
                bool on = GUILayout.Toggle(_mode == mode, ModeName(mode), _button, GUILayout.Width(100f));
                if (on && _mode != mode)
                {
                    _mode = mode;
                    _selected = null;
                    _selectedNode = null;
                    _confirm = false;
                    Refresh();
                }
            }
            GUILayout.Space(16f);
        }
        DrawKeyButton(Plugin.ToggleKey);
        if (Plugin.GuideEnabled.Value)
        {
            DrawKeyButton(Plugin.GuideKey);
        }
        GUILayout.Space(16f);
        bool paused = GUILayout.Toggle(!Plugin.AutoCapture.Value, " 暫停自動存檔", _toggle, GUILayout.Width(170f));
        if (paused == Plugin.AutoCapture.Value)
        {
            Plugin.AutoCapture.Value = !paused;
            _message = paused ? "已暫停自動存檔：時光機存檔與關鍵節點都不會寫入，直到取消勾選（重開遊戲也會保持暫停）。" : "已恢復自動存檔。";
            Plugin.Log.LogInfo($"[TimeMachine] 自動存檔{(paused ? "暫停" : "恢復")}");
        }
        bool quick = GUILayout.Toggle(Plugin.QuickLoad.Value, " 快速讀取", _toggle, GUILayout.Width(120f));
        if (quick != Plugin.QuickLoad.Value)
        {
            Plugin.QuickLoad.Value = quick;
            _confirm = false;
            _message = quick ? "快速讀取：雙擊時間點直接讀取，按「讀取這個時間點」也不再確認。" : "已關閉快速讀取。";
        }
        GUILayout.Space(8f);
        if (GUILayout.Button("重新整理", _button, GUILayout.Width(110f)))
        {
            Refresh();
        }
        if (GUILayout.Button($"關閉（{Plugin.ToggleKey.Value}）", _button, GUILayout.Width(130f)))
        {
            Close();
        }
        GUILayout.EndHorizontal();
    }

    private void DrawKeyButton(ConfigEntry<Key> entry)
    {
        string text = _capturing == entry ? "請按新按鍵（Esc 取消）" : $"{KeyName(entry)}：{entry.Value}";
        if (GUILayout.Button(text, _button, GUILayout.MinWidth(130f)))
        {
            _capturing = _capturing == entry ? null : entry;
            _message = _capturing != null ? $"請按下「{KeyName(entry)}」的新快捷鍵，按 Esc 取消。" : null;
        }
    }

    // 路線：每條路線各自一套時光機存檔，切換後新的存檔只寫進目前路線
    private void DrawRoutes()
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label("存檔路線：", _label, GUILayout.Width(110f));
        string current = TimeStore.CurrentRoute;
        foreach (string route in TimeStore.Routes())
        {
            bool on = GUILayout.Toggle(route == current, route, _button, GUILayout.MinWidth(80f));
            if (on && route != current)
            {
                TimeStore.SwitchRoute(route);
                ResetSelection();
                _message = $"已切換到路線「{route}」，之後的時光機存檔只會寫進這條路線。";
                Refresh();
            }
            if (route != TimeStore.DefaultRoute && GUILayout.Button("×", _button, GUILayout.Width(30f)))
            {
                _deleteRoute = route;
                _message = null;
            }
            GUILayout.Space(8f);
        }
        GUILayout.FlexibleSpace();
        _newRoute = GUILayout.TextField(_newRoute, 24, _field, GUILayout.Width(180f));
        if (GUILayout.Button("新增：從目前時間分岔", _button, GUILayout.Width(220f)))
        {
            CreateRoute(copy: true);
        }
        if (GUILayout.Button("新增：空白", _button, GUILayout.Width(120f)))
        {
            CreateRoute(copy: false);
        }
        GUILayout.EndHorizontal();
        if (_deleteRoute != null)
        {
            DrawDeleteRoute();
        }
    }

    private void DrawDeleteRoute()
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label($"確定刪除路線「{_deleteRoute}」？裡面 {TimeStore.CountSaves(_deleteRoute)} 個時光機存檔會一起刪除，無法復原。"
            + (_deleteRoute == TimeStore.CurrentRoute ? "刪除後切回「預設」。" : ""), _small);
        if (GUILayout.Button("確定刪除", _button, GUILayout.Width(120f)))
        {
            string name = _deleteRoute;
            _deleteRoute = null;
            string error;
            try
            {
                error = TimeStore.DeleteRoute(name);
            }
            catch (Exception e)
            {
                error = "刪除路線失敗：" + e.Message;
                Plugin.Log.LogError($"[TimeMachine] {e}");
            }
            if (error == null)
            {
                Plugin.Log.LogInfo($"[TimeMachine] 刪除路線「{name}」");
            }
            _message = error ?? $"已刪除路線「{name}」。目前路線：{TimeStore.CurrentRoute}";
            ResetSelection();
            Refresh();
        }
        if (GUILayout.Button("取消", _button, GUILayout.Width(100f)))
        {
            _deleteRoute = null;
        }
        GUILayout.EndHorizontal();
    }

    // 分岔：複製目前路線「不晚於現在這一旬」的存檔（標題畫面時整套複製），之後各走各的
    private void CreateRoute(bool copy)
    {
        int? until = null;
        if (copy)
        {
            if (InGame())
            {
                GameTime time = PlayerStatManagerData.Instance.GameTime;
                until = (time.Year * 100 + time.Month) * 10 + (int)time.Stage;
            }
            else
            {
                until = int.MaxValue;
            }
        }
        string from = TimeStore.CurrentRoute;
        string name = _newRoute.Trim();
        string error;
        try
        {
            error = TimeStore.CreateRoute(name, until);
        }
        catch (Exception e)
        {
            error = "建立路線失敗：" + e.Message;
            Plugin.Log.LogError($"[TimeMachine] {e}");
        }
        if (error != null)
        {
            _message = error;
            return;
        }
        Plugin.Log.LogInfo($"[TimeMachine] 新增路線「{name}」（{(copy ? "從「" + from + "」分岔" : "空白")}）");
        _message = copy ? $"已新增路線「{name}」並切換過去：複製了「{from}」到目前時間為止的存檔，之後兩條路線互不覆蓋。"
            : $"已新增空白路線「{name}」並切換過去。";
        _newRoute = "";
        ResetSelection();
        Refresh();
    }

    private void ResetSelection()
    {
        _selected = null;
        _selectedNode = null;
        _confirm = false;
    }

    private void DrawGrid()
    {
        Dictionary<int, TimeEntry> byRound = new Dictionary<int, TimeEntry>();
        SortedSet<int> years = new SortedSet<int>();
        foreach (TimeEntry entry in _entries)
        {
            byRound[entry.SortKey] = entry;
            years.Add(entry.Year);
        }
        GameTime current = InGame() && _mode == TimeStore.CurrentMode() ? PlayerStatManagerData.Instance.GameTime : null;
        if (current is not null)
        {
            years.Add(current.Year);
        }
        if (_mode == TimeStore.MainMode && years.Count > 0)
        {
            foreach (KeyNode node in KeyNodes.All)
            {
                _nodeEntries.TryGetValue(node.Id, out TimeEntry nodeEntry);
                years.Add(NodePosition(node, nodeEntry).year);
            }
        }
        if (years.Count == 0)
        {
            GUILayout.Label("還沒有時光機存檔。遊戲進入每一旬第一個可存檔的時間點時會自動建立。", _label);
            return;
        }

        // 月份標題對齊下方格子的「中」旬（格子實際寬度比 CellWidth 多出邊距，逐月累積會偏掉）
        Rect monthRow = GUILayoutUtility.GetRect(10f, 30f, GUILayout.ExpandWidth(true));
        for (int month = 1; month <= 12; month++)
        {
            float cx = StageCenter(month, 2);
            GUI.Label(new Rect(cx - CellWidth / 2f, monthRow.y, CellWidth, monthRow.height), $"{month}月", _header);
        }

        foreach (int year in years)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label($"第{year}年", _header, GUILayout.Width(YearLabelWidth), GUILayout.Height(CellHeight));
            for (int month = 1; month <= 12; month++)
            {
                GUILayout.BeginHorizontal(GUILayout.Width(CellWidth));
                for (int stage = 1; stage <= 3; stage++)
                {
                    bool isCurrent = current is not null && current.Year == year && current.Month == month && (int)current.Stage == stage;
                    if (byRound.TryGetValue((year * 100 + month) * 10 + stage, out TimeEntry entry))
                    {
                        GUIStyle style = entry == _selected ? _cellSelected : (isCurrent ? _cellCurrent : _cell);
                        if (GUILayout.Button(StageShort[stage], style, GUILayout.Width(StageWidth), GUILayout.Height(CellHeight)))
                        {
                            _selected = entry;
                            _selectedNode = null;
                            _confirm = false;
                            _message = null;
                            CheckDoubleClick(entry);
                        }
                    }
                    else
                    {
                        GUILayout.Label(isCurrent ? "▲" : "·", _empty, GUILayout.Width(StageWidth), GUILayout.Height(CellHeight));
                    }
                    if (Event.current.type == EventType.Repaint)
                    {
                        _stageX[month, stage] = GUILayoutUtility.GetLastRect().center.x;
                        _stageXReady = true;
                    }
                }
                GUILayout.EndHorizontal();
            }
            GUILayout.EndHorizontal();
            if (_mode == TimeStore.MainMode)
            {
                DrawNodeLane(year);
            }
        }
    }

    // 年份列下方：從事件觸發的旬往下拉線，標出關鍵節點（金色＝已存，存檔本身的時間看下方說明）。還沒經過的節點以灰色標在預計觸發的旬。
    // 標籤超出可視範圍右緣時改畫在線的左邊。
    private void DrawNodeLane(int year)
    {
        List<(KeyNode node, TimeEntry entry, int month, int stage, float width, int level, bool left)> items = new List<(KeyNode, TimeEntry, int, int, float, int, bool)>();
        foreach (KeyNode node in KeyNodes.All)
        {
            _nodeEntries.TryGetValue(node.Id, out TimeEntry entry);
            (int nodeYear, int month, int stage) = NodePosition(node, entry);
            if (nodeYear != year)
            {
                continue;
            }
            float width = (entry != null ? _node : _nodeDim).CalcSize(new GUIContent(node.Name)).x + 12f;
            items.Add((node, entry, month, stage, width, 0, false));
        }
        if (items.Count == 0)
        {
            return;
        }
        items.Sort((a, b) => (a.month * 10 + a.stage).CompareTo(b.month * 10 + b.stage));
        float rightEdge = _scroll.x + (_viewWidth > 0f ? _viewWidth : WindowWidth - 36f) - 24f;
        // 標籤互相重疊時往下一排放
        List<float> levelEnds = new List<float>();
        for (int i = 0; i < items.Count; i++)
        {
            float x = StageCenter(items[i].month, items[i].stage);
            bool left = x + 6f + items[i].width > rightEdge;
            float start = left ? x - 6f - items[i].width : x;
            float end = left ? x : x + 6f + items[i].width;
            int level = levelEnds.FindIndex(e => e < start);
            if (level < 0)
            {
                level = levelEnds.Count;
                levelEnds.Add(0f);
            }
            levelEnds[level] = end + 8f;
            items[i] = (items[i].node, items[i].entry, items[i].month, items[i].stage, items[i].width, level, left);
        }
        Rect lane = GUILayoutUtility.GetRect(10f, levelEnds.Count * NodeRowHeight + 6f, GUILayout.ExpandWidth(true));
        if (!_stageXReady)
        {
            return;
        }
        foreach (var item in items)
        {
            float cx = _stageX[item.month, item.stage];
            float top = lane.y + 4f + item.level * NodeRowHeight;
            float mid = top + (NodeRowHeight - 4f) / 2f;
            Texture2D line = item.entry != null ? _lineOn : _lineOff;
            GUI.DrawTexture(new Rect(cx - 1f, lane.y - 6f, 2f, mid - lane.y + 7f), line);
            GUI.DrawTexture(new Rect(item.left ? cx - 6f : cx, mid - 1f, 6f, 2f), line);
            Rect button = new Rect(item.left ? cx - 6f - item.width : cx + 6f, top, item.width, NodeRowHeight - 4f);
            if (GUI.Button(button, item.node.Name, item.entry != null ? _node : _nodeDim))
            {
                _selectedNode = item.node;
                _selected = item.entry;
                _confirm = false;
                _message = null;
                CheckDoubleClick(item.entry);
            }
        }
    }

    // 快速讀取：同一個存檔在短時間內點兩下就直接讀取
    private void CheckDoubleClick(TimeEntry entry)
    {
        float now = Time.unscaledTime;
        bool twice = entry != null && entry == _lastClicked && now - _lastClickTime <= DoubleClickSeconds;
        _lastClicked = twice ? null : entry;
        _lastClickTime = now;
        if (twice && Plugin.QuickLoad.Value)
        {
            _pendingLoad = entry;
        }
    }

    // 標籤位置：已存的節點用存檔記下的觸發時間（舊檔沒有就用存檔時間），沒存的用預計觸發時間
    private static (int year, int month, int stage) NodePosition(KeyNode node, TimeEntry entry)
    {
        if (entry == null)
        {
            return (node.Year, node.Month, node.Stage);
        }
        if (KeyNodes.TryParseTrigger(entry.Source, out int y, out int m, out int s, out _) && m >= 1 && m <= 12 && s >= 1 && s <= 3)
        {
            return (y, m, s);
        }
        return (entry.Year, entry.Month, (int)entry.Stage);
    }

    private float StageCenter(int month, int stage)
    {
        return _stageXReady ? _stageX[month, stage] : YearLabelWidth + (month - 1) * (CellWidth + 4f) + (stage - 0.5f) * StageWidth;
    }

    private void DrawDetails()
    {
        if (_selectedNode != null)
        {
            GUILayout.Label($"關鍵節點：{_selectedNode.Name}　{_selectedNode.When}", _label);
            if (_selected == null)
            {
                GUILayout.Label(_selectedNode.AfterTrigger
                    ? "這次還沒經過這個節點。經過時會自動保存「觸發後第一個可存檔的時間點」的狀態。"
                    : "這次還沒經過這個節點。經過時會自動保存「觸發前最後一個養成回合開始」的狀態（還有行動次數，可以先準備再觸發）。", _small);
                return;
            }
            if (KeyNodes.TryParseTrigger(_selected.Source, out int ty, out int tm, out int ts, out string script))
            {
                string which = _selectedNode.AfterTrigger ? "後第一個可存檔時間點" : "前";
                GUILayout.Label($"上次在第{ty}年{tm}月{StageShort[ts]}旬觸發（{script}）；下面是觸發{which}的存檔。", _small);
            }
        }
        if (_selected == null)
        {
            GUILayout.Label("每個月分上／中／下旬三格。點選有存檔的旬查看細節，再按「讀取」回到那個時間點。藍色（或 ▲）是目前所在的旬。格子下方拉線的是關鍵節點，標在事件觸發的旬（灰色＝還沒經過）。", _small);
            return;
        }
        TimeEntry entry = _selected;
        GUILayout.Label($"第{entry.Year}年{entry.Month}月{entry.Stage}　{SceneName(entry.Scene)}　腳本：{entry.Script}", _label);
        GUILayout.Label($"存檔時間：{entry.SavedAt:yyyy-MM-dd HH:mm}　來源：{Sources.Describe(entry.Source)}", _small);
        bool canLoad = GameBridge.CanLoad(out string reason);
        GUILayout.BeginHorizontal();
        if (!_confirm)
        {
            GUI.enabled = canLoad;
            if (GUILayout.Button("讀取這個時間點", _button, GUILayout.Width(200f)))
            {
                if (Plugin.QuickLoad.Value)
                {
                    _pendingLoad = entry;
                }
                else
                {
                    _confirm = true;
                }
            }
            GUI.enabled = true;
            if (!canLoad)
            {
                GUILayout.Label(reason, _small);
            }
        }
        else
        {
            GUILayout.Label($"目前未存檔的進度會遺失。讀取後，選單的「存檔」仍會寫入目前欄位 {SaveSystem.Instance.CurrentSlot}。確定讀取？", _small);
            GUI.enabled = canLoad;
            if (GUILayout.Button("確定讀取", _button, GUILayout.Width(140f)))
            {
                _pendingLoad = entry;
            }
            GUI.enabled = true;
            if (GUILayout.Button("取消", _button, GUILayout.Width(100f)))
            {
                _confirm = false;
            }
        }
        GUILayout.EndHorizontal();
    }

    private static bool InGame()
    {
        SceneController sceneController = SceneController.Instance;
        return sceneController != null && sceneController.CurrentScene != GameBridge.TitleScene;
    }

    private static string CurrentTimeText()
    {
        if (!InGame())
        {
            return "目前在標題畫面";
        }
        GameTime time = PlayerStatManagerData.Instance.GameTime;
        return $"目前：第{time.Year}年{time.Month}月{time.Stage}";
    }

    private static string ModeName(string mode)
    {
        return mode == TimeStore.ActMode ? "序章" : (mode == TimeStore.MainMode ? "本篇" : mode);
    }

    private static string SceneName(string scene)
    {
        switch (scene)
        {
            case "Free": return "養成";
            case "Story": return "劇情";
            default: return scene;
        }
    }

    private void EnsureStyles()
    {
        if (_stylesReady)
        {
            return;
        }
        Font font = Font.CreateDynamicFontFromOSFont(FontNames, 20);

        _dim = new GUIStyle { normal = { background = SolidTexture(new Color(0f, 0f, 0f, 0.55f)) } };

        _window = new GUIStyle(GUI.skin.window)
        {
            font = font,
            fontSize = 22,
            padding = new RectOffset(18, 18, 40, 16)
        };
        Texture2D windowBackground = SolidTexture(new Color(0.09f, 0.09f, 0.11f, 0.97f));
        _window.normal.background = windowBackground;
        _window.onNormal.background = windowBackground;
        _window.normal.textColor = new Color(0.95f, 0.85f, 0.6f);
        _window.onNormal.textColor = _window.normal.textColor;

        _label = new GUIStyle(GUI.skin.label) { font = font, fontSize = 20, wordWrap = true };
        _label.normal.textColor = new Color(0.92f, 0.92f, 0.92f);
        _small = new GUIStyle(_label) { fontSize = 17 };
        _small.normal.textColor = new Color(0.75f, 0.75f, 0.78f);
        _header = new GUIStyle(_label) { alignment = TextAnchor.MiddleCenter, wordWrap = false };
        _header.normal.textColor = new Color(0.95f, 0.85f, 0.6f);

        _button = new GUIStyle(GUI.skin.button) { font = font, fontSize = 18 };
        _field = new GUIStyle(GUI.skin.textField) { font = font, fontSize = 18 };
        _nowrap = new GUIStyle(_label) { wordWrap = false };
        _warn = new GUIStyle(_nowrap);
        _warn.normal.textColor = new Color(0.95f, 0.6f, 0.4f);
        _toggle = new GUIStyle(GUI.skin.toggle) { font = font, fontSize = 18 };
        _toggle.normal.textColor = _label.normal.textColor;
        _toggle.onNormal.textColor = new Color(0.95f, 0.6f, 0.4f);
        _toggle.hover.textColor = Color.white;
        _toggle.onHover.textColor = _toggle.onNormal.textColor;

        _cell = new GUIStyle(GUI.skin.button) { font = font, fontSize = 17, alignment = TextAnchor.MiddleCenter };
        _cellCurrent = new GUIStyle(_cell);
        Texture2D currentBackground = SolidTexture(new Color(0.25f, 0.4f, 0.55f, 1f));
        _cellCurrent.normal.background = currentBackground;
        _cellCurrent.hover.background = currentBackground;
        _cellSelected = new GUIStyle(_cell);
        Texture2D selectedBackground = SolidTexture(new Color(0.75f, 0.55f, 0.2f, 1f));
        _cellSelected.normal.background = selectedBackground;
        _cellSelected.hover.background = selectedBackground;
        _cellSelected.normal.textColor = Color.white;

        _empty = new GUIStyle(_header) { fontSize = 17 };
        _empty.normal.textColor = new Color(0.45f, 0.45f, 0.5f);

        _node = new GUIStyle(GUI.skin.button) { font = font, fontSize = 15, alignment = TextAnchor.MiddleLeft, padding = new RectOffset(6, 6, 2, 2) };
        _node.normal.textColor = new Color(0.95f, 0.85f, 0.6f);
        _node.hover.textColor = Color.white;
        _nodeDim = new GUIStyle(_node);
        _nodeDim.normal.textColor = new Color(0.55f, 0.55f, 0.6f);
        _lineOn = SolidTexture(new Color(0.85f, 0.65f, 0.3f, 1f));
        _lineOff = SolidTexture(new Color(0.4f, 0.4f, 0.45f, 1f));

        _stylesReady = true;
    }

    private static Texture2D SolidTexture(Color color)
    {
        Texture2D texture = new Texture2D(1, 1, TextureFormat.RGBA32, false);
        texture.SetPixel(0, 0, color);
        texture.Apply();
        texture.hideFlags = HideFlags.HideAndDontSave;
        return texture;
    }
}

// 視窗開著時暫停遊戲本身的輸入，避免點擊穿透到遊戲 UI 或推進對話。
internal sealed class InputBlocker
{
    private List<InputAction> _disabledActions;
    private EventSystem _eventSystem;
    private bool _eventSystemWasEnabled;
    private bool _cursorWasVisible;
    private CursorLockMode _cursorLockMode;
    private bool _blocking;

    public void Block()
    {
        if (_blocking)
        {
            return;
        }
        _blocking = true;
        _disabledActions = new List<InputAction>();
        foreach (InputAction action in InputSystem.ListEnabledActions())
        {
            action.Disable();
            _disabledActions.Add(action);
        }
        _eventSystem = EventSystem.current;
        if (_eventSystem != null)
        {
            _eventSystemWasEnabled = _eventSystem.enabled;
            _eventSystem.enabled = false;
        }
        _cursorWasVisible = Cursor.visible;
        _cursorLockMode = Cursor.lockState;
        Cursor.visible = true;
        Cursor.lockState = CursorLockMode.None;
    }

    // 遊戲本身（已暫停的輸入動作）綁定這個鍵時回傳動作名稱
    public string FindBinding(Key key)
    {
        if (_disabledActions == null)
        {
            return null;
        }
        foreach (InputAction action in _disabledActions)
        {
            foreach (InputControl control in action.controls)
            {
                if (control is KeyControl keyControl && keyControl.keyCode == key)
                {
                    return action.name;
                }
            }
        }
        return null;
    }

    public void Restore()
    {
        if (!_blocking)
        {
            return;
        }
        _blocking = false;
        foreach (InputAction action in _disabledActions)
        {
            try
            {
                action.Enable();
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[TimeMachine] 無法恢復輸入 {action?.name}：{e.Message}");
            }
        }
        _disabledActions = null;
        if (_eventSystem != null)
        {
            _eventSystem.enabled = _eventSystemWasEnabled;
        }
        _eventSystem = null;
        Cursor.visible = _cursorWasVisible;
        Cursor.lockState = _cursorLockMode;
    }
}
