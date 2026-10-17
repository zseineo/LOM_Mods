using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.Mono;
using HarmonyLib;
using Mortal.Combat;

namespace LOM.CombatSpeed;

[BepInPlugin(GUID, NAME, VERSION)]
public class Plugin : BaseUnityPlugin
{
    public const string GUID = "zseineo.mortal.combatspeed";
    public const string NAME = "LOM CombatSpeed";
    public const string VERSION = "0.1.0";

    internal static ManualLogSource Log;
    internal static ConfigEntry<float> SpeedMultiplier;

    private void Awake()
    {
        Log = Logger;
        SpeedMultiplier = Config.Bind("General", "SpeedMultiplier", 6f,
            "戰鬥中開啟加速按鈕時的倍率（遊戲原本為 2）");
        Harmony.CreateAndPatchAll(typeof(SpeedPatches), GUID);
        Logger.LogInfo($"{NAME} {VERSION} loaded, speed = x{SpeedMultiplier.Value}");
    }
}

// 遊戲所有加速入口（Awake 初始化、讀取上次設定、按鈕、快捷鍵）都經過 EnableSpeedTime，
// 開關選單後也是還原成它算出的 _currentSpeedTime，所以只要在這裡換掉 _speedTime。
internal static class SpeedPatches
{
    private static readonly AccessTools.FieldRef<CombatManager, float> SpeedTime =
        AccessTools.FieldRefAccess<CombatManager, float>("_speedTime");

    [HarmonyPrefix]
    [HarmonyPatch(typeof(CombatManager), nameof(CombatManager.EnableSpeedTime))]
    private static void EnableSpeedTimePrefix(CombatManager __instance)
    {
        SpeedTime(__instance) = Plugin.SpeedMultiplier.Value;
    }
}
