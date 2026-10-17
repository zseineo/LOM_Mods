// 讀活俠傳存檔（BinaryFormatter）印出時間、腳本、指定的旗標與數值。
// 用法：SaveDump <存檔.dat> [旗標或數值名稱的前綴...]
using System;
using System.IO;
using System.Linq;
using System.Runtime.Serialization.Formatters.Binary;
using Mortal.Core;

internal static class Program
{
    private static int Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        object obj;
        using (FileStream stream = File.OpenRead(args[0]))
        {
            obj = new BinaryFormatter().Deserialize(stream);
        }
        GameSave save = obj is AutoGameSave auto ? auto.GameSave : (GameSave)obj;
        if (args.Length > 1 && args[1] == "--json")
        {
            // 輸出與 Mod 網頁 /api/state 相同格式，供離線測試
            string Pairs<T>(System.Collections.Generic.IEnumerable<T> list, Func<T, string> k, Func<T, int> v) =>
                string.Join(",", list.GroupBy(k).Select(g => $"\"{g.Key}\":{v(g.First())}"));
            Console.WriteLine("{\"live\":true,\"inGame\":true,\"time\":{\"y\":" + save.CurrentYear + ",\"m\":" + save.CurrentMonth + ",\"s\":" + (int)save.CurrentStage + "}"
                + ",\"flags\":{" + Pairs(save.EventFlags, f => f.Name, f => f.State) + "}"
                + ",\"stats\":{" + Pairs(save.Stats, x => x.Key, x => x.Value) + "}"
                + ",\"rel\":{" + Pairs(save.Relationships, x => x.Key, x => x.Value) + "}"
                + ",\"talents\":{" + Pairs(save.Talents, x => x.Id, x => x.Level) + "}}");
            return 0;
        }
        if (obj is AutoGameSave a) Console.WriteLine($"Slot: {a.Slot}");
        Console.WriteLine($"Time: Y{save.CurrentYear} M{save.CurrentMonth} {save.CurrentStage}  Scene: {save.CurrentScene}  StartScript: {save.StartStoryScript}  Saved: {new DateTime(save.TimeTick)}");
        Console.WriteLine($"MainMission: {save.MainMission.Key}");
        string[] filters = args.Skip(1).ToArray();
        bool Match(string name) => filters.Length == 0 || filters.Any(f => name.StartsWith(f, StringComparison.OrdinalIgnoreCase));
        foreach (EventFlagSave flag in save.EventFlags.Where(f => Match(f.Name)))
            Console.WriteLine($"flag {flag.Name} = {flag.State}");
        foreach (StatSave stat in save.Stats)
        {
            string line = string.Join(" ", stat.GetType().GetFields().Select(f => $"{f.Name}={f.GetValue(stat)}"));
            if (filters.Length == 0 || filters.Any(f => line.IndexOf(f, StringComparison.OrdinalIgnoreCase) >= 0))
                Console.WriteLine($"stat {line}");
        }
        foreach (RelationshipSave rel in save.Relationships)
        {
            string line = string.Join(" ", rel.GetType().GetFields().Select(f => $"{f.Name}={f.GetValue(rel)}"));
            if (filters.Length == 0 || filters.Any(f => line.IndexOf(f, StringComparison.OrdinalIgnoreCase) >= 0))
                Console.WriteLine($"rel {line}");
        }
        foreach (MissionSave m in save.SubMissions.Where(m => Match(m.Name)))
            Console.WriteLine($"mission {m.Name} = {m.Key}");
        return 0;
    }
}
