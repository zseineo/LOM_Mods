using System.IO;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using HarmonyLib;
using UnityEngine;
using UnityEngine.InputSystem;

namespace LOM.TimeMachine;

[BepInPlugin(GUID, NAME, VERSION)]
public class Plugin : BaseUnityPlugin
{
    public const string GUID = "zseineo.mortal.timemachine";
    public const string NAME = "LOM TimeMachine";
    public const string VERSION = "0.7.8";

    internal static ManualLogSource Log;
    internal static ConfigEntry<bool> AutoCapture;
    internal static ConfigEntry<bool> QuickLoad;
    internal static ConfigEntry<Key> ToggleKey;
    internal static ConfigEntry<bool> GuideEnabled;
    internal static ConfigEntry<int> GuidePort;
    internal static ConfigEntry<Key> GuideKey;
    internal static ConfigEntry<bool> EventLogEnabled;

    private TimeMachineWindow _window;
    private GuideServer _guide;

    private void Awake()
    {
        Log = Logger;
        AutoCapture = Config.Bind("General", "AutoCapture", true,
            "每一旬第一個可合法存檔的時間點，自動存一份時光機存檔（不占存檔欄位）。時光機視窗的「暫停自動存檔」就是把這項關掉");
        QuickLoad = Config.Bind("General", "QuickLoad", false, "快速讀取：雙擊時間點直接讀取，按「讀取」也不再確認（時光機視窗上可直接勾選）");
        ToggleKey = Config.Bind("General", "ToggleKey", Key.F6, "開關時光機視窗的按鍵（也可以在時光機視窗上方直接改）");
        GuideEnabled = Config.Bind("Guide", "Enabled", true, "啟用「五塊錢」網頁（本機瀏覽器開啟：流程圖、結緣條件、地點事件、未讀場景，可看即時旗標並讀取時光機存檔）");
        GuidePort = Config.Bind("Guide", "Port", 8642, "「五塊錢」網頁使用的本機連接埠");
        GuideKey = Config.Bind("Guide", "OpenKey", Key.F7, "用瀏覽器開啟「五塊錢」網頁的按鍵（也可以在時光機視窗上方直接改）");
        EventLogEnabled = Config.Bind("General", "EventLog", true, "事件紀錄：劇情腳本、任務啟動、旗標變化、分歧判斷結果、擲骰寫到 TimeMachine/<SteamID>/event_log.txt");
        _window = new TimeMachineWindow();
        Harmony.CreateAndPatchAll(typeof(CapturePatches), GUID);
        Harmony.CreateAndPatchAll(typeof(EventLogPatches), GUID + ".eventlog");
        Cheats.Bind(Config);
        Harmony.CreateAndPatchAll(typeof(Cheats), GUID + ".cheats");
        if (GuideEnabled.Value)
        {
            string pageDir = Path.Combine(Path.GetDirectoryName(Info.Location), "guide");
            _guide = new GuideServer(GuidePort.Value, pageDir);
            _guide.Start();
        }
        Logger.LogInfo($"{NAME} {VERSION} loaded, toggle key = {ToggleKey.Value}, guide key = {GuideKey.Value}");
    }

    private void Update()
    {
        Keyboard keyboard = Keyboard.current;
        bool capturing = _window.CapturingKey;
        if (!capturing && keyboard != null && keyboard[ToggleKey.Value].wasPressedThisFrame)
        {
            _window.Toggle();
        }
        if (!capturing && _guide != null && keyboard != null && keyboard[GuideKey.Value].wasPressedThisFrame)
        {
            Application.OpenURL(_guide.Url);
        }
        _window.Update();
        _guide?.Tick();
    }

    private void OnGUI()
    {
        _window.OnGUI();
    }

    private void OnDestroy()
    {
        _guide?.Stop();
    }
}
