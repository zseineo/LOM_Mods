using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using HarmonyLib;
using Mortal.Core;
using Mortal.Story;

namespace LOM.TimeMachine;

// 事件紀錄：每段劇情腳本、任務啟動、旗標變化、分歧／條件判斷結果、擲骰，寫到 TimeMachine/<SteamID>/event_log.txt
// 給查「為什麼沒觸發」用：哪個分歧走了哪邊、當時旗標是多少，一看就知道。
internal static class EventLog
{
    private static StreamWriter _writer;
    private static string _path;
    private static readonly List<string> Recent = new List<string>();

    // 最近執行的劇情腳本（新的在後），給網頁顯示「目前的事件」
    internal static string[] RecentScripts()
    {
        lock (Recent)
        {
            return Recent.ToArray();
        }
    }

    internal static void Script(string name)
    {
        lock (Recent)
        {
            Recent.Add(name);
            if (Recent.Count > 8)
            {
                Recent.RemoveAt(0);
            }
        }
        Write("腳本", name);
    }

    internal static void Write(string kind, string text)
    {
        if (!Plugin.EventLogEnabled.Value)
        {
            return;
        }
        try
        {
            string path = Path.Combine(TimeStore.Root, "event_log.txt");
            if (_writer == null || _path != path)
            {
                _writer?.Dispose();
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                _writer = new StreamWriter(path, true, new UTF8Encoding(true)) { AutoFlush = true };
                _path = path;
            }
            GameTime time = PlayerStatManagerData.Instance?.GameTime;
            string when = time != null ? $"第{time.Year}年{time.Month}月{time.Stage}" : "";
            _writer.WriteLine($"{DateTime.Now:yyyy-MM-dd HH:mm:ss}\t{when}\t{kind}\t{text}");
        }
        catch (Exception e)
        {
            Plugin.Log.LogWarning($"[TimeMachine] 事件紀錄寫檔失敗：{e.Message}");
        }
    }
}

internal static class EventLogPatches
{
    [HarmonyPrefix]
    [HarmonyPatch(typeof(StatModifyManager), nameof(StatModifyManager.Mission))]
    private static void Mission(string name, string key)
    {
        EventLog.Write("任務", $"{name} → {key}");
    }

    [HarmonyPrefix]
    [HarmonyPatch(typeof(MissionManagerData), nameof(MissionManagerData.SetFlag))]
    private static void SetFlag(MissionManagerData __instance, string name, int value)
    {
        int old = __instance.GetFlag(name)?.State ?? 0;
        if (old != value)
        {
            EventLog.Write("旗標", $"{name} {old} → {value}");
        }
    }

    [HarmonyPrefix]
    [HarmonyPatch(typeof(MissionManagerData), nameof(MissionManagerData.AddFlag))]
    private static void AddFlag(MissionManagerData __instance, string name, int value)
    {
        int old = __instance.GetFlag(name)?.State ?? 0;
        EventLog.Write("旗標", $"{name} {old} + {value}");
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(CheckPointManager), nameof(CheckPointManager.Switch))]
    private static void Switch(string name, int __result)
    {
        EventLog.Write("分歧", $"{name} → 第 {__result} 項");
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(CheckPointManager), nameof(CheckPointManager.Condition))]
    private static void Condition(string name, bool __result)
    {
        EventLog.Write("條件", $"{name} → {(__result ? "成立" : "不成立")}");
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(CheckPointManager), nameof(CheckPointManager.Dice))]
    private static void Dice(string name, int random, DiceCheckResult __result)
    {
        EventLog.Write("擲骰", $"{name} 骰 {random} → 結果 {__result?.Result}");
    }
}
