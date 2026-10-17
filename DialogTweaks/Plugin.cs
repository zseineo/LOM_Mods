using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using Fungus;
using HarmonyLib;
using Mortal.Story;
using UnityEngine;
using UnityEngine.InputSystem;
using Mouse = UnityEngine.InputSystem.Mouse;

namespace LOM.DialogTweaks;

[BepInPlugin(GUID, NAME, VERSION)]
public class Plugin : BaseUnityPlugin
{
    public const string GUID = "zseineo.mortal.dialogtweaks";
    public const string NAME = "LOM DialogTweaks";
    public const string VERSION = "0.1.0";

    internal static ManualLogSource Log;
    internal static ConfigEntry<bool> WheelNext;
    internal static ConfigEntry<Key> AutoSkipKey;
    internal static ConfigEntry<bool> AutoSkipEnabled;
    internal static ConfigEntry<bool> ShowIndicator;

    private static readonly AccessTools.FieldRef<StoryManager, bool> SkipDialogRef =
        AccessTools.FieldRefAccess<StoryManager, bool>("_skipDialog");
    private static readonly AccessTools.FieldRef<StoryManager, bool> EnableSkipRef =
        AccessTools.FieldRefAccess<StoryManager, bool>("_enableSkip");
    private static readonly AccessTools.FieldRef<StoryManager, bool> LogOpenRef =
        AccessTools.FieldRefAccess<StoryManager, bool>("_logOpen");

    // 目前這句是否為已讀（由 LuaManager.GetStoryText 決定，與遊戲的已讀變色同一判斷）
    internal static bool CurrentLineSkippable;

    // 是否由本 Mod 打開了遊戲的跳過狀態
    private bool _engaged;
    private GUIStyle _indicatorStyle;

    private void Awake()
    {
        Log = Logger;
        WheelNext = Config.Bind("General", "WheelNext", true, "劇情中滾輪往下 = 下一句");
        AutoSkipKey = Config.Bind("AutoSkip", "ToggleKey", Key.F8, "開關「自動跳過已讀」的按鍵");
        AutoSkipEnabled = Config.Bind("AutoSkip", "Enabled", false,
            "自動跳過已讀（黃字）劇情；遇到未讀、選項、擲骰時自動停下。按鍵切換時會寫回此值");
        ShowIndicator = Config.Bind("AutoSkip", "ShowIndicator", true, "開啟自動跳過時在畫面左上角顯示提示");
        Harmony.CreateAndPatchAll(typeof(StoryPatches), GUID);
        Logger.LogInfo($"{NAME} {VERSION} loaded, auto skip key = {AutoSkipKey.Value}, enabled = {AutoSkipEnabled.Value}");
    }

    private void Update()
    {
        Keyboard keyboard = Keyboard.current;
        if (keyboard != null && keyboard[AutoSkipKey.Value].wasPressedThisFrame)
        {
            AutoSkipEnabled.Value = !AutoSkipEnabled.Value;
            Logger.LogInfo($"Auto skip: {AutoSkipEnabled.Value}");
        }

        StoryManager sm = StoryManager.Instance;
        if (sm == null || !sm.isActiveAndEnabled)
        {
            // 劇情場景卸載時 StoryManager.OnDestroy 自己會把 timeScale 還原
            _engaged = false;
            CurrentLineSkippable = false;
            return;
        }

        if (WheelNext.Value && CanAdvance(sm))
        {
            Mouse mouse = Mouse.current;
            if (mouse != null && mouse.scroll.ReadValue().y < 0f)
            {
                SayDialog.ActiveSayDialog.GetComponent<DialogInput>().SetNextLineFlag();
            }
        }

        UpdateAutoSkip(sm);
    }

    // 與 StoryManager.SubmitActionChanged（Enter 下一句）相同條件，另外要求對話框真的在畫面上
    private static bool CanAdvance(StoryManager sm)
    {
        if (!sm.EnableAction || sm.IsStoryPause)
        {
            return false;
        }
        SayDialog say = SayDialog.ActiveSayDialog;
        if (say == null || !say.gameObject.activeInHierarchy)
        {
            return false;
        }
        DialogInput input = say.GetComponent<DialogInput>();
        return input != null && input.enabled;
    }

    private void UpdateAutoSkip(StoryManager sm)
    {
        if (MenuShowing())
        {
            // 選項出現：停下，選完後要等下一句已讀才會再繼續
            CurrentLineSkippable = false;
        }

        bool paused = !sm.EnableAction || sm.IsStoryPause || LogOpenRef(sm);
        bool want = AutoSkipEnabled.Value && CurrentLineSkippable && EnableSkipRef(sm) && !paused;

        if (want)
        {
            if (!SkipDialogRef(sm))
            {
                sm.SkipDialog(enabled: true);
            }
            _engaged = true;
        }
        else if (_engaged)
        {
            _engaged = false;
            if (SkipDialogRef(sm))
            {
                if (paused)
                {
                    // 選單／紀錄開啟時 timeScale 由遊戲設為 0，只關掉旗標，不能呼叫 SkipDialog(false) 把時間恢復
                    SkipDialogRef(sm) = false;
                }
                else
                {
                    sm.SkipDialog(enabled: false);
                }
            }
        }
    }

    // 與 Fungus DialogInput 忽略點擊的條件相同
    private static bool MenuShowing()
    {
        MenuDialog menu = MenuDialog.ActiveMenuDialog;
        return menu != null && menu.IsActive() && menu.DisplayedOptionsCount > 0;
    }

    private void OnGUI()
    {
        if (!ShowIndicator.Value || !AutoSkipEnabled.Value || StoryManager.Instance == null)
        {
            return;
        }
        _indicatorStyle ??= new GUIStyle(GUI.skin.label)
        {
            fontSize = 18,
            fontStyle = FontStyle.Bold,
            normal = { textColor = new Color(1f, 0.85f, 0.3f) },
        };
        string text = $"自動跳過已讀 ON（{AutoSkipKey.Value}）";
        GUI.color = new Color(0f, 0f, 0f, 0.8f);
        GUI.Label(new Rect(12, 10, 400, 30), text, _indicatorStyle);
        GUI.color = Color.white;
        GUI.Label(new Rect(10, 8, 400, 30), text, _indicatorStyle);
    }
}

internal static class StoryPatches
{
    private static readonly AccessTools.FieldRef<StoryManager, bool> EnableSkipRef =
        AccessTools.FieldRefAccess<StoryManager, bool>("_enableSkip");

    // GetStoryText 每句呼叫一次：已讀（或設定了「可跳過未讀」）時遊戲會 EnableSkip(true)，未讀則 EnableSkip(false)
    [HarmonyPostfix]
    [HarmonyPatch(typeof(LuaManager), nameof(LuaManager.GetStoryText))]
    private static void GetStoryTextPostfix()
    {
        StoryManager sm = StoryManager.Instance;
        Plugin.CurrentLineSkippable = sm != null && EnableSkipRef(sm);
    }

    // 擲骰介面會自己 EnableSkip(true)，不讓自動跳過替玩家按過擲骰
    [HarmonyPostfix]
    [HarmonyPatch(typeof(DiceMenuDialog), "OnEnable")]
    private static void DiceOnEnablePostfix()
    {
        Plugin.CurrentLineSkippable = false;
    }
}
