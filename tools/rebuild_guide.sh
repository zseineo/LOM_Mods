#!/usr/bin/env bash
# 重建流程圖網頁並安裝到遊戲的時光機 Mod 資料夾。
# 遊戲更新後先跑 refresh_data.sh 重新抽資料到 data/。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/data"
GAME="/c/Program Files (x86)/Steam/steamapps/common/LegendOfMortal"
UNIVERSE="$(ls "$USERPROFILE"/AppData/LocalLow/Obb\ Studio/Mortal/*/Save_universe.json | head -1)"
python -I "$ROOT/tools/build_graph.py" "$DATA/so2.json" "$DATA/lua_tc" "$DATA/loc_tc" "$DATA/decomp" "$UNIVERSE" "$DATA/graph.json" "$DATA/battle_dump.json"
python -I "$ROOT/tools/render_preview.py" "$DATA/graph.json" "$ROOT/tools/flowchart_template.html" "$ROOT/preview/flowchart_preview.html" "$ROOT/tools/guides.json"
mkdir -p "$GAME/BepInEx/plugins/LOM_TimeMachine/guide"
cp "$ROOT/preview/flowchart_preview.html" "$GAME/BepInEx/plugins/LOM_TimeMachine/guide/index.html"
echo "已安裝：$GAME/BepInEx/plugins/LOM_TimeMachine/guide/index.html"
