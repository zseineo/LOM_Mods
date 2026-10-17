#!/usr/bin/env bash
# 遊戲更新後重新抽取分析資料到 data/（舊資料先改名為 data_old_<時間>）。
# 抽完再跑 rebuild_guide.sh 重建流程圖網頁。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
GAME="/c/Program Files (x86)/Steam/steamapps/common/LegendOfMortal"
NEW="$ROOT/data_new"
TMP="$ROOT/data_tmp"
rm -rf "$NEW" "$TMP"
mkdir -p "$NEW" "$TMP"

echo "== 劇本（Lua）"
python -I "$ROOT/tools/extract_lua.py" "$GAME/Mortal_Data" "$TMP/lua_all" | head -3
STORY="$(find "$TMP/lua_all" -type d -ipath "*story/chinesetraditional" | head -1)"
mkdir -p "$NEW/lua_tc"
for f in "$STORY"/*.txt; do
  name="$(basename "$f")"
  cp "$f" "$NEW/lua_tc/${name,,}"
done
echo "lua_tc: $(ls "$NEW/lua_tc" | wc -l) 個"

echo "== 在地化文字（繁中）"
python -I "$ROOT/tools/extract_loc.py" "$GAME" "$NEW/loc_tc" "${1:-ChineseTraditional}"
echo "loc_tc: $(ls "$NEW/loc_tc" | wc -l) 個"

echo "== 遊戲設定物件"
python -I "$ROOT/tools/dump_so.py" "$GAME" "$NEW/so2.json" \
  "GameStat,FlagData,GameTimeData,RelationshipStat,PlayerTalentData,Book,Misc,SpecialItem,LibraryItemData,MissionData,MissionCheckData,MissionManagerData,SubMissionsData,StatGroupVariable,ConditionResultData,UpgradeItemData,ConditionResultConfig,DiceResultData,DiceResultConfig,PositionResultData,PositionResultConfig,SwitchResultData,SwitchResultConfig,PositionEventData,StoryMappingItem" | grep -v "^top classes"
python -I "$ROOT/tools/dump_so.py" "$GAME" "$NEW/battle_dump.json" "BattleLevel,CombatLevel" | grep -v "^top classes"

echo "== 反編譯（列舉型別等）"
for dll in Mortal.Battle Mortal.Combat Mortal.Core Mortal.Free Mortal.Story; do
  ilspycmd -p -o "$NEW/decomp/$dll" "$GAME/Mortal_Data/Managed/$dll.dll" > /dev/null
done

rm -rf "$TMP"
if [ -d "$ROOT/data" ]; then mv "$ROOT/data" "$ROOT/data_old_$(date +%Y%m%d_%H%M)"; fi
mv "$NEW" "$ROOT/data"
echo "完成：$ROOT/data"
