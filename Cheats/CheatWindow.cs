using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Mortal.Core;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.SceneManagement;

namespace LOM.Cheats;

internal sealed class CheatWindow
{
    private const int WindowId = 0x434854;
    private const float WindowWidth = 980f;
    private const float WindowHeight = 760f;
    private const float UiScale = 1.15f;

    private static readonly string[] FontNames =
    {
        "Microsoft JhengHei UI", "Microsoft JhengHei", "Microsoft YaHei UI", "Microsoft YaHei", "PMingLiU", "SimSun", "Arial"
    };

    // 女主角排在最前面
    private static readonly string[] Heroines = { "小師妹", "葉雲裳", "龍湘", "虞小梅", "夏侯蘭", "郁竹", "上官螢", "魏菊", "瑞杏" };
    // 「認識 X」旗標備註裡的小名 → 人際關係的名稱
    private static readonly Dictionary<string, string> Nicknames = new Dictionary<string, string>
    {
        { "小梅", "虞小梅" }, { "小蘭", "夏侯蘭" }, { "小竹", "郁竹" }, { "小菊", "魏菊" }, { "馬富貴", "李富貴" }, { "毛二壯", "王二壯" }
    };
    private static readonly Regex MeetFlagName = new Regex("^G(1000|300)\\d+$");
    // 劇情用旗標當好感的角色：遊戲的人際關係好感沒有任何劇本會改、也沒有條件用到，改顯示／修改這個旗標
    //（孟仙謠：H04003「孟仙謠好感」，投奔的擲骰門檻等都看它）。遊戲更新後要確認是不是改回一般好感度
    private static readonly Dictionary<string, string> FlagAffection = new Dictionary<string, string> { { "孟仙謠", "H04003" } };

    private readonly InputBlocker _blocker = new InputBlocker();
    private readonly Dictionary<string, string> _setText = new Dictionary<string, string>();
    private Dictionary<string, string> _meetFlags;
    private bool _open;
    private Rect _rect;
    private Vector2 _scroll;
    private string _message;
    private bool _stylesReady;
    private GUIStyle _dim, _window, _label, _small, _button, _field, _toggle, _done;

    public void Toggle()
    {
        _open = !_open;
        if (_open)
        {
            _message = null;
            _blocker.Block();
        }
        else
        {
            _blocker.Restore();
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
        _rect = GUI.Window(WindowId, _rect, DrawWindow, "作弊", _window);
        GUI.matrix = previous;
    }

    private void DrawWindow(int id)
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label($"遊戲本來不允許的選擇。按 {Plugin.ToggleKey.Value} 關閉；改完記得存檔。", _small);
        if (GUILayout.Button("關閉", _button, GUILayout.Width(90f)))
        {
            Toggle();
        }
        GUILayout.EndHorizontal();
        GUILayout.Space(8f);

        bool all = GUILayout.Toggle(Plugin.ShowAllDecisions.Value, " 決策時顯示全部選項", _toggle);
        if (all != Plugin.ShowAllDecisions.Value)
        {
            Plugin.ShowAllDecisions.Value = all;
        }
        GUILayout.Label("第3年12月三師兄召集的決策：滿足西武林盟條件時，遊戲會藏起「決策：戰他娘親」（頑抗路線）和「決策：退隱江湖」（解散唐門）。打開後這兩個也會出現，可以自己選。", _small);
        GUILayout.Space(14f);

        GUILayout.Label("好感與結識", _label);
        GUILayout.Label("直接改目前遊戲裡的好感（0～100）。「設成已結識」會讓角色出現在人際關係，並把劇情條件用的「認識 X」旗標設成 1（有這個旗標的角色才會設）。"
            + "名字後面有旗標的（孟仙謠）：劇情看的是那個旗標，顯示和修改的是它，不是人際關係裡的好感。", _small);
        PlayerStatManagerData player = PlayerStatManagerData.Instance;
        if (player == null || player.Relationships == null || SceneManager.GetActiveScene().name == "Title")
        {
            GUILayout.Label("讀檔進入遊戲後才能使用。", _small);
        }
        else
        {
            DrawRelationships(player);
        }
        if (!string.IsNullOrEmpty(_message))
        {
            GUILayout.Label(_message, _small);
        }
        GUI.DragWindow(new Rect(0f, 0f, WindowWidth, 34f));
    }

    private void DrawRelationships(PlayerStatManagerData player)
    {
        Dictionary<string, string> meetFlags = MeetFlags();
        List<RelationshipStat> stats = player.Relationships.List.Where(s => s != null && s.Type.ToString() != "主角")
            .OrderBy(s => Array.IndexOf(Heroines, s.Type.ToString()) is int i && i >= 0 ? i : 99).ThenByDescending(s => s.Value).ToList();
        _scroll = GUILayout.BeginScrollView(_scroll, GUILayout.ExpandHeight(true));
        foreach (RelationshipStat stat in stats)
        {
            string name = stat.Type.ToString();
            meetFlags.TryGetValue(name, out string flag);
            FlagData flagData = flag != null ? MissionManagerData.Instance?.GetFlag(flag) : null;
            bool met = stat.Active && (flagData == null || flagData.State == 1);
            FlagAffection.TryGetValue(name, out string affFlag);
            FlagData affData = affFlag != null ? MissionManagerData.Instance?.GetFlag(affFlag) : null;
            int current = affData != null ? affData.State : stat.Value;
            void Set(int v)
            {
                if (affData != null)
                {
                    MissionManagerData.Instance.SetFlag(affFlag, Mathf.Clamp(v, 0, 100));
                    Note($"{name} 好感（{affFlag}）{affData.State}");
                }
                else
                {
                    stat.SetValue(Mathf.Clamp(v, 0, 100));
                    Note($"{name} 好感 {stat.Value}");
                }
            }
            GUILayout.BeginHorizontal();
            GUILayout.Label(affData != null ? $"{name}（{affFlag}）" : name, _label, GUILayout.Width(150f));
            GUILayout.Label(current.ToString(), _label, GUILayout.Width(56f));
            foreach (int delta in new[] { -10, -1, 1, 10 })
            {
                if (GUILayout.Button(delta > 0 ? "+" + delta : delta.ToString(), _button, GUILayout.Width(52f)))
                {
                    Set(current + delta);
                }
            }
            GUILayout.Space(10f);
            _setText.TryGetValue(name, out string text);
            _setText[name] = GUILayout.TextField(text ?? "", 3, _field, GUILayout.Width(60f));
            if (GUILayout.Button("設成", _button, GUILayout.Width(64f)) && int.TryParse(_setText[name], out int value))
            {
                Set(value);
            }
            GUILayout.Space(10f);
            if (met)
            {
                GUILayout.Label("已結識", _done, GUILayout.Width(150f));
            }
            else if (GUILayout.Button("設成已結識", _button, GUILayout.Width(150f)))
            {
                stat.SetActive(true);
                if (flagData != null)
                {
                    MissionManagerData.Instance.SetFlag(flag, 1);
                }
                Note($"{name} 已結識{(flagData != null ? "，" + flag + " = 1" : "")}");
            }
            GUILayout.EndHorizontal();
        }
        GUILayout.EndScrollView();
    }

    private void Note(string message)
    {
        _message = message;
        Plugin.Log.LogInfo("作弊：" + message);
    }

    // 「認識 X」旗標（開發備註）：角色名稱 → 旗標
    private Dictionary<string, string> MeetFlags()
    {
        if (_meetFlags != null || MissionManagerData.Instance == null)
        {
            return _meetFlags ?? new Dictionary<string, string>();
        }
        _meetFlags = new Dictionary<string, string>();
        foreach (FlagCollectionData collection in MissionManagerData.Instance.FlagsCollection ?? new FlagCollectionData[0])
        {
            foreach (FlagData flag in collection?.List ?? new List<FlagData>())
            {
                Match m = flag != null && MeetFlagName.IsMatch(flag.name) ? Regex.Match(flag.DevNote ?? "", "^認識(.+)$") : Match.Empty;
                if (m.Success)
                {
                    string who = m.Groups[1].Value.Trim();
                    _meetFlags[Nicknames.TryGetValue(who, out string full) ? full : who] = flag.name;
                }
            }
        }
        return _meetFlags;
    }

    private void EnsureStyles()
    {
        if (_stylesReady)
        {
            return;
        }
        Font font = Font.CreateDynamicFontFromOSFont(FontNames, 20);
        _dim = new GUIStyle { normal = { background = SolidTexture(new Color(0f, 0f, 0f, 0.55f)) } };
        _window = new GUIStyle(GUI.skin.window) { font = font, fontSize = 22, padding = new RectOffset(18, 18, 40, 16) };
        Texture2D windowBackground = SolidTexture(new Color(0.09f, 0.09f, 0.11f, 0.97f));
        _window.normal.background = windowBackground;
        _window.onNormal.background = windowBackground;
        _window.normal.textColor = new Color(0.95f, 0.85f, 0.6f);
        _window.onNormal.textColor = _window.normal.textColor;
        _label = new GUIStyle(GUI.skin.label) { font = font, fontSize = 20, wordWrap = true };
        _label.normal.textColor = new Color(0.92f, 0.92f, 0.92f);
        _small = new GUIStyle(_label) { fontSize = 17 };
        _small.normal.textColor = new Color(0.75f, 0.75f, 0.78f);
        _done = new GUIStyle(_small);
        _done.normal.textColor = new Color(0.45f, 0.75f, 0.55f);
        _button = new GUIStyle(GUI.skin.button) { font = font, fontSize = 18 };
        _field = new GUIStyle(GUI.skin.textField) { font = font, fontSize = 18 };
        _toggle = new GUIStyle(GUI.skin.toggle) { font = font, fontSize = 20 };
        _toggle.normal.textColor = _label.normal.textColor;
        _toggle.onNormal.textColor = new Color(0.95f, 0.6f, 0.4f);
        _toggle.hover.textColor = Color.white;
        _toggle.onHover.textColor = _toggle.onNormal.textColor;
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

// 視窗開著時暫停遊戲本身的輸入，避免點擊穿透到遊戲 UI 或推進對話（作弊視窗的熱鍵仍由 Plugin.Update 直接讀鍵盤）
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
                Plugin.Log.LogWarning($"無法恢復輸入 {action?.name}：{e.Message}");
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
