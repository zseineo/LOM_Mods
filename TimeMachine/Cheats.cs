using System.Collections.Generic;
using BepInEx.Configuration;
using HarmonyLib;
using Mortal.Story;

namespace LOM.TimeMachine;

// 作弊：從「算命仙」網頁的作弊分頁開關，設定存在 BepInEx 設定檔（Cheat 區）
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

    // 網頁送來的修改：排到主執行緒做（GuideServer.Tick 呼叫 RunPending）
    private static readonly System.Collections.Concurrent.ConcurrentQueue<System.Action> Pending = new System.Collections.Concurrent.ConcurrentQueue<System.Action>();

    internal static void RunPending()
    {
        while (Pending.TryDequeue(out System.Action action))
        {
            try
            {
                action();
            }
            catch (System.Exception e)
            {
                Plugin.Log.LogWarning($"[TimeMachine] 作弊失敗：{e.Message}");
            }
        }
    }

    // 好感：set（設成）或 add（加減），夾在 0～100；meet = 1 時設成已結識，flag 是一起設成 1 的「認識 X」旗標
    internal static bool QueueRelationship(string key, string set, string add, bool meet, string flag)
    {
        if (!System.Enum.TryParse(key, out Mortal.Core.RelationshipStatType type))
        {
            return false;
        }
        if (!string.IsNullOrEmpty(flag) && !System.Text.RegularExpressions.Regex.IsMatch(flag, "^G(1000|300)\\d+$"))
        {
            return false;
        }
        Pending.Enqueue(() =>
        {
            Mortal.Core.RelationshipStat stat = Mortal.Core.PlayerStatManagerData.Instance.Relationships.Get(type);
            if (stat == null)
            {
                return;
            }
            if (int.TryParse(set, out int value))
            {
                stat.SetValue(UnityEngine.Mathf.Clamp(value, 0, 100));
            }
            else if (int.TryParse(add, out int delta))
            {
                stat.AddValue(delta);
            }
            if (meet)
            {
                stat.SetActive(true);
                if (!string.IsNullOrEmpty(flag))
                {
                    Mortal.Core.MissionManagerData.Instance.SetFlag(flag, 1);
                }
            }
            EventLog.Write("作弊", $"好感 {type} = {stat.Value}{(meet ? "，已結識" : "")}{(string.IsNullOrEmpty(flag) || !meet ? "" : "，" + flag + " = 1")}");
        });
        return true;
    }

    // 好感一覽（主執行緒呼叫）
    internal static string RelationshipsJson()
    {
        System.Text.StringBuilder sb = new System.Text.StringBuilder("[");
        foreach (Mortal.Core.RelationshipStat stat in Mortal.Core.PlayerStatManagerData.Instance.Relationships.List)
        {
            if (stat == null)
            {
                continue;
            }
            sb.Append(sb.Length > 1 ? "," : "").Append("{\"key\":").Append(LOM.TimeMachine.Json.Str(stat.Type.ToString()))
              .Append(",\"value\":").Append(stat.Value).Append(",\"active\":").Append(stat.Active ? "true" : "false").Append('}');
        }
        return sb.Append(']').ToString();
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
