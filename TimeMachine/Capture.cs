using System;
using HarmonyLib;
using Mortal.Core;
using Mortal.Free;
using Mortal.Story;
using System.Collections.Generic;

namespace LOM.TimeMachine;

// 自動存檔規則：
// - 只在遊戲本身允許存檔的時間點存（養成回合開始、劇情自動存檔、劇情開放存檔）。
// - 同一次遊玩中，每一旬只存第一個時間點；換旬後的第一個時間點覆蓋該旬舊檔。
// - 尚未到達的旬不動。
// - 「同一次遊玩」從讀檔或開新遊戲起算；讀入的那一旬視為已存過，除非該旬還沒有任何時光機存檔。
internal static class Capture
{
    private static int _lastRound = -1;

    private static int RoundKey(int year, int month, MonthStageType stage)
    {
        return (year * 100 + month) * 10 + (int)stage;
    }

    internal static void OnLoaded(GameSave gameSave)
    {
        _lastRound = RoundKey(gameSave.CurrentYear, gameSave.CurrentMonth, gameSave.CurrentStage);
    }

    internal static void OnNewGame()
    {
        _lastRound = -1;
    }

    // useCurrentScriptAsStart：遊戲在存檔前會 SetStartScript(CurrentStoryScript)，
    // 尚未執行這步的時間點（養成回合開始且關閉「回家自動存檔」時）改在存檔副本上補上，不動到遊戲本身的狀態。
    internal static void TryCapture(string source, bool useCurrentScriptAsStart)
    {
        if (!Plugin.AutoCapture.Value)
        {
            return;
        }
        try
        {
            PlayerStatManagerData playerStat = PlayerStatManagerData.Instance;
            GameTime time = playerStat.GameTime;
            string mode = TimeStore.CurrentMode();
            int round = RoundKey(time.Year, time.Month, time.Stage);
            if (round == _lastRound && TimeStore.Exists(mode, time.Year, time.Month, time.Stage))
            {
                return;
            }
            GameSave gameSave = GameBridge.CreateSaveData();
            if (useCurrentScriptAsStart)
            {
                gameSave.StartStoryScript = playerStat.CurrentStoryScript;
            }
            AutoGameSave save = new AutoGameSave
            {
                Slot = SaveSystem.Instance.CurrentSlot,
                GameSave = gameSave
            };
            TimeStore.Write(mode, time.Year, time.Month, time.Stage, save, source);
            _lastRound = round;
            Plugin.Log.LogInfo($"[TimeMachine] 已存 {mode} 第{time.Year}年{time.Month}月{time.Stage}（路線 {TimeStore.CurrentRoute}，{source}，腳本 {gameSave.StartStoryScript}）");
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[TimeMachine] 自動存檔失敗（{source}）：{e}");
        }
    }
}

internal static class CapturePatches
{
    // 養成模式回合開始（行動次數全滿）：與遊戲「回家自動存檔」同一個時間點
    [HarmonyPrefix]
    [HarmonyPatch(typeof(FreeManager), "Start")]
    private static void FreeManagerStart()
    {
        PlayerStatManagerData playerStat = PlayerStatManagerData.Instance;
        if (playerStat.CurrentActionCount == playerStat.MaxActionCount)
        {
            Capture.TryCapture(Sources.FreeRound, useCurrentScriptAsStart: true);
            KeyNodes.OnFreeRoundStart();
        }
    }

    // 每段劇情腳本開始執行：檢查是不是關鍵節點
    [HarmonyPrefix]
    [HarmonyPatch(typeof(LuaManager), "ExecuteLuaScript")]
    private static void LuaExecuteScript(LuaManager __instance)
    {
        KeyNodes.OnScript(__instance.ScriptName);
        DrawLog.MarkPlayed(__instance.ScriptName);
    }

    // 劇情自動存檔（遊戲已先 SetStartScript）
    [HarmonyPostfix]
    [HarmonyPatch(typeof(LuaManager), nameof(LuaManager.AutoSave))]
    private static void LuaAutoSave()
    {
        Capture.TryCapture(Sources.StoryAutoSave, useCurrentScriptAsStart: false);
        KeyNodes.OnSavePoint();
    }

    // 劇情腳本內的養成自動存檔，條件與遊戲相同
    [HarmonyPostfix]
    [HarmonyPatch(typeof(LuaManager), nameof(LuaManager.AutoFreeSave))]
    private static void LuaAutoFreeSave()
    {
        PlayerStatManagerData playerStat = PlayerStatManagerData.Instance;
        if (playerStat.CurrentActionCount == playerStat.MaxActionCount)
        {
            Capture.TryCapture(Sources.FreeAutoSave, useCurrentScriptAsStart: false);
        }
    }

    // 劇情開放存檔（遊戲已先 SetStartScript）
    [HarmonyPostfix]
    [HarmonyPatch(typeof(LuaManager), nameof(LuaManager.ToggleSaveButton))]
    private static void LuaToggleSaveButton(int active)
    {
        if (active == 1)
        {
            Capture.TryCapture(Sources.SaveEnabled, useCurrentScriptAsStart: false);
            KeyNodes.OnSavePoint();
        }
    }

    // 地點隨機事件抽完：記下結果與當下每個候選的權重
    [HarmonyPostfix]
    [HarmonyPatch(typeof(PositionResultData), nameof(PositionResultData.GetResult))]
    private static void PositionGetResult(PositionResultData __instance, string __result)
    {
        try
        {
            System.Text.StringBuilder rates = new System.Text.StringBuilder("{");
            bool first = true;
            foreach (PositionEventData item in __instance.List)
            {
                if (item == null)
                {
                    continue;
                }
                rates.Append(first ? "" : ",").Append(Json.Str(item.name)).Append(':').Append(item.GetRate());
                first = false;
            }
            GameTime time = PlayerStatManagerData.Instance.GameTime;
            DrawLog.Add(new DrawLog.Entry
            {
                Group = __instance.name,
                Result = __result,
                Time = $"第{time.Year}年{time.Month}月{time.Stage}",
                Rates = rates.Append('}').ToString()
            });
            Plugin.Log.LogInfo($"[TimeMachine] 地點抽籤 {__instance.name} → {__result}");
        }
        catch (Exception e)
        {
            Plugin.Log.LogWarning($"[TimeMachine] 抽籤紀錄失敗：{e.Message}");
        }
    }
    // 所有讀檔（欄位、自動存檔、劇情重試、時光機）都經過這裡
    [HarmonyPostfix]
    [HarmonyPatch(typeof(SaveSystem), "ExecuteLoadGameData")]
    private static void ExecuteLoadGameData(GameSave gameSave)
    {
        Capture.OnLoaded(gameSave);
        KeyNodes.Reset();
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(SaveSystem), nameof(SaveSystem.NewGameData))]
    private static void NewGameData()
    {
        Capture.OnNewGame();
        KeyNodes.Reset();
    }

    [HarmonyPostfix]
    [HarmonyPatch(typeof(SaveSystem), nameof(SaveSystem.NewActGameData))]
    private static void NewActGameData()
    {
        Capture.OnNewGame();
        KeyNodes.Reset();
    }
}

// 地點隨機事件的抽籤紀錄（最近 40 次），給網頁核對實際結果
internal static class DrawLog
{
    internal sealed class Entry
    {
        public string Group;
        public string Result;
        public string Time;
        public string Rates;
        public bool Played;
    }

    // 結果腳本真的開始執行時標記（被前一層事件接走、直接進戰鬥時就不會播）
    internal static void MarkPlayed(string script)
    {
        lock (Entries)
        {
            for (int i = Entries.Count - 1; i >= 0 && i >= Entries.Count - 4; i--)
            {
                if (!Entries[i].Played && string.Equals(Entries[i].Result, script, StringComparison.OrdinalIgnoreCase))
                {
                    Entries[i].Played = true;
                    return;
                }
            }
        }
    }

    private static readonly List<Entry> Entries = new List<Entry>();

    internal static void Add(Entry entry)
    {
        lock (Entries)
        {
            Entries.Add(entry);
            if (Entries.Count > 40)
            {
                Entries.RemoveAt(0);
            }
        }
    }

    internal static string Json()
    {
        lock (Entries)
        {
            System.Text.StringBuilder sb = new System.Text.StringBuilder("[");
            for (int i = 0; i < Entries.Count; i++)
            {
                Entry e = Entries[i];
                sb.Append(i > 0 ? "," : "").Append("{\"group\":").Append(LOM.TimeMachine.Json.Str(e.Group))
                  .Append(",\"result\":").Append(LOM.TimeMachine.Json.Str(e.Result))
                  .Append(",\"time\":").Append(LOM.TimeMachine.Json.Str(e.Time))
                  .Append(",\"rates\":").Append(e.Rates)
                  .Append(",\"played\":").Append(e.Played ? "true" : "false").Append('}');
            }
            return sb.Append(']').ToString();
        }
    }
}

internal static class Sources
{
    internal const string FreeRound = "free_round";
    internal const string StoryAutoSave = "story_auto";
    internal const string FreeAutoSave = "free_auto";
    internal const string SaveEnabled = "save_enabled";
    internal const string KeyNode = "key_node";
    internal const string KeyNodeAfter = "key_node_after";

    internal static string Describe(string source)
    {
        if (source != null && source.StartsWith(KeyNodeAfter + "|"))
        {
            return "關鍵節點（觸發後第一個可存檔的時間點）";
        }
        if (source != null && source.StartsWith(KeyNode))
        {
            return "關鍵節點（觸發前最後一個養成回合開始）";
        }
        switch (source)
        {
            case FreeRound: return "養成回合開始";
            case StoryAutoSave: return "劇情自動存檔";
            case FreeAutoSave: return "養成自動存檔";
            case SaveEnabled: return "劇情開放存檔";
            default: return source;
        }
    }
}
