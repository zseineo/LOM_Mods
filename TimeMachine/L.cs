using System;
using System.Collections.Generic;
using System.IO;

namespace LOM.TimeMachine;

// 多語言：key 是繁中原文。strings.tsv（tools/i18n.py 從 i18n/strings.json 產生）有這個語言的字就換掉，沒有就用原文。
// 格式：第一行 key<TAB>zh-TW<TAB>ja<TAB>ko，之後一行一個字串；\t \n \\ 跳脫。
internal static class L
{
    private static readonly Dictionary<string, string> Map = new Dictionary<string, string>();

    internal static void Load(string file, string lang)
    {
        Map.Clear();
        if (!File.Exists(file))
        {
            return;
        }
        try
        {
            string[] lines = File.ReadAllLines(file);
            string[] header = lines[0].Split('\t');
            int col = Array.IndexOf(header, lang), zh = Array.IndexOf(header, "zh-TW");
            for (int i = 1; i < lines.Length; i++)
            {
                string[] cells = lines[i].Split('\t');
                string text = Cell(cells, col);
                if (text.Length == 0)
                {
                    text = Cell(cells, zh);
                }
                if (text.Length > 0)
                {
                    Map[Unescape(cells[0])] = Unescape(text);
                }
            }
        }
        catch (Exception e)
        {
            Plugin.Log.LogWarning($"[TimeMachine] 無法讀取多語言檔 {file}：{e.Message}");
        }
    }

    internal static string T(string key, params object[] args)
    {
        string text = Map.TryGetValue(key, out string found) ? found : key;
        return args.Length > 0 ? string.Format(text, args) : text;
    }

    private static string Cell(string[] cells, int index)
    {
        return index > 0 && index < cells.Length ? cells[index] : "";
    }

    private static string Unescape(string s)
    {
        if (s.IndexOf('\\') < 0)
        {
            return s;
        }
        System.Text.StringBuilder sb = new System.Text.StringBuilder(s.Length);
        for (int i = 0; i < s.Length; i++)
        {
            if (s[i] == '\\' && i + 1 < s.Length)
            {
                char c = s[++i];
                sb.Append(c == 't' ? '\t' : c == 'n' ? '\n' : c);
            }
            else
            {
                sb.Append(s[i]);
            }
        }
        return sb.ToString();
    }
}
