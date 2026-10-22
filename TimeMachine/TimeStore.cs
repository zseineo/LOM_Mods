using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.Serialization.Formatters.Binary;
using System.Text.RegularExpressions;
using Mortal.Core;
using UnityEngine;

namespace LOM.TimeMachine;

internal sealed class TimeEntry
{
    public string Mode;
    public int Year;
    public int Month;
    public string Path;
    public MonthStageType Stage;
    public string Scene;
    public string Script;
    public DateTime SavedAt;
    public string Source;
    public DateTime FileTime;

    public int SortKey => (Year * 100 + Month) * 10 + (int)Stage;
}

// 時光機存檔：每個模式、每一旬一個檔案，同一旬的新存檔直接覆蓋。
// 位置在存檔資料夾的上一層（TimeMachine/<SteamID>/[_routes/<路線>/]<模式>/），不在遊戲的存檔欄位內，也不會被 Steam 雲端同步。
internal static class TimeStore
{
    internal const string MainMode = "main";
    internal const string ActMode = "act1";

    private static readonly Regex FileNamePattern = new Regex(@"^Y(\d+)_M(\d+)_S(\d)\.dat$");
    private static readonly Dictionary<string, TimeEntry> Cache = new Dictionary<string, TimeEntry>();

    internal static string Root => System.IO.Path.Combine(Application.persistentDataPath, "TimeMachine", GameBridge.UserFolder());

    // ---------- 路線：每條路線一套獨立的時光機存檔，切換後只寫入目前路線 ----------
    // 「預設」路線就是原本的位置（Root/<模式>/），其他路線放在 Root/_routes/<名稱>/<模式>/
    internal const string DefaultRoute = "預設";
    private const string RoutesDir = "_routes";
    private static string _route;
    private static string _routeRoot;

    internal static string CurrentRoute
    {
        get
        {
            string root = Root;
            if (_route == null || _routeRoot != root)
            {
                _routeRoot = root;
                string file = System.IO.Path.Combine(root, "route.txt");
                string saved = File.Exists(file) ? File.ReadAllText(file).Trim() : "";
                _route = saved.Length > 0 && Directory.Exists(RouteDir(saved)) ? saved : DefaultRoute;
            }
            return _route;
        }
    }

    private static string RouteDir(string route)
    {
        return route == DefaultRoute ? Root : System.IO.Path.Combine(Root, RoutesDir, route);
    }

    private static string RouteRoot => RouteDir(CurrentRoute);

    internal static List<string> Routes()
    {
        List<string> routes = new List<string> { DefaultRoute };
        string dir = System.IO.Path.Combine(Root, RoutesDir);
        if (Directory.Exists(dir))
        {
            foreach (string sub in Directory.GetDirectories(dir))
            {
                routes.Add(System.IO.Path.GetFileName(sub));
            }
        }
        return routes;
    }

    internal static void SwitchRoute(string route)
    {
        Directory.CreateDirectory(Root);
        File.WriteAllText(System.IO.Path.Combine(Root, "route.txt"), route == DefaultRoute ? "" : route);
        _route = route;
        _routeRoot = Root;
    }

    // 新增路線；copyUntil 不為 null 時，把目前路線中「不晚於這一旬」的存檔與關鍵節點複製過去（從這裡分岔）
    internal static string CreateRoute(string name, int? copyUntil)
    {
        name = (name ?? "").Trim();
        if (name.Length == 0)
        {
            return L.T("請輸入路線名稱");
        }
        if (name.IndexOfAny(System.IO.Path.GetInvalidFileNameChars()) >= 0 || name == RoutesDir)
        {
            return L.T("名稱不能包含 \\ / : * ? \" < > | 等符號");
        }
        if (Routes().Contains(name))
        {
            return L.T("已經有同名的路線");
        }
        string target = System.IO.Path.Combine(Root, RoutesDir, name);
        Directory.CreateDirectory(target);
        if (copyUntil.HasValue)
        {
            foreach (string mode in Modes())
            {
                string to = System.IO.Path.Combine(target, mode);
                Directory.CreateDirectory(to);
                List<TimeEntry> entries = List(mode);
                entries.AddRange(ListNodes(mode).Values);
                foreach (TimeEntry e in entries)
                {
                    // 只有目前模式要看時間；其他模式（序章／本篇）整套複製
                    if (mode == CurrentMode() && e.SortKey > copyUntil.Value)
                    {
                        continue;
                    }
                    string file = System.IO.Path.GetFileName(e.Path);
                    File.Copy(e.Path, System.IO.Path.Combine(to, file), true);
                    if (File.Exists(e.Path + ".meta"))
                    {
                        File.Copy(e.Path + ".meta", System.IO.Path.Combine(to, file + ".meta"), true);
                    }
                }
            }
        }
        SwitchRoute(name);
        return null;
    }

    // 刪除路線（預設路線不能刪）；刪的是目前路線時切回預設
    internal static string DeleteRoute(string name)
    {
        if (name == DefaultRoute || !Routes().Contains(name))
        {
            return L.T("這條路線不能刪除");
        }
        string dir = RouteDir(name);
        Directory.Delete(dir, true);
        foreach (string key in new List<string>(Cache.Keys))
        {
            if (key.StartsWith(dir + System.IO.Path.DirectorySeparatorChar))
            {
                Cache.Remove(key);
            }
        }
        if (CurrentRoute == name || _route == name)
        {
            SwitchRoute(DefaultRoute);
        }
        return null;
    }

    internal static int CountSaves(string route)
    {
        string dir = RouteDir(route);
        return Directory.Exists(dir) ? Directory.GetFiles(dir, "*.dat", SearchOption.AllDirectories).Length : 0;
    }

    // 序章（act1 模式）用獨立的時間軸，避免與本篇的同年月互相覆蓋
    internal static string CurrentMode()
    {
        return SaveSystem.Instance.CurrentSlot == "act1" ? ActMode : MainMode;
    }

    internal static string PathFor(string mode, int year, int month, MonthStageType stage)
    {
        return System.IO.Path.Combine(RouteRoot, mode, $"Y{year}_M{month:00}_S{(int)stage}.dat");
    }

    internal static bool Exists(string mode, int year, int month, MonthStageType stage)
    {
        return File.Exists(PathFor(mode, year, month, stage));
    }

    internal static void Write(string mode, int year, int month, MonthStageType stage, AutoGameSave save, string source)
    {
        string path = PathFor(mode, year, month, stage);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path));
        string tmp = path + ".tmp";
        using (FileStream stream = new FileStream(tmp, FileMode.Create, FileAccess.Write))
        {
            new BinaryFormatter().Serialize(stream, save);
            stream.Flush(flushToDisk: true);
        }
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        File.Move(tmp, path);
        File.WriteAllText(path + ".meta", source);
        Cache.Remove(path);
    }

    // 關鍵節點：每個節點一個檔（N_<id>.dat），再次經過同一節點時覆蓋
    internal static string NodePath(string mode, string id)
    {
        return System.IO.Path.Combine(RouteRoot, mode, $"N_{id}.dat");
    }

    internal static void WriteNode(string mode, string id, byte[] data, string source)
    {
        string path = NodePath(mode, id);
        Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path));
        string tmp = path + ".tmp";
        File.WriteAllBytes(tmp, data);
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        File.Move(tmp, path);
        File.WriteAllText(path + ".meta", source);
        Cache.Remove(path);
    }

    internal static Dictionary<string, TimeEntry> ListNodes(string mode)
    {
        Dictionary<string, TimeEntry> result = new Dictionary<string, TimeEntry>();
        foreach (KeyNode node in KeyNodes.All)
        {
            string path = NodePath(mode, node.Id);
            if (!File.Exists(path))
            {
                continue;
            }
            DateTime fileTime = File.GetLastWriteTimeUtc(path);
            if (!Cache.TryGetValue(path, out TimeEntry entry) || entry.FileTime != fileTime)
            {
                entry = ReadEntry(path, mode, -1, -1, fileTime);
                if (entry == null)
                {
                    continue;
                }
                Cache[path] = entry;
            }
            result[node.Id] = entry;
        }
        return result;
    }

    internal static AutoGameSave Read(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return (AutoGameSave)new BinaryFormatter().Deserialize(stream);
    }

    internal static List<string> Modes()
    {
        List<string> modes = new List<string>();
        if (Directory.Exists(RouteRoot))
        {
            foreach (string dir in Directory.GetDirectories(RouteRoot))
            {
                string name = System.IO.Path.GetFileName(dir);
                if (name != RoutesDir)
                {
                    modes.Add(name);
                }
            }
        }
        return modes;
    }

    internal static List<TimeEntry> List(string mode)
    {
        List<TimeEntry> result = new List<TimeEntry>();
        string dir = System.IO.Path.Combine(RouteRoot, mode);
        if (!Directory.Exists(dir))
        {
            return result;
        }
        MigrateMonthlyFiles(dir, mode);
        foreach (string path in Directory.GetFiles(dir, "Y*_M*_S*.dat"))
        {
            Match match = FileNamePattern.Match(System.IO.Path.GetFileName(path));
            if (!match.Success)
            {
                continue;
            }
            DateTime fileTime = File.GetLastWriteTimeUtc(path);
            if (!Cache.TryGetValue(path, out TimeEntry entry) || entry.FileTime != fileTime)
            {
                entry = ReadEntry(path, mode, int.Parse(match.Groups[1].Value), int.Parse(match.Groups[2].Value), fileTime);
                if (entry == null)
                {
                    continue;
                }
                Cache[path] = entry;
            }
            result.Add(entry);
        }
        result.Sort((a, b) => a.SortKey.CompareTo(b.SortKey));
        return result;
    }

    // 0.1.0 每月一檔（Y2_M09.dat）→ 依存檔內的旬改名為每旬一檔；新格式已存在就保留新的。
    private static readonly Regex MonthlyFileNamePattern = new Regex(@"^Y(\d+)_M(\d+)\.dat$");

    private static void MigrateMonthlyFiles(string dir, string mode)
    {
        foreach (string path in Directory.GetFiles(dir, "Y*_M*.dat"))
        {
            Match match = MonthlyFileNamePattern.Match(System.IO.Path.GetFileName(path));
            if (!match.Success)
            {
                continue;
            }
            try
            {
                GameSave gameSave = Read(path).GameSave;
                string target = PathFor(mode, gameSave.CurrentYear, gameSave.CurrentMonth, gameSave.CurrentStage);
                if (File.Exists(target))
                {
                    File.Delete(path);
                    if (File.Exists(path + ".meta"))
                    {
                        File.Delete(path + ".meta");
                    }
                    continue;
                }
                File.Move(path, target);
                if (File.Exists(path + ".meta"))
                {
                    File.Move(path + ".meta", target + ".meta");
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"[TimeMachine] 無法轉換舊檔 {path}：{e.Message}");
            }
        }
    }

    private static TimeEntry ReadEntry(string path, string mode, int year, int month, DateTime fileTime)
    {
        try
        {
            GameSave gameSave = Read(path).GameSave;
            string metaPath = path + ".meta";
            return new TimeEntry
            {
                Mode = mode,
                Year = year < 0 ? gameSave.CurrentYear : year,
                Month = month < 0 ? gameSave.CurrentMonth : month,
                Path = path,
                Stage = gameSave.CurrentStage,
                Scene = gameSave.CurrentScene,
                Script = gameSave.StartStoryScript,
                SavedAt = new DateTime(gameSave.TimeTick),
                Source = File.Exists(metaPath) ? File.ReadAllText(metaPath).Trim() : "",
                FileTime = fileTime
            };
        }
        catch (Exception e)
        {
            Plugin.Log.LogWarning($"[TimeMachine] 無法讀取 {path}：{e.Message}");
            return null;
        }
    }
}
