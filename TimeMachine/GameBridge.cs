using System.Reflection;
using HarmonyLib;
using Mortal.Core;

namespace LOM.TimeMachine;

// 透過反射呼叫 SaveSystem 的私有方法，存讀檔流程與遊戲本身完全相同。
internal static class GameBridge
{
    private static readonly MethodInfo CreateSaveDataMethod = AccessTools.Method(typeof(SaveSystem), "CreateSaveData");
    private static readonly MethodInfo ExecuteLoadGameDataMethod = AccessTools.Method(typeof(SaveSystem), "ExecuteLoadGameData");
    private static readonly MethodInfo GetUserFolderMethod = AccessTools.Method(typeof(SaveSystem), "GetUserFolder");
    private static readonly FieldInfo IsDemoField = AccessTools.Field(typeof(SaveSystem), "_isDemo");

    internal const string TitleScene = "Title";

    internal static GameSave CreateSaveData()
    {
        SaveSystem saveSystem = SaveSystem.Instance;
        GameSave gameSave = (GameSave)CreateSaveDataMethod.Invoke(saveSystem, null);
        gameSave.IsDemo = (bool)IsDemoField.GetValue(saveSystem);
        return gameSave;
    }

    // 與遊戲存檔相同的使用者資料夾（Steam 版為 SteamID）
    internal static string UserFolder()
    {
        return (string)GetUserFolderMethod.Invoke(SaveSystem.Instance, null);
    }

    internal static bool CanLoad(out string reason)
    {
        SceneController sceneController = SceneController.Instance;
        if (sceneController == null)
        {
            reason = L.T("遊戲尚未就緒");
            return false;
        }
        if (sceneController.IsPrepare || sceneController.IsLoading)
        {
            reason = L.T("場景載入中，請稍候");
            return false;
        }
        reason = null;
        return true;
    }

    // 同 LoadSlotPanel.OnTitleClick 的讀檔步驟；不呼叫 SetSlot，維持目前使用中的存檔欄位。
    internal static void Load(AutoGameSave save)
    {
        SoundManager.Instance.StopMusic();
        ExecuteLoadGameDataMethod.Invoke(SaveSystem.Instance, new object[] { save.GameSave });
        SaveSystem.Instance.SaveUniverseData();
        MissionManagerData.Instance.UpdateCheckMissions();
        SceneController.Instance.LoadCurrentScene();
    }
}
