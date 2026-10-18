using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using Mortal.Story;

namespace LOM.TimeMachine;

// 作弊：從「五塊錢」網頁的作弊分頁開關，設定存在 BepInEx 設定檔（Cheat 區）
internal static class Cheats
{
    // 決策選單（ch7_4_2_break_start_01）：滿足西武林盟條件（M70004 = 1）時，遊戲會藏起「戰他娘親」「退隱江湖」
    internal static ConfigEntry<bool> ShowAllDecisions;
    private static readonly HashSet<string> DecisionConditions = new HashSet<string> { "Ch_7_4_2_Break_01_001", "Ch_7_4_2_Break_01_002" };

    internal static void Bind(ConfigFile config)
    {
        ShowAllDecisions = config.Bind("Cheat", "ShowAllDecisions", false,
            "決策選單：滿足西武林盟條件時，仍顯示「決策：戰他娘親」「決策：退隱江湖」");
    }

    internal static string Json()
    {
        return "{\"showAllDecisions\":" + (ShowAllDecisions.Value ? "true" : "false") + "}";
    }

    internal static bool Set(string id, bool on)
    {
        switch (id)
        {
            case "showAllDecisions":
                ShowAllDecisions.Value = on;
                return true;
        }
        return false;
    }

    // 只改條件判斷的結果，排在事件紀錄之前，紀錄會記到改過的結果
    [HarmonyPostfix]
    [HarmonyPriority(Priority.First)]
    [HarmonyPatch(typeof(CheckPointManager), nameof(CheckPointManager.Condition))]
    private static void Condition(string name, ref bool __result)
    {
        if (!__result && ShowAllDecisions.Value && DecisionConditions.Contains(name))
        {
            __result = true;
            Plugin.Log.LogInfo($"[TimeMachine] 作弊：顯示決策選項 {name}");
        }
    }
}
