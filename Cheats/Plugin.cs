using System.Collections.Generic;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using HarmonyLib;
using Mortal.Story;
using UnityEngine.InputSystem;

namespace LOM.Cheats;

// 作弊：遊戲本來不允許的選擇。按 F9 開視窗切換，設定存在 BepInEx 設定檔
[BepInPlugin(GUID, NAME, VERSION)]
public class Plugin : BaseUnityPlugin
{
    public const string GUID = "zseineo.mortal.cheats";
    public const string NAME = "LOM Cheats";
    public const string VERSION = "0.1.0";

    internal static ManualLogSource Log;
    internal static ConfigEntry<Key> ToggleKey;
    // 決策選單（ch7_4_2_break_start_01）：滿足西武林盟條件（M70004 = 1）時，遊戲會藏起「戰他娘親」「退隱江湖」
    internal static ConfigEntry<bool> ShowAllDecisions;

    private CheatWindow _window;

    private void Awake()
    {
        Log = Logger;
        ToggleKey = Config.Bind("General", "ToggleKey", Key.F9, "開關作弊視窗的按鍵");
        ShowAllDecisions = Config.Bind("Cheat", "ShowAllDecisions", false,
            "決策選單：滿足西武林盟條件時，仍顯示「決策：戰他娘親」「決策：退隱江湖」");
        _window = new CheatWindow();
        Harmony.CreateAndPatchAll(typeof(DecisionPatch), GUID);
        Logger.LogInfo($"{NAME} {VERSION} loaded, toggle key = {ToggleKey.Value}");
    }

    private void Update()
    {
        Keyboard keyboard = Keyboard.current;
        if (keyboard != null && keyboard[ToggleKey.Value].wasPressedThisFrame)
        {
            _window.Toggle();
        }
    }

    private void OnGUI()
    {
        _window.OnGUI();
    }
}

internal static class DecisionPatch
{
    private static readonly HashSet<string> DecisionConditions = new HashSet<string> { "Ch_7_4_2_Break_01_001", "Ch_7_4_2_Break_01_002" };

    // 只改條件判斷的結果，排在其他 Mod（時光機的事件紀錄）之前，紀錄會記到改過的結果
    [HarmonyPostfix]
    [HarmonyPriority(Priority.First)]
    [HarmonyPatch(typeof(CheckPointManager), nameof(CheckPointManager.Condition))]
    private static void Condition(string name, ref bool __result)
    {
        if (!__result && Plugin.ShowAllDecisions.Value && DecisionConditions.Contains(name))
        {
            __result = true;
            Plugin.Log.LogInfo($"作弊：顯示決策選項 {name}");
        }
    }
}
