using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.Serialization.Formatters.Binary;
using Mortal.Core;

namespace LOM.TimeMachine;

internal sealed class KeyNode
{
    public string Id;
    public string Name;
    public string[] Scripts;
    public string[] Flags = Array.Empty<string>();
    public int Year;
    public int Month;
    public int Stage;
    public string When;
    // true：腳本執行後「第一個可存檔的時間點」存成節點（用於劇情場景中的停留，例如江陵）；false：存觸發前最後一個養成回合
    public bool AfterTrigger;
}

// 關鍵節點：劇情觸發時，另存「觸發前最後一個養成回合開始（行動次數全滿）」的狀態。
// 事件在旬中觸發 → 就是那一旬的開頭；事件在旬初直接觸發（主線、月會）→ 是前一個還能行動的旬。
// 讀回來還有行動次數，可以先準備（換心上人、補屬性）再觸發。
// AfterTrigger 節點例外：停留期間是劇情場景、不經過養成回合（例如江陵），改存腳本執行後第一個可存檔的時間點。
internal static class KeyNodes
{
    internal static readonly KeyNode[] All =
    {
        new KeyNode { Id = "yejia", Name = "葉家兄妹（客棧）", Scripts = new[] { "s0018_02" }, Year = 1, Month = 8, Stage = 1,
            When = "第1年8月～第2年1月：觸發「讀報」事件後一個月內，點大門到客棧" },
        new KeyNode { Id = "liuxue", Name = "留學（月會）", Scripts = new[] { "ch2_3_2" }, Year = 2, Month = 2, Stage = 1,
            When = "第2年2月上旬月會：選「我想去崆峒派留學」或不留學" },
        new KeyNode { Id = "pomiao", Name = "破廟（不留學）", Scripts = new[] { "ch2_4_2" }, Year = 2, Month = 6, Stage = 1,
            When = "第2年6月上旬：住破廟或住客棧" },
        new KeyNode { Id = "jiangling", Name = "江陵", Scripts = new[] { "ch3_6_1" }, AfterTrigger = true, Year = 2, Month = 9, Stage = 1,
            When = "約第2年9月上旬剛到江陵（住進南宮世家大宅）；之後第2年10月小梅現身時跟她走是小梅線，選「祝妳好運」是郁竹線" },
        new KeyNode { Id = "dashixiong", Name = "大師兄下山", Scripts = new[] { "ch4_5_1" }, Year = 3, Month = 1, Stage = 2,
            When = "第3年1月中旬：選要不要陪大師兄下山（心上人是小師妹時一定得去）" },
        new KeyNode { Id = "xiaoshimei", Name = "小師妹招親", Scripts = new[] { "ch5_2_5" }, Year = 3, Month = 5, Stage = 1,
            When = "第3年5月上旬：小師妹招親" },
        new KeyNode { Id = "xueshan", Name = "大雪山（月會）", Scripts = new[] { "meeting_start_01" }, Flags = new[] { "M50021=1", "M10017=0" },
            Year = 3, Month = 6, Stage = 1, When = "月會出現「雪山行」選項的那個月（約第3年6月上旬）" },
        new KeyNode { Id = "wulin", Name = "武林大會（出發）", Scripts = new[] { "ch6_3_1" }, Year = 3, Month = 9, Stage = 1,
            When = "第3年9月上旬：出發前往武林大會" },
        new KeyNode { Id = "juece", Name = "決策（武林盟／退隱）", Scripts = new[] { "ch7_3_1" }, Year = 3, Month = 12, Stage = 1,
            When = "第3年12月上旬決議：成立武林盟／響應武林盟／退隱江湖／戰他娘親" },
    };

    private static byte[] _snapshot;
    private static readonly HashSet<string> Written = new HashSet<string>();
    // AfterTrigger 節點已觸發、等下一個可存檔時間點寫檔：節點 → 觸發紀錄
    private static readonly Dictionary<KeyNode, string> Pending = new Dictionary<KeyNode, string>();

    internal static void Reset()
    {
        _snapshot = null;
        Written.Clear();
        Pending.Clear();
    }

    // 養成回合開始（行動次數全滿）時記下狀態，等節點劇情觸發才寫檔
    internal static void OnFreeRoundStart()
    {
        if (Plugin.Paused)
        {
            // 暫停期間經過的回合不記；恢復後節點才不會存到暫停前的舊狀態
            _snapshot = null;
        }
        if (!Plugin.Capturing || TimeStore.CurrentMode() != TimeStore.MainMode)
        {
            return;
        }
        try
        {
            GameSave gameSave = GameBridge.CreateSaveData();
            gameSave.StartStoryScript = PlayerStatManagerData.Instance.CurrentStoryScript;
            AutoGameSave save = new AutoGameSave
            {
                Slot = SaveSystem.Instance.CurrentSlot,
                GameSave = gameSave
            };
            using MemoryStream stream = new MemoryStream();
            new BinaryFormatter().Serialize(stream, save);
            _snapshot = stream.ToArray();
            Written.Clear();
        }
        catch (Exception e)
        {
            _snapshot = null;
            Plugin.Log.LogError($"[TimeMachine] 關鍵節點快照失敗：{e}");
        }
    }

    internal static void OnScript(string script)
    {
        if (!Plugin.Capturing || string.IsNullOrEmpty(script) || TimeStore.CurrentMode() != TimeStore.MainMode)
        {
            return;
        }
        foreach (KeyNode node in All)
        {
            if (Written.Contains(node.Id) || Array.FindIndex(node.Scripts, s => string.Equals(s, script, StringComparison.OrdinalIgnoreCase)) < 0 || !FlagsMatch(node))
            {
                continue;
            }
            Written.Add(node.Id);
            if (node.AfterTrigger)
            {
                GameTime now = PlayerStatManagerData.Instance.GameTime;
                Pending[node] = $"{Sources.KeyNodeAfter}|{now.Year}|{now.Month}|{(int)now.Stage}|{script}";
                continue;
            }
            if (_snapshot == null)
            {
                Plugin.Log.LogInfo($"[TimeMachine] 關鍵節點「{node.Name}」觸發，但這次遊玩還沒有觸發前的養成回合，略過");
                continue;
            }
            try
            {
                GameTime time = PlayerStatManagerData.Instance.GameTime;
                TimeStore.WriteNode(TimeStore.MainMode, node.Id, _snapshot, $"{Sources.KeyNode}|{time.Year}|{time.Month}|{(int)time.Stage}|{script}");
                Plugin.Log.LogInfo($"[TimeMachine] 關鍵節點「{node.Name}」：第{time.Year}年{time.Month}月{time.Stage}觸發（{script}），已存觸發前的養成回合");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"[TimeMachine] 關鍵節點存檔失敗（{node.Name}）：{e}");
            }
        }
    }

    // 劇情自動存檔／劇情開放存檔（遊戲已先 SetStartScript）：把等待中的 AfterTrigger 節點存成目前狀態
    internal static void OnSavePoint()
    {
        if (Pending.Count == 0)
        {
            return;
        }
        try
        {
            if (!Plugin.Capturing || TimeStore.CurrentMode() != TimeStore.MainMode)
            {
                return;
            }
            AutoGameSave save = new AutoGameSave
            {
                Slot = SaveSystem.Instance.CurrentSlot,
                GameSave = GameBridge.CreateSaveData()
            };
            using MemoryStream stream = new MemoryStream();
            new BinaryFormatter().Serialize(stream, save);
            byte[] data = stream.ToArray();
            GameTime time = PlayerStatManagerData.Instance.GameTime;
            foreach (KeyValuePair<KeyNode, string> pair in Pending)
            {
                TimeStore.WriteNode(TimeStore.MainMode, pair.Key.Id, data, pair.Value);
                Plugin.Log.LogInfo($"[TimeMachine] 關鍵節點「{pair.Key.Name}」：已存觸發後第一個可存檔的時間點（第{time.Year}年{time.Month}月{time.Stage}）");
            }
        }
        catch (Exception e)
        {
            Plugin.Log.LogError($"[TimeMachine] 關鍵節點存檔失敗：{e}");
        }
        finally
        {
            Pending.Clear();
        }
    }

    private static bool FlagsMatch(KeyNode node)
    {
        foreach (string condition in node.Flags)
        {
            string[] parts = condition.Split('=');
            FlagData flag = MissionManagerData.Instance.GetFlag(parts[0]);
            if (flag == null || flag.State != int.Parse(parts[1]))
            {
                return false;
            }
        }
        return true;
    }

    // 「key_node|年|月|旬|腳本」或「key_node_after|年|月|旬|腳本」
    internal static bool TryParseTrigger(string source, out int year, out int month, out int stage, out string script)
    {
        year = month = stage = 0;
        script = null;
        string[] parts = (source ?? "").Split('|');
        if (parts.Length != 5 || (parts[0] != Sources.KeyNode && parts[0] != Sources.KeyNodeAfter))
        {
            return false;
        }
        script = parts[4];
        return int.TryParse(parts[1], out year) && int.TryParse(parts[2], out month) && int.TryParse(parts[3], out stage);
    }
}
