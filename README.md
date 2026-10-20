# 活俠傳（Legend of Mortal）Mod

三個 BepInEx Mod，各自獨立，可以只裝需要的。目前是**測試版**。

| Mod | 功能 |
|---|---|
| **時光機**（LOM_TimeMachine） | 每一旬自動存一份檔，按 F6 隨時讀回過去；F7 開「算命仙」攻略網頁 |
| **戰鬥加速**（LOM_CombatSpeed） | 戰鬥中的加速按鈕從 x2 改成 x6（可調） |
| **對話調整**（LOM_DialogTweaks） | 滾輪往下＝下一句；F8 自動跳過已讀劇情 |

## 安裝

1. **先裝 BepInEx 6**（只要裝一次）
   下載 [BepInEx-Unity.Mono-win-x64-6.0.0-be.692](https://builds.bepinex.dev/projects/bepinex_be/692/BepInEx-Unity.Mono-win-x64-6.0.0-be.692%2B851521c.zip)，
   解壓縮到遊戲資料夾（有 `Mortal.exe` 的那層），開一次遊戲再關掉。
   遊戲是 64 位元，請用 **win-x64** 版；x86 版會完全沒反應。
2. 到 [Releases](https://github.com/zseineo/LOM_Mods/releases) 下載要的 Mod 壓縮檔，同樣**解壓縮到遊戲資料夾**，檔案會自動放進 `BepInEx\plugins\`。
3. 開遊戲。設定檔在第一次開遊戲後產生於 `BepInEx\config\`。

遊戲資料夾：Steam 收藏庫對活俠傳按右鍵 ▸ 管理 ▸ 瀏覽本機檔案。

**移除**：刪掉 `BepInEx\plugins\` 裡對應的 `LOM_xxx` 資料夾。

## 時光機

- **自動存檔**：每一旬第一個能存檔的時間點自動存一份。存在 `%LocalLow%\Obb Studio\Mortal\TimeMachine\`，不佔遊戲存檔欄位，也不會被 Steam 雲端同步。
  同一旬會覆蓋成最新的；讀回過去時，比現在晚的存檔不會被刪掉。
- **F6 時光機視窗**：點時間點讀檔。另外有「關鍵節點」（葉家兄妹、留學、招親、武林大會等劇情觸發前）和「路線」（從目前時間分岔出另一條存檔線，互不覆蓋）。
- **F7 算命仙網頁**：用瀏覽器開本機網頁（只有自己的電腦連得到），連上遊戲時即時顯示目前狀態：
  - 流程圖：各事件的觸發時間、條件、分支
  - 結緣條件、其他條件：每一步要做什麼，目前有沒有達成（✓／✗）
  - 地點事件：現在點各地點會抽到什麼、機率多少
  - 五塊錢：還沒看過的劇情、怎麼看到
  - 作弊：顯示全部決策選項、調整好感與結識
- 內容是從劇本推出來的，可能不準。
- 快捷鍵可以在 F6 視窗上方直接改。

## 戰鬥加速

設定 `BepInEx\config\zseineo.mortal.combatspeed.cfg`：

- `SpeedMultiplier`：開啟加速按鈕時的倍率，預設 6（遊戲原本 2）

## 對話調整

設定 `BepInEx\config\zseineo.mortal.dialogtweaks.cfg`：

- `WheelNext`：劇情中滾輪往下＝下一句（預設開）
- `AutoSkip.ToggleKey`：開關「自動跳過已讀」的按鍵（預設 F8）。遇到未讀、選項、擲骰會自動停下
- `AutoSkip.ShowIndicator`：開啟時在畫面左上角顯示提示

## 回報問題

請附上 `BepInEx\LogOutput.log`（遊戲當掉或 Mod 沒反應時最有用），並寫明 Mod 版本與怎麼重現。
