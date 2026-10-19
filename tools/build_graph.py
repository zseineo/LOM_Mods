"""從抽出的遊戲資料建立劇情流程圖 JSON。

用法：python -I build_graph.py <so2.json> <lua_dir> <loc_dir> <decomp_dir> <universe.json|-> <out.json>
"""
import collections
import json
import os
import re
import sys

so_path, lua_dir, loc_dir, decomp_dir, universe_path, out_path = sys.argv[1:7]
battle_path = sys.argv[7] if len(sys.argv) > 7 else None

so = json.load(open(so_path, encoding="utf-8"))

# 戰鬥關卡：決鬥 ChangeScene("Combat", key) → CL_key，戰役 ChangeScene("Battle", key) → BL_key。
# 決鬥的勝敗寫在關卡自己的旗標設定；戰役固定寫 BattleResult_001（勝=1）。
BATTLE_RESULT_FLAGS = {"BattleResult_001": {"win": {1}, "lose": {0}}, "BattleResult_002": {"win": {1}, "lose": {0}}}
level_flags = {}
level_info = {}
if battle_path and os.path.exists(battle_path):
    battle_dump = json.load(open(battle_path, encoding="utf-8"))
    for level in battle_dump.get("CombatLevel", []):
        flags = {}
        for side, key in (("win", "_winResult"), ("lose", "_loseResult")):
            for r in level.get(key) or []:
                if r.get("_flag"):
                    name = r["_flag"].split("@")[0].split(":", 1)[1]
                    flags.setdefault(name, {"win": set(), "lose": set()})[side].add(r["_state"])
        level_flags[level["m_Name"]] = flags
        enemy = (level.get("_enemyStat") or "").split("@")[0].split(":", 1)[-1]
        m = re.match(r"^Enemy_(.+?)(?:_\d+)?$", enemy)
        dead_lib = (level.get("_deadLibrary") or "").split("@")[0].split(":", 1)[-1] if level.get("_deadEnd") else ""
        level_info[level["m_Name"]] = {"enemy": m.group(1) if m else enemy, "desc": level.get("_desc", ""), "dead": bool(level.get("_deadEnd")), "deadLib": dead_lib}
    for level in battle_dump.get("BattleLevel", []):
        level_flags[level["m_Name"]] = BATTLE_RESULT_FLAGS
        level_info[level["m_Name"]] = {"enemy": level.get("_enemyNote") or "", "desc": "", "dead": False}


battle_flag_values = {}
for flags in level_flags.values():
    for f, sides in flags.items():
        agg = battle_flag_values.setdefault(f, {"win": set(), "lose": set()})
        agg["win"] |= sides["win"]
        agg["lose"] |= sides["lose"]
battle_flag_values = {f: {"win": sorted(v["win"]), "lose": sorted(v["lose"])} for f, v in battle_flag_values.items()
                      if not v["win"] & v["lose"]}


def level_name(mode, key):
    return ("CL_" if mode == "Combat" else "BL_") + key

# ---------- 在地化 ----------
loc = {}
for name in os.listdir(loc_dir):
    with open(os.path.join(loc_dir, name), encoding="utf-8", errors="replace") as fp:
        for line in fp:
            line = line.lstrip("﻿").rstrip("\r\n")
            if " = " in line and not line.startswith("//"):
                k, v = line.split(" = ", 1)
                loc[k.strip()] = v.replace("\\n", "\n").strip()


def story_text(key):
    return loc.get("Story/" + key)


# ---------- 列舉 ----------
def parse_enum(enum_name):
    for root, _, files in os.walk(decomp_dir):
        for f in files:
            if not f.endswith(".cs"):
                continue
            text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            m = re.search(r"enum\s+" + enum_name + r"\s*\{(.*?)\}", text, re.S)
            if not m:
                continue
            result, value = {}, -1
            for raw in m.group(1).splitlines():
                raw = re.sub(r"\[.*?\]", "", raw).strip().rstrip(",")
                if not raw:
                    continue
                mm = re.match(r"^([^\s=]+)\s*(?:=\s*(-?\d+))?$", raw)
                if not mm:
                    continue
                value = int(mm.group(2)) if mm.group(2) is not None else value + 1
                result[value] = mm.group(1)
            return result
    return {}


def parse_enum_strings(enum_name):
    """列舉名稱 → [StringValue(...)]（存檔裡用的鍵名）。"""
    for root, _, files in os.walk(decomp_dir):
        for f in files:
            if not f.endswith(".cs"):
                continue
            text = open(os.path.join(root, f), encoding="utf-8", errors="replace").read()
            m = re.search(r"enum\s+" + enum_name + r"\s*\{(.*?)\}", text, re.S)
            if m:
                return dict((name, key) for key, name in re.findall(r'\[StringValue\("([^"]*)"\)\]\s*([^\s=,\[]+)', m.group(1)))
    return {}


STAT = parse_enum("GameStatType")
REL = parse_enum("RelationshipStatType")
POS = parse_enum("PositionType")
OPS = ["=", "≠", "<", "≤", ">", "≥"]

# ---------- 物件索引 ----------
objs = {}
by_name = collections.defaultdict(dict)
for cls, lst in so.items():
    if not isinstance(lst, list):
        continue
    for o in lst:
        objs[f"{o['__file']}:{o['__pid']}"] = (cls, o)
        by_name[cls][o["m_Name"]] = o


def deref(ref):
    if not ref or "@" not in ref:
        return None
    hit = objs.get(ref.rsplit("@", 1)[1])
    return hit[1] if hit else None


def ref_name(ref):
    return ref.split("@")[0].split(":", 1)[1] if ref else "?"


def item_name(kind, ref):
    o = deref(ref)
    ident = o.get("_id") if o else None
    if ident:
        return loc.get(f"{kind}/Name/{ident}", ident)
    return ref_name(ref)


def flag_label(name):
    alias = loc.get(f"Flag/Name/{name}")
    return f"旗標 {name}" + (f"（{alias}）" if alias else "")


def value_text(v):
    ct = v["_checkType"]
    neg = "-" if v.get("_negative") else ""
    if ct == 0:
        return neg + str(v["_constant"])
    if ct == 1:
        o = deref(v["_stat"])
        if o:
            return neg + STAT.get(o["_type"], ref_name(v["_stat"]))
        name = ref_name(v["_stat"])
        # 找不到物件時用名稱對應在地化（Player_Training → PlayerStat/training → 修養）
        if name.startswith("Player_"):
            return neg + loc.get("PlayerStat/" + name[7:].lower(), name)
        return neg + name
    if ct == 2:
        o = deref(v["_relationship"])
        return neg + "好感·" + (REL.get(o["_type"], ref_name(v["_relationship"])) if o else ref_name(v["_relationship"]))
    if ct == 3:
        return neg + flag_label(ref_name(v["_flag"]))
    if ct == 4:
        return "持有·" + item_name("Book", v["_book"])
    if ct == 5:
        return "持有·" + item_name("Misc", v["_misc"])
    if ct == 6:
        return "持有·" + item_name("Special", v["_specialItem"])
    if ct == 7:
        return f"隨機({v['_randomMin']}~{v['_randomMax']})"
    if ct == 8:
        return "(" + group_text(v["_statGroup"]) + ")"
    if ct == 9:
        o = deref(v["_gameTime"])
        if not o or o["m_Name"] == "PlayerGameTime":
            return "目前時間"
        if not o["m_Name"].startswith("第"):
            return f"任務時間〔{o['m_Name']}〕"
        t = o["GameTime"]
        return f"第{t['Year']}年{t['Month']}月{['', '上旬', '中旬', '下旬'][t['Stage']]}"
    if ct == 10:
        return "天賦·" + ref_name(v["_talentData"])
    if ct == 11:
        return "秘笈等級·" + item_name("Book", v["_book"])
    if ct == 12:
        return "已開發·" + ref_name(v["_upgradeItemData"])
    if ct == 13:
        return "開發等級·" + ref_name(v["_upgradeItemData"])
    if ct == 14:
        return "精通書籍數"
    if ct == 15:
        return "風雲史·" + ref_name(v["_libraryAchieve"])
    if ct == 16:
        return "條件·" + ref_name(v["_condition"])
    return f"?{ct}"


def group_text(ref):
    o = deref(ref)
    if not o:
        return ref_name(ref)
    vals = [value_text(x) for x in o.get("_value", [])]
    gt = o.get("_groupType", 1)
    if len(vals) == 1:
        return vals[0]
    if gt == 2:
        return "max(" + ", ".join(vals) + ")"
    if gt == 3:
        return "min(" + ", ".join(vals) + ")"
    if gt == 4:
        return " × ".join(vals)
    return " + ".join(vals)


def cond_item_text(ci):
    parts = [f"{group_text(i['_value1'])} {OPS[i['_compareOp']]} {group_text(i['_value2'])}" for i in ci.get("_items", [])]
    return (" 且 " if ci.get("_logicOp", 0) == 0 else " 或 ").join(parts) or "（無條件）"


def switch_conditions(name):
    o = by_name["SwitchResultData"].get(name)
    if not o:
        return None
    if o.get("_useCount"):
        what = (o.get("_devNote") or "").strip() or "經過這裡的次數"
        return [f"{what} {OPS[c['_compareOp']]} {c['_value']}" for c in o.get("_countItems", [])] + [f"{what}是其他次數"]
    items = [cond_item_text(ci) for ci in o.get("_items", [])]
    # 「以上皆非」補上它排除了哪些條件，讀的人才知道實際要滿足什麼
    others = "；".join(items)
    return items + [f"以上皆非（不是：{others}）" if items else "以上皆非"]


def group_flags(ref, out):
    o = deref(ref)
    for v in (o or {}).get("_value", []):
        if v["_checkType"] == 3 and v.get("_flag"):
            out.append(("flag", ref_name(v["_flag"])))
        elif v["_checkType"] == 0:
            out.append(("const", v["_constant"]))
    return out


def switch_battle_outcomes(name, battle_flags):
    """Switch 若是在判斷戰鬥結果旗標，回傳每個結果對應勝/敗（None 表示看不出來）。"""
    o = by_name["SwitchResultData"].get(name)
    if not o or o.get("_useCount"):
        return None
    sides, found = [], False
    for ci in o.get("_items", []):
        side = None
        for it in ci.get("_items", []):
            a, b = group_flags(it["_value1"], []), group_flags(it["_value2"], [])
            flags = [x[1] for x in a + b if x[0] == "flag" and x[1] in battle_flags]
            consts = [x[1] for x in a + b if x[0] == "const"]
            if flags and consts and it["_compareOp"] == 0:
                found = True
                info = battle_flags[flags[0]]
                side = "win" if consts[0] in info["win"] else "lose" if consts[0] in info["lose"] else None
        sides.append(side)
    if not found:
        return None
    sides.append("lose" if "win" in sides and "lose" not in sides else "win" if "lose" in sides and "win" not in sides else None)
    return sides


def condition_text(name):
    o = by_name["ConditionResultData"].get(name)
    if not o:
        return name
    return " 或 ".join(f"（{cond_item_text(ci)}）" for ci in o.get("_items", [])) or name


# ---------- Lua 解析 ----------
RE = {
    "choose": re.compile(r"^local (\w+) = choose\((\w+)\)"),
    "table_reset": re.compile(r"^local (\w+) = \{\}"),
    "table_entry": re.compile(r"^(\w+)\[(\d+)\] = (.*)$"),
    "switch": re.compile(r'^local (\w+) = checkpointmanager\.Switch\("([^"]+)"\)'),
    "cond": re.compile(r'^local (\w+) = checkpointmanager\.Condition\("([^"]+)"\)'),
    "dice": re.compile(r'^local (\w+) = checkpointmanager\.Dice\("([^"]+)"'),
    "dice_sel": re.compile(r"^local (\w+) = dicemenudialog\.ResultSelection"),
    "position": re.compile(r'^(?:local )?(\w+) = checkpointmanager\.Position\("([^"]+)"\)'),
    "if": re.compile(r"^if (.+) then$"),
    "elseif": re.compile(r"^elseif (.+) then$"),
    "next": re.compile(r'luamanager\.SetNextScript\(("?)([^")]+)\1\)'),
    "scene": re.compile(r'luamanager\.ChangeScene\("([^"]*)", "([^"]*)", "([^"]*)"\)'),
    "mission": re.compile(r'statmodifymanager\.Mission\("([^"]+)", "([^"]*)"\)'),
    "setflag": re.compile(r'statmodifymanager\.(SetFlag|AddFlag)\("([^"]+)", (-?\d+)\)'),
    "story": re.compile(r'statmodifymanager\.AddStory\("([^"]+)"\)'),
    "text": re.compile(r'GetStoryText\("([^"]+)"\)'),
    "time": re.compile(r"luamanager\.SetGameTime\((\d+), (\d+), (\d+)\)"),
    "ending": re.compile(r'endgamepanel\.Open\("(\d+)"'),
    "cg": re.compile(r'cgpanel\.Open\("(\d+)"'),
    "lover": re.compile(r'statmodifymanager\.SetPlayer\("lover", (\d+)\)'),
    "travel": re.compile(r'luamanager\.(?:SetCurrentTravelScript\(|SetTempScript\(\d+, )"([^"]+)"\)'),
    "curscript": re.compile(r'luamanager\.SetCurrentStoryScript\("([^"]+)"\)'),
    "save": re.compile(r"luamanager\.(ToggleSaveButton\(1\)|AutoSave\(\))"),
    "char": re.compile(r'characters\.Get\("([^"]+)"\)'),
}


def option_label(raw):
    raw = raw.strip()
    m = re.match(r'^(\w+) and "(.*)" or "~[^"]*"$', raw)
    cond_var = None
    if m:
        cond_var, raw = m.group(1), m.group(2)
    elif raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    else:
        return None, None, cond_var
    if "|" in raw:
        key, rule = raw.split("|", 1)
        return key, f"{story_text(key) or key}（{rule}）", cond_var
    if "+" in raw:
        parts = raw.split("+")
        key = parts[1] if len(parts) > 1 else raw
        return key, story_text(key) or loc.get(f"Position/Talk/{key}") or loc.get(f"Position/title/{parts[0]}") or "+".join(parts[:2]), cond_var
    return raw, story_text(raw) or raw, cond_var


def parse_script(text):
    root = []
    stack = [("block", root)]
    tables = {}
    vars_ = {}
    last_dice = None

    def cur():
        return stack[-1][1]

    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        m = RE["if"].match(s)
        if m:
            node = {"t": "if", "branches": [{"cond": m.group(1), "block": []}]}
            # 同名變數可能在後面的區塊重新 choose（選單內容不同）：記下當下的選單
            var = re.sub(r"^not ", "", re.match(r"^(not )?(\w+)", m.group(1)).group(0))
            if var in vars_:
                node["var"] = vars_[var]
            cur().append(node)
            stack.append(("if", node))
            stack.append(("block", node["branches"][-1]["block"]))
            continue
        m = RE["elseif"].match(s)
        if m or s == "else":
            stack.pop()
            node = stack[-1][1]
            node["branches"].append({"cond": m.group(1) if m else "else", "block": []})
            stack.append(("block", node["branches"][-1]["block"]))
            continue
        if s == "end":
            stack.pop()
            stack.pop()
            continue
        m = RE["table_reset"].match(s)
        if m:
            tables[m.group(1)] = []
            continue
        m = RE["table_entry"].match(s)
        if m and m.group(1) in tables:
            key, label, cvar = option_label(m.group(3))
            if label is not None:
                tables[m.group(1)].append({"i": int(m.group(2)), "key": key, "label": label,
                                           "cond": vars_.get(cvar, {}).get("name") if cvar else None})
            continue
        m = RE["choose"].match(s)
        if m:
            vars_[m.group(1)] = {"kind": "choice", "opts": list(tables.get(m.group(2), []))}
            continue
        m = RE["switch"].match(s)
        if m:
            vars_[m.group(1)] = {"kind": "switch", "name": m.group(2)}
            continue
        m = RE["cond"].match(s)
        if m:
            vars_[m.group(1)] = {"kind": "cond", "name": m.group(2)}
            continue
        m = RE["dice"].match(s)
        if m:
            last_dice = m.group(2)
            continue
        m = RE["dice_sel"].match(s)
        if m:
            dice_tables = [t for t in tables.values() if t and "（" in t[0]["label"]]
            vars_[m.group(1)] = {"kind": "dice", "name": last_dice, "opts": list(dice_tables[-1]) if dice_tables else []}
            continue
        m = RE["position"].match(s)
        if m:
            vars_[m.group(1)] = {"kind": "position", "name": m.group(2)}
        stmt = []
        for k in ("next", "curscript", "travel", "lover", "scene", "mission", "setflag", "story", "text", "time", "ending", "cg", "save", "char"):
            for mm in RE[k].finditer(s):
                stmt.append((k, mm.groups()))
        for k, g in stmt:
            if k == "travel":
                # 外出節點：先記下下一站，再由中繼腳本以 GetCurrentTravelScript/GetTempScript 動態接過去
                cur().append({"t": "next", "s": g[0], "via": "travel"})
            elif k == "lover":
                cur().append({"t": "lover", "v": int(g[0])})
            elif k == "curscript":
                # 戰鬥前指定戰後接續的腳本（也用於直接切回劇情場景）
                cur().append({"t": "next", "s": g[0], "via": "after"})
            elif k == "scene" and g[0] in ("Battle", "Combat"):
                cur().append({"t": "battle", "mode": g[0], "key": g[1]})
            elif k == "next":
                target = g[1]
                if g[0] == '"':
                    cur().append({"t": "next", "s": target})
                else:
                    v = vars_.get(target, {})
                    cur().append({"t": "next_var", "v": v.get("name", target), "kind": v.get("kind")})
            elif k == "scene":
                cur().append({"t": "scene", "s": g[0], "key": g[1]})
            elif k == "mission":
                cur().append({"t": "mission", "m": g[0], "k": g[1]})
            elif k == "setflag":
                cur().append({"t": "flag", "op": g[0], "f": g[1], "v": int(g[2])})
            elif k == "story":
                cur().append({"t": "story", "k": g[0]})
            elif k == "text":
                cur().append({"t": "text", "k": g[0]})
            elif k == "time":
                cur().append({"t": "time", "y": int(g[0]), "m": int(g[1]), "st": int(g[2])})
            elif k == "ending":
                cur().append({"t": "ending", "id": g[0]})
            elif k == "cg":
                cur().append({"t": "cg", "id": g[0]})
            elif k == "save":
                cur().append({"t": "save"})
            elif k == "char" and g[0] != "player":
                cur().append({"t": "char", "c": g[0]})
    return root, vars_


def resolve_if(node, vars_):
    """標註 if 的種類與每個分支的標籤。"""
    first = node["branches"][0]["cond"]
    m = re.match(r"^(\w+) == (\d+)$", first)
    var = m.group(1) if m else re.sub(r"^not ", "", first)
    info = node.get("var") or vars_.get(var, {})
    kind = info.get("kind", "other")
    labels = []
    sw = switch_conditions(info["name"]) if kind == "switch" else None
    incoming = battles_into.get(CURRENT[0], [])
    allowed = {}
    for b in incoming:
        allowed.update(level_flags.get(level_name(b["mode"], b["key"]), {}))
    outcome = switch_battle_outcomes(info["name"], allowed) if kind == "switch" and allowed else None
    if outcome:
        kind = "battle"
        labels = []
        for br in node["branches"]:
            mm = re.match(r"^(\w+) == (\d+)$", br["cond"])
            idx = int(mm.group(2)) if mm else None
            side = outcome[idx - 1] if idx and 0 < idx <= len(outcome) else None
            text = sw[idx - 1] if sw and idx and 0 < idx <= len(sw) else ("其他" if br["cond"] == "else" else br["cond"])
            prefix = {"win": "勝利", "lose": "落敗"}.get(side, "")
            labels.append((f"{prefix}：{text}" if prefix else text, None))
        return kind, info.get("name"), labels, incoming
    for br in node["branches"]:
        c = br["cond"]
        mm = re.match(r"^(\w+) == (\d+)$", c)
        idx = int(mm.group(2)) if mm else None
        label, key = c, None
        if kind in ("choice", "dice") and idx is not None:
            opt = next((o for o in info.get("opts", []) if o["i"] == idx), None)
            if opt:
                label, key = opt["label"], opt["key"]
                if opt.get("cond"):
                    label += f"　〔需：{condition_text(opt['cond'])}〕"
        elif kind == "switch" and sw and idx is not None:
            label = sw[idx - 1] if 0 < idx <= len(sw) else f"結果 {idx}"
            # Switch 是「第一個成立的條件」：第 2 個以後的分支隱含「前面的都不成立」
            if 1 < idx < len(sw):
                prev = "；".join(sw[:idx - 1])
                label = f"{label}　〔前提不是：{prev}〕"
        elif kind == "cond":
            label = ("不符合：" if c.startswith("not ") else "符合：") + condition_text(info["name"])
        elif c == "else":
            label = "其他"
        labels.append((label, key))
    return kind, info.get("name"), labels, None


# ---------- 讀取全部腳本 ----------
scripts = {}
script_views = {}
script_first_say = {}
script_cond_names = {}
script_chars = {}
CHAR_GET = re.compile(r'characters\.Get\("([^"]+)"\)')
VIEW_NAME = re.compile(r'LoadView\("([^"]*)"\)')
# 任務時間：劇本用 SetMissionTime(名稱, 年, 月, 旬) 記下「現在＋多久」，條件「目前時間 = 任務時間〔名稱〕」就是到了那時
MISSION_TIME = re.compile(r'SetMissionTime\("([^"]+)", (\d+), (\d+), (\d+)\)')
mission_time_set = collections.defaultdict(list)
COND_NAME = re.compile(r'checkpointmanager\.(?:Switch|Condition)\("([^"]+)"\)')
for name in os.listdir(lua_dir):
    if name.endswith(".txt"):
        text = open(os.path.join(lua_dir, name), encoding="utf-8", errors="replace").read()
        key = name[:-4].lower()
        scripts[key] = parse_script(text)
        script_views[key] = collections.Counter(v for v in VIEW_NAME.findall(text) if v not in ("black", "white", "sky"))
        say = RE["text"].search(text)
        script_first_say[key] = say.group(1) if say else None
        script_cond_names[key] = set(COND_NAME.findall(text))
        for m in MISSION_TIME.finditer(text):
            mission_time_set[m.group(1)].append((key, [int(m.group(2)), int(m.group(3)), int(m.group(4))]))
        script_chars[key] = {c for c in CHAR_GET.findall(text) if c != "player"}

read_keys = set()
if universe_path != "-" and os.path.exists(universe_path):
    read_keys = set(json.load(open(universe_path, encoding="utf-8")).get("ReadStoryData", []))


def collect(block, acc):
    for it in block:
        t = it["t"]
        if t == "if":
            for br in it["branches"]:
                collect(br["block"], acc)
        else:
            acc[t].append(it)
    return acc


def outcome_sig(block):
    acc = collect(block, collections.defaultdict(list))
    return (
        tuple(sorted({x["s"] for x in acc["next"]})),
        tuple(sorted({(x["m"], x["k"]) for x in acc["mission"]})),
        tuple(sorted({x["s"] for x in acc["scene"]})),
        tuple(sorted(x["id"] for x in acc["ending"] + acc["cg"])),
        tuple(sorted({x["v"] for x in acc["lover"]})),
        tuple(sorted({x["v"] for x in acc["next_var"]})),
    )


def read_ratio(keys):
    keys = list(dict.fromkeys(keys))
    if not keys:
        return None
    return round(sum(1 for k in keys if k in read_keys) / len(keys), 3)


def legend(keys):
    out = []
    for k in dict.fromkeys(keys):
        t = loc.get("LegendInfo/" + k)
        if t:
            out.append(t.strip())
    return out


NEED_NAME = re.compile(r"　〔需：([A-Za-z0-9_]+)〕$")


def never_shown(label):
    m = NEED_NAME.search(label)
    return bool(m) and m.group(1) not in by_name["ConditionResultData"]


def summarize(block, vars_, depth=0):
    """把區塊壓成 UI 用的樹：選項一定保留；條件/擲骰分支只在走向不同時保留。"""
    items = []
    texts, stories = [], []
    for it in block:
        t = it["t"]
        if t == "text":
            texts.append(it["k"])
        elif t == "story":
            stories.append(it["k"])
        elif t == "if":
            kind, name, labels, battles = resolve_if(it, vars_)
            sigs = {outcome_sig(br["block"]) for br in it["branches"]}
            significant = kind in ("choice", "battle") or (len(sigs) > 1 and kind != "position")
            if kind == "dice" and len(sigs) == 1:
                significant = False
            # 選項條件在遊戲資料裡不存在（「XXX」「Meeting_Option_703_02_XXX」）：遊戲判定不成立，選項不會出現
            pairs = [(br, lk) for br, lk in zip(it["branches"], labels) if not never_shown(lk[0])]
            if significant and depth < 12:
                branches = []
                # 選項文字不算已讀：遊戲的已讀紀錄（ReadStoryData）從來不記選項
                for br, (label, key) in pairs:
                    sub = summarize(br["block"], vars_, depth + 1)
                    sub_texts = sub.pop("_texts")
                    branches.append({"label": label, "read": read_ratio(sub_texts), **sub})
                    texts.extend(sub_texts)
                node = {"t": "branch", "kind": kind, "name": name, "branches": branches}
                if battles:
                    node["battles"] = battles
                items.append(node)
            else:
                for br, (label, key) in pairs:
                    sub = summarize(br["block"], vars_, depth + 1)
                    texts.extend(sub.pop("_texts"))
                    stories.extend(sub.get("legend_keys", []))
                    for x in sub["items"]:
                        # 分支收起來後，旗標仍要知道是在什麼條件下設的
                        if x["t"] == "flag" and kind in ("switch", "cond", "dice") and not label.startswith("以上皆非"):
                            x = dict(x, when=x.get("when", []) + [label])
                        items.append(x)
        elif t in ("next", "next_var", "scene", "mission", "ending", "cg", "time", "battle", "lover"):
            items.append(it)
        elif t == "flag":
            items.append(it)
    return {"items": items, "_texts": texts, "legend_keys": stories, "legend": legend(stories)}


# ---------- 決鬥中的事件（第幾回合有人出場、狀態變化、改旗標…） ----------
# 每場決鬥（CombatLevel.Events）整理成「條件：發生什麼」；改的旗標記下來，當成那場戰鬥的設定點。
combat_objs = {}
combat_path = os.path.join(os.path.dirname(battle_path), "combat_events.json") if battle_path else ""
if combat_path and os.path.exists(combat_path):
    for _t, _lst in json.load(open(combat_path, encoding="utf-8")).items():
        for _o in _lst:
            combat_objs[f"{_t}:{_o['m_Name']}@{_o.get('__file')}:{_o.get('__pid')}"] = (_t, _o)
CMP = {0: "=", 1: "≠", 2: "<", 3: "≤", 4: ">", 5: "≥"}
SIDE = {1: "我方", 2: "敵方"}
NAME_OPS = [("_EQ_", " = "), ("_NE_", " ≠ "), ("NEQ", " ≠ "), ("_GE_", " ≥ "), ("_LE_", " ≤ "), ("_GT_", " > "), ("_LT_", " < ")]


def ref_tail(ref):
    """「CombatStateEffectScriptable:C506_某某@…」→「某某」"""
    name = (ref or "").split("@")[0].split(":", 1)[-1]
    name = name.split("_", 1)[1] if "_" in name else name
    # 「峨嵋弟子_01」「2_小師妹」「上官螢_苦惱拳」→「峨嵋弟子」「小師妹」「上官螢·苦惱拳」
    return re.sub(r"_\d+$|^\d+_", "", name).replace("_", "·")


def name_text(name):
    """物件名稱本身就是描述（「我方_血量_GE_01」「數值_修養_GE_40」）：換成符號、去掉底線。"""
    for x, y in NAME_OPS:
        name = name.replace(x, y)
    name = re.sub(r"^數值_", "", name)
    # 百分比：「05PCT」「PCT50」→「5%」「50%」
    name = re.sub(r"PCT_?0*(\d+)|0*(\d+)_?PCT", lambda m: (m.group(1) or m.group(2)) + "%", name)
    if name.startswith("旗標"):
        name = re.sub(r"^旗標_?", "旗標 ", name)
    return re.sub(r"\b0+(\d)", r"\1", name).replace("_", "")


def combat_cond(ref):
    t, o = combat_objs.get(ref, (None, None))
    if not o:
        return ref_tail(ref)
    if t == "CombatEventConditionRound":
        r, op = o["_round"], o["_op"]
        return (f"撐到第 {r} 回合" if r > 1 else "第 1 回合") if op == 0 else f"第 {r} 回合起" if op == 5 else             f"前 {r} 回合內" if op == 3 else f"前 {r - 1} 回合內" if op == 2 else f"回合數 {CMP.get(op, op)} {r}"
    if t == "CombatEventConditionEffectState":
        return f"{SIDE.get(o.get('_character'), '')}身上有「{ref_tail(o.get('_effectState'))}」"
    if t == "CombatEventConditionRoundFlag":
        return "到了記下的回合"
    if t == "CombatEventConditionBlockCounterAttack":
        return "擋下對方的反擊"
    return name_text(o["m_Name"])


def action_text(text):
    """「動作_嘴攻_發動」→「使出嘴攻」（沒抽出來的出招條件只剩名稱）"""
    m = re.search(r"動作[_·](.+?)[_·](發動|命中|未命中|使用)$", text)
    if not m:
        return text
    return {"發動": f"使出{m.group(1)}", "使用": f"使用{m.group(1)}的動作", "命中": f"{m.group(1)}命中", "未命中": f"{m.group(1)}沒命中"}[m.group(2)]


def combat_actions(refs):
    """回傳（文字、改的旗標、出場說話的人）"""
    texts, flags, who = [], [], []
    for ref in refs or []:
        t, o = combat_objs.get(ref, (None, None))
        if not o:
            continue
        if t == "CombatEventActionDialog":
            for d in o.get("_dialogs", [])[:1]:
                sm = deref(d.get("_characterKey")) if d.get("_characterKey") else None
                speaker = (sm.get("Key") or "").split("_")[0] if sm else ""
                text = (loc.get("CombatTalking/" + d.get("_key", "")) or d.get("_text") or "").replace("\n", "")
                if speaker:
                    who.append(speaker)
                texts.append(f"{speaker + '：' if speaker else ''}「{text[:24]}{'…' if len(text) > 24 else ''}」")
        elif t == "CombatEventActionStateEffect":
            texts.append(f"{SIDE.get(o.get('_character'), '')}{'獲得' if o.get('_type') == 1 else '失去'}「{ref_tail(o.get('_effect'))}」")
        elif t == "CombatEventActionModifyFlag":
            flags.append((ref_name(o["_flag"]), o["_state"]))
        elif t == "CombatEventActionPunchSupport":
            texts.append(f"{SIDE.get(o.get('_character'), '')}得到「{ref_tail(o.get('_support'))}」助攻")
        elif t == "CombatEventActionLoadScene":
            texts.append("戰鬥直接結束")
        elif t == "CombatEventActionSetStoryScript":
            texts.append(f"戰後改接劇情 {o.get('_name')}")
        elif t == "CombatEventActionCount":
            items = o.get("_items")
            items = json.loads(items) if isinstance(items, str) else items or []
            for it in items:
                sub, sub_flags, sub_who = combat_actions(it.get("Actions"))
                flags += sub_flags
                who += sub_who
                if sub:
                    texts.append(f"第 {it.get('Count')} 次：" + "、".join(sub))
        elif t in ("CombatEventActionModifyStat", "CombatEventActionModifyWeaponValue", "CombatEventActionRemoveAllStateEffect",
                   "CombatEventActionRemoveAllSupport", "CombatEventActionCrazyMode", "CombatEventActionReduceEffectCount",
                   "CombatEventActionRelationshipAttack"):
            texts.append(name_text(o["m_Name"]))
    return texts, flags, who


def combat_events(level):
    out = []
    for ce_ref in level.get("Events") or []:
        _, ce = combat_objs.get(ce_ref, (None, None))
        if not ce:
            continue
        texts, flags, who = combat_actions(ce.get("_initAction"))
        if texts or flags:
            out.append({"when": "戰鬥開始時", "what": "；".join(texts), "flags": flags, "who": who})
        for ca_ref in ce.get("_conditionAction") or []:
            _, ca = combat_objs.get(ca_ref, (None, None))
            if not ca:
                continue
            when = (" 且 " if ca.get("_logic", 0) == 0 else " 或 ").join(action_text(combat_cond(c)) for c in ca.get("_conditions") or []) or "戰鬥中"
            texts, flags, who = combat_actions((ca.get("_actions") or []) + (ca.get("_afterActions") or []) + (ca.get("_afterResult") or []))
            if texts or flags:
                out.append({"when": when, "what": "；".join(texts), "flags": flags, "who": who})
    return out


if battle_path and os.path.exists(battle_path):
    for level in battle_dump.get("CombatLevel", []):
        evs = combat_events(level)
        if evs:
            level_info.setdefault(level["m_Name"], {})["events"] = evs

battles_into = collections.defaultdict(list)


def pair_battles(script, block):
    pending = None
    for it in block:
        if it["t"] == "next" and it.get("via") == "after":
            pending = it["s"].lower()
        elif it["t"] == "battle":
            info = level_info.get(level_name(it["mode"], it["key"]), {})
            it["enemy"] = info.get("enemy", "")
            it["desc"] = info.get("desc", "")
            if info.get("events"):
                it["events"] = [f"{e['when']}：{e['what']}" for e in info["events"] if e["what"]]
            if info.get("deadLib"):
                it["dead"] = info["deadLib"]
            if pending:
                it["after"] = pending
                entry = {"mode": it["mode"], "key": it["key"], "from": script, "enemy": it["enemy"]}
                if entry not in battles_into[pending]:
                    battles_into[pending].append(entry)
        elif it["t"] == "if":
            for br in it["branches"]:
                pair_battles(script, br["block"])


for name, (block, vars_) in scripts.items():
    pair_battles(name, block)

CURRENT = [None]
script_info = {}
for name, (block, vars_) in scripts.items():
    CURRENT[0] = name
    s = summarize(block, vars_)
    texts = s.pop("_texts")
    script_info[name] = {
        "read": read_ratio(texts),
        "lines": len(set(texts)),
        **s,
    }
    script_info[name].pop("legend_keys", None)


def strip_legend_keys(node):
    if isinstance(node, dict):
        node.pop("legend_keys", None)
        for v in node.values():
            strip_legend_keys(v)
    elif isinstance(node, list):
        for v in node:
            strip_legend_keys(v)


strip_legend_keys(script_info)


def next_scripts(name):
    out = []
    def walk(items):
        for it in items:
            if it["t"] == "next":
                out.append(it["s"].lower())
            elif it["t"] == "branch":
                for br in it["branches"]:
                    walk(br["items"])
    walk(script_info.get(name, {}).get("items", []))
    return list(dict.fromkeys(out))


# ---------- 任務 / 事件 ----------
cps = by_name["MissionCheckData"]
missions = by_name["MissionData"]
main_name = ref_name(so["MissionManagerData"][0]["_main"])
sub_names = [ref_name(r) for r in so["SubMissionsData"][0]["_list"]]


def gt(t):
    return {"y": t["Year"], "m": t["Month"], "s": t["Stage"]}


def fixed_time(ref):
    """StatGroupVariable 若是單一個非「目前時間」的遊戲時間，回傳該時間。"""
    o = deref(ref)
    vals = (o or {}).get("_value", [])
    if len(vals) == 1 and vals[0]["_checkType"] == 9:
        t = deref(vals[0]["_gameTime"])
        if t and t["m_Name"].startswith("第"):
            return gt(t["GameTime"])
    return None


def is_now(ref):
    o = deref(ref)
    vals = (o or {}).get("_value", [])
    if len(vals) == 1 and vals[0]["_checkType"] == 9:
        t = deref(vals[0]["_gameTime"])
        return not t or t["m_Name"] == "PlayerGameTime"
    return False


def time_from_conditions(conditions):
    """條件裡「目前時間 ≥ X 且 ≤ Y」這類寫法轉成時間區間（只看 AND 條件）。"""
    lo = hi = None
    for ci in conditions:
        if ci.get("_logicOp", 0) != 0:
            continue
        for it in ci.get("_items", []):
            op = it["_compareOp"]
            if is_now(it["_value1"]):
                t = fixed_time(it["_value2"])
            elif is_now(it["_value2"]):
                t = fixed_time(it["_value1"])
                op = {2: 4, 3: 5, 4: 2, 5: 3}.get(op, op)
            else:
                continue
            if not t:
                continue
            if op == 0:
                lo = hi = t
            elif op in (4, 5):
                lo = t
            elif op in (2, 3):
                hi = t
    if lo and hi:
        return {"type": "at", "from": lo} if lo == hi else {"type": "range", "from": lo, "to": hi}
    if lo:
        return {"type": "range", "from": lo, "to": {"y": 4, "m": 3, "s": 3}, "open": True}
    return None


script_time = {}


def time_after(script):
    """腳本內最後一次 SetGameTime 的值（之後接續的腳本從這個時間開始）。"""
    last = None

    def walk(items):
        nonlocal last
        for it in items:
            if it["t"] == "time":
                last = {"y": it["y"], "m": it["m"], "s": it["st"]}
            elif it["t"] == "branch":
                for br in it["branches"]:
                    walk(br["items"])
    walk(script_info.get(script, {}).get("items", []))
    return last


FREE_HUB = re.compile(r"^section_0*(\d+)_free_start_\d+$")


def sub_chapter(script):
    """劇本的段落編號：ch5_6_3_1 → ch5_6"""
    m = re.match(r"^(ch\d+_\d+)(?:_|$)", script or "")
    return m.group(1) if m else None


def part_key(script):
    hub = FREE_HUB.match(script or "")
    return f"hub{hub.group(1)}" if hub else sub_chapter(script)


def trace_chain(start, start_time, stop=(), cuts=None):
    """從開頭一路追到底（不設上限），順便推算每支腳本開始時的遊戲時間。stop：追到就停的腳本。
    cuts：有給就在劇情換段的地方停（見 should_cut），記下 {斷點腳本: 到那裡的時間}。"""
    chain, queue = [], [(start, start_time, part_key(start))] if start else []
    # 多條路徑到同一支腳本時取較晚的時間；時間變晚才重新往下傳
    in_chain, t_of = set(), {}
    tkey = lambda t: (t["y"], t["m"], t["s"]) if t else (0, 0, 0)
    while queue:
        s, t, cur = queue.pop(0)
        if s not in script_info:
            continue
        if s in in_chain and tkey(t) <= tkey(t_of.get(s)):
            continue
        if s not in in_chain:
            chain.append(s)
            in_chain.add(s)
        t_of[s] = t
        after = time_after(s) or t
        cur = part_key(s) or cur
        for n in next_scripts(s):
            if n in entry_scripts or n in stop:
                continue
            if cuts is not None and should_cut(cur, n):
                if n not in cuts or tkey(after) < tkey(cuts[n]):
                    cuts[n] = after
                continue
            queue.append((n, after, cur))
    for s, t in t_of.items():
        if t and tkey(t) > tkey(script_time.get(s)):
            script_time[s] = t
    return chain


events = []
entry_scripts = set()
for mission_name in [main_name] + sub_names:
    m = missions.get(mission_name)
    if not m:
        continue
    for r in m.get("_missions", []):
        c = cps.get(ref_name(r)) if r else None
        if c and c.get("_startScript"):
            entry_scripts.add(c["_startScript"].lower())

for mission_name in [main_name] + sub_names:
    m = missions.get(mission_name)
    if not m:
        continue
    for r in m.get("_missions", []):
        c = cps.get(ref_name(r)) if r else None
        if not c:
            continue
        time = None
        if c["_dayCheck"]:
            if c["_timeCheckType"] == 1:
                time = {"type": "at", "from": gt(c["_specificTime"])}
            elif c["_timeCheckType"] == 2:
                time = {"type": "range", "from": gt(c["_minTime"]), "to": gt(c["_maxTime"])}
            else:
                time = {"type": "period", "stage": c["_periodStage"]}
        if time is None:
            time = time_from_conditions(c.get("_conditions", []))
        start_time = time.get("from") if time and time.get("from", {}).get("y", 0) >= 1 else None
        chain = trace_chain(c["_startScript"].lower(), start_time)
        events.append({
            "id": f"{mission_name}/{c['_key']}",
            "mission": mission_name,
            "main": mission_name == main_name,
            "key": c["_key"],
            "active": bool(c["_active"]),
            "time": time,
            "pos": POS.get(c["_position"], "") if c["_position"] else "",
            "conds": [cond_item_text(ci) for ci in c.get("_conditions", [])],
            "start": c["_startScript"].lower(),
            "nextState": c["_nextStateName"],
            "dialogs": [loc.get("Mission/" + d["_dialog"]) or d["_dialog"] for d in c.get("_startDialogs", [])],
            "scripts": chain,
            # 開發者給的短名稱：檢查點的優先，沒有就用任務的（「主線任務」這種通用說明不用）
            "desc": re.sub(r"^\d+-\d+\s*", "", (c.get("_desc") or "").strip())
                    or ((m.get("_desc") or "").strip() if (m.get("_desc") or "").strip() not in ("主線任務", "支線任務") else ""),
        })

def satisfies(v, op, n):
    return {"=": v == n, "≠": v != n, "<": v < n, "≤": v <= n, ">": v > n, "≥": v >= n}[op]


# ---------- 唐門月會 ----------
# 每個月的月會事件（S1108、S1109…）和幾段主線結尾都接到同一個選單 meeting_option_01，
# 選單的 24 個選項各有條件（時間、旗標、門派規模…），所以每個月份的事件底下內容都一樣。
# 改成：月份事件只留選單本身，每個選項各自一個事件，月份用選項條件從「有開月會的月份」篩出來。
MEETING_START, MEETING_MENU = "meeting_start_01", "meeting_option_01"
NOW_COND = re.compile(r"目前時間 (=|≠|<|≤|>|≥) 第(\d+)年(\d+)月(上|中|下)旬")
meeting_months = set()
for e in events:
    t = e["time"]
    if not t or t["type"] != "at":
        continue
    if e["start"] == MEETING_START or any(MEETING_START in next_scripts(sc) for sc in e["scripts"]):
        meeting_months.add((t["from"]["y"], t["from"]["m"], t["from"]["s"]))
meeting_months = sorted(meeting_months)
hub_scripts = [MEETING_START, MEETING_MENU]
for e in events:
    if e["start"] == MEETING_START:
        e["scripts"] = hub_scripts
        e["meeting"] = True
ids_seen = set()
for it in script_info[MEETING_MENU]["items"]:
    if it["t"] != "branch":
        continue
    for br in it["branches"]:
        start = next((x["s"].lower() for x in br["items"] if x["t"] == "next"), None)
        name, _, need = br["label"].partition("　〔需：")
        need = need.rstrip("〕")
        # 條件只寫了名字（遊戲裡沒有這個條件，例如 Meeting_Option_703_02_XXX）的選項不會出現
        if not start or start in entry_scripts or f"Meeting/{start}" in ids_seen or re.fullmatch(r"[A-Za-z0-9_]+", need):
            continue
        ids_seen.add(f"Meeting/{start}")
        months = meeting_months
        # 時間條件只在全部用「且」連接時才拿來篩月份
        if "或" not in need:
            for op, y, m, st in NOW_COND.findall(need):
                v = (int(y), int(m), "上中下".index(st) + 1)
                months = [t for t in months if satisfies(t, op, v)]
        # 選不到的選項（例如第2年2月的留學走另一個臨時選單）不另列
        if not months:
            continue
        first, last = ({"y": t[0], "m": t[1], "s": t[2]} for t in (months[0], months[-1]))
        events.append({
            "id": f"Meeting/{start}",
            "mission": "Meeting",
            "main": False,
            "key": start,
            "active": True,
            "time": {"type": "at", "from": first} if first == last else {"type": "range", "from": first, "to": last},
            "pos": "",
            "conds": [f"唐門月會選「{name}」"] + ([need] if need else []),
            "start": start,
            "nextState": "",
            "dialogs": [],
            # 選完回到選單的不再往下追
            "scripts": trace_chain(start, first, stop=hub_scripts),
            "meetingMonths": [{"y": t[0], "m": t[1], "s": t[2]} for t in months],
            "meetingOption": name,
        })

# ---------- 長事件切段 ----------
# 一個檢查點接下去的劇情常會一路演好幾段（求親 → 金烏上人鬧場 → 崆峒神威…）。
# 劇本編號 chX_Y 的 Y 換了就是換一段劇情；留學的自由行動選單（section_0N_free_start）也自成一段。
# 換段的地方斷開，後面另成一個「接續」事件（同一段有好幾個入口時併成一個）。
PART_MIN = 3   # 太短（不到 3 支腳本）的段落不另外切


def part_size(script):
    key, seen, queue = part_key(script), {script}, [script]
    while queue and len(seen) < PART_MIN:
        for n in next_scripts(queue.pop(0)):
            if n not in seen and part_key(n) == key and n not in entry_scripts:
                seen.add(n)
                queue.append(n)
    return len(seen)


def should_cut(cur, n):
    key = part_key(n)
    return bool(key) and key != cur and (key.startswith("hub") or part_size(n) >= PART_MIN)


# 段落名稱：那段裡決鬥的開發者說明開頭（「崆峒神威 刺客」→「崆峒神威」）最常見的那個
def part_desc(scripts):
    names = collections.Counter()

    def walk(items):
        for it in items:
            if it["t"] == "battle" and level_info.get(level_name(it["mode"], it["key"]), {}).get("desc"):
                names[level_info[level_name(it["mode"], it["key"])]["desc"].split(" ")[0]] += 1
            elif it["t"] == "if":
                for br in it["branches"]:
                    walk(br["block"])
    for sc in scripts:
        if sc in scripts_lower:
            walk(scripts_lower[sc][0])
    return names.most_common(1)[0][0] if names else ""


scripts_lower = {k.lower(): v for k, v in scripts.items()}
HUB_DESC = {"1": "崆峒留學：每旬自由行動", "2": "青城留學：每旬自由行動"}
parts = {}          # 段落 → {入口腳本: 到達時間}
part_from = collections.defaultdict(set)
hub_span = {}
# 已經是同一段事件裡的腳本（例如客棧選單同時被好幾個事件用到）：斷開後連到那個事件就好，不另成一段
own_part = {sc for e in events for sc in e["scripts"] if sub_chapter(sc) and sub_chapter(sc) == sub_chapter(e["start"])}
# 開發者說明裡沒有段落名稱的，照內容取名
PART_NAMES = {"ch2_5": "抵達崆峒", "ch5_3": "比武招親", "ch4_6": "臥雲崗約戰", "ch8_5": "六大派攻山", "ch3_10": "江陵決戰泥教",
              "ch8_4": "南溪大戰南宮深", "ch3_15": "襄陽城外遇小竹", "ch6_9": "武林大會後歇宿", "ch6_10": "聽說武林大會後續"}


def cut_event(e, start, start_time):
    cuts = {}
    e["scripts"] = trace_chain(start, start_time, stop=hub_scripts if e.get("meetingOption") else (), cuts=cuts)
    for n, t in cuts.items():
        key = part_key(n)
        if key == e.get("part") or n in own_part:
            continue
        ent = parts.setdefault(key, {})
        # 多條路徑到同一個入口時取較晚的時間（和 trace_chain 一樣；較早的常是沒在用的檢查點的假時間）
        tk = lambda x: (x["y"], x["m"], x["s"]) if x else (0, 0, 0)
        if n not in ent or tk(t) > tk(ent[n]):
            ent[n] = t
        part_from[key].add(e["id"])
        # 自由行動選單：主線帶進來的時間範圍（支線事件的時間常不準）
        if t and e["main"]:
            span = hub_span.setdefault(key, [t, t])
            span[0], span[1] = min(span[0], t, key=tk), max(span[1], t, key=tk)


for e in list(events):
    if e.get("meeting"):
        continue
    t = (e["time"] or {}).get("from")
    cut_event(e, e["start"], t if t and t.get("y", 0) >= 1 else None)
# 段落本身也可能再接到下一段：一直做到沒有新入口為止
done = {}
while True:
    todo = [k for k, ent in parts.items() if done.get(k) != sorted(ent)]
    if not todo:
        break
    for key in todo:
        ent = parts[key]
        done[key] = sorted(ent)
        tk = lambda x: (x["y"], x["m"], x["s"]) if x else (99, 0, 0)
        # 入口：段落編號的第一支（chX_Y_1）優先，其次最早到的
        starts = sorted(ent, key=lambda n: (not re.fullmatch(r"ch\d+_\d+_1|section_\d+_free_start_01", n), tk(ent[n]), n))
        e = next((x for x in events if x.get("part") == key), None)
        if not e:
            e = {"id": f"Part/{key}", "mission": "Part", "main": True, "key": key, "active": True, "pos": "",
                 "conds": [], "nextState": "", "dialogs": [], "part": key}
            events.append(e)
        times = sorted((ent[n] for n in ent if ent[n]), key=tk)
        e["start"] = starts[0]
        # 劇情段落接在前一段後面，取最晚的時間；自由行動選單整段留學期間都會回來，列出範圍
        if key.startswith("hub"):
            times = hub_span.get(key, times)
        elif times:
            times = times[-1:]
        e["time"] = None if not times else {"type": "at", "from": times[0]} if times[0] == times[-1] else {"type": "range", "from": times[0], "to": times[-1]}
        if key.startswith("hub") and times:
            e["time"] = {"type": "range", "from": times[0], "to": {"y": 4, "m": 3, "s": 3}, "open": True}
        chain = []
        for n in starts:
            cut_event(e, n, ent[n])
            chain += [x for x in e["scripts"] if x not in chain]
        e["scripts"] = chain
for e in events:
    if e.get("part"):
        e["partFrom"] = sorted(part_from[e["part"]])
        hub = re.fullmatch(r"hub(\d+)", e["part"])
        # 決鬥說明的名稱有時是整章的名字（ch5_3 的「小師妹出嫁」和前一段同名），有手動取名的優先
        e["desc"] = HUB_DESC.get(hub.group(1), "留學：自由行動") if hub else PART_NAMES.get(e["part"]) or part_desc(e["scripts"])

# 同名的段落（武林大會分好幾段）加上序號
desc_count = collections.Counter(e["desc"] for e in events if e.get("part") and e["desc"])
desc_seen = collections.Counter()
for e in events:
    if e.get("part") and desc_count[e["desc"]] > 1:
        desc_seen[e["desc"]] += 1
        e["desc"] += f"（{'一二三四五六七八九十'[desc_seen[e['desc']] - 1]}）"

# 旗標反查：哪個腳本、哪個分支把旗標設成多少
flag_setters = collections.defaultdict(list)


lover_points = collections.defaultdict(list)


def index_flags(script, items, path):
    for it in items:
        if it["t"] == "lover":
            lover_points[it["v"]].append({"s": script, "path": path})
        if it["t"] == "flag":
            flag_setters[it["f"]].append({"s": script, "v": it["v"], "path": path + it.get("when", []), "op": it["op"]})
        elif it["t"] == "branch":
            for br in it["branches"]:
                index_flags(script, br["items"], path + [br["label"]])


def add_battle_flags(items):
    out = []
    for it in items:
        out.append(it)
        if it["t"] == "battle":
            for e in level_info.get(level_name(it["mode"], it["key"]), {}).get("events", []):
                # 戰鬥內部用的暫存旗標（確保只觸發一次的計數）對玩家沒意義，從說明拿掉
                when = re.sub(r"^旗標 (?:TC|[ABC])\d+ \S+ -?\d+ 且 | 且 旗標 (?:TC|[ABC])\d+ \S+ -?\d+", "", e["when"])
                label = "戰鬥中：" + (when if when.startswith(("撐到", "戰鬥開始")) else when + "時") \
                        + (f"（{'、'.join(dict.fromkeys(e['who']))}出場）" if e["who"] else "")
                out += [{"t": "flag", "op": "SetFlag", "f": f, "v": v, "when": [label]} for f, v in e["flags"]]
        elif it["t"] == "branch":
            for br in it["branches"]:
                br["items"] = add_battle_flags(br["items"])
    return out


for name, info in script_info.items():
    info["items"] = add_battle_flags(info["items"])

# 戰鬥事件裡的暫存旗標（TC0001、A00001…）是戰前劇情設的：換成戰前的選項／條件，找不到就合併成「依戰前情況」
TEMP_ATOM = re.compile(r"旗標 ((?:TC|[ABC])\d+) (=|≠|<|≤|>|≥) (-?\d+)")
CMP_FN = {"=": lambda a, b: a == b, "≠": lambda a, b: a != b, "<": lambda a, b: a < b, "≤": lambda a, b: a <= b, ">": lambda a, b: a > b, "≥": lambda a, b: a >= b}


def temp_setters(items, path, out, nexts):
    for it in items:
        if it["t"] == "flag" and TEMP_ATOM.match(f"旗標 {it['f']} = 0") and not any(w.startswith("戰鬥中") for w in it.get("when", [])):
            out.append((it["f"], it["v"], it["op"], path + it.get("when", [])))
        elif it["t"] == "next":
            nexts.add(it["s"].lower())
        elif it["t"] == "branch":
            for br in it["branches"]:
                temp_setters(br["items"], path + [br["label"]], out, nexts)


script_temp, script_callers = {}, collections.defaultdict(set)
for name, info in script_info.items():
    out, nexts = [], set()
    temp_setters(info["items"], [], out, nexts)
    script_temp[name] = out
    for n in nexts:
        script_callers[n].add(name)


def temp_label(script, f, op, v):
    """None：找不到；""：其他情況；否則是戰前的選項或條件"""
    cand = [x for x in script_temp.get(script, []) if x[0] == f]
    if not cand:
        cand = [x for c in script_callers.get(script.lower(), ()) for x in script_temp.get(c, []) if x[0] == f]
    if not cand or any(x[2] != "SetFlag" for x in cand):
        return None
    hit = [x for x in cand if CMP_FN[op](x[1], v)]
    if not hit:
        return None
    labels = []
    for x in hit:
        if not x[3]:
            return ""
        label = re.sub(r"　〔(?:需|前提不是)：.*〕$", "", x[3][-1])
        if TEMP_ATOM.search(label):
            return None
        labels.append(re.sub(r"（(?:>=|<=|<|>)\d+）$", "", label))
    labels = list(dict.fromkeys(labels))
    return labels[0] if len(labels) == 1 else None


def plain_battle_events(script, items):
    for it in items:
        if it["t"] == "battle" and it.get("events"):
            out = []
            # 戰鬥中自己設的旗標（「前 7 回合用了備揍、嘴攻以外的動作」記成 TC0003 = 1）：寫成戰鬥中有沒有發生那件事
            in_battle = {}
            for e2 in level_info.get(level_name(it["mode"], it["key"]), {}).get("events", []):
                for f2, v2 in e2["flags"]:
                    in_battle[f2] = (re.sub(r"^旗標 \S+ \S+ -?\d+ 且 | 且 旗標 \S+ \S+ -?\d+", "", e2["when"]), v2)
            for ev in it["events"]:
                when, _, what = ev.partition("：")
                atoms = []
                for a in when.split(" 且 "):
                    m = TEMP_ATOM.fullmatch(a)
                    if m and m.group(1) in in_battle:
                        w2, v2 = in_battle[m.group(1)]
                        hit, dflt = satisfies(v2, m.group(2), int(m.group(3))), satisfies(0, m.group(2), int(m.group(3)))
                        w2 = w2.replace(" 且 ", "")
                        # 出招、回合這類「發生過的事」寫有沒有；單純的屬性檢查（只觸發一次的台詞）寫那段發生過沒
                        act = re.search(r"使用|使出|命中|回合|擋下", w2)
                        a = (f"戰鬥中有「{w2}」" if act else f"戰鬥中「{w2}」那段發生過") if hit and not dflt else                             (f"戰鬥中沒有「{w2}」" if act else f"戰鬥中「{w2}」那段還沒發生") if dflt and not hit else a
                    atoms.append(a)
                base = [a for a in atoms if not TEMP_ATOM.fullmatch(a)]
                labels = [temp_label(script, *m.groups()[:2], int(m.group(3))) for m in map(TEMP_ATOM.fullmatch, atoms) if m]
                head = " 且 ".join(base) or "戰鬥中"
                if not labels:
                    out.append([head, what, None, None])
                elif None in labels:
                    # 只有同一組旗標的才合併（記在第 4 欄）
                    out.append([head, what, "依戰前情況", tuple(m.group(1) for m in map(TEMP_ATOM.fullmatch, atoms) if m)])
                else:
                    known = [l for l in labels if l]
                    # 選項寫「選「X」」，條件直接寫（網頁再轉白話）
                    known = [k if re.search(r"[=≠<>≤≥]", k) and "「" not in k else f"選「{k}」" for k in known]
                    out.append([head, what, "戰前" + "且".join(known) if known else "其他情況", None])
            # 同一個時間點、只差戰前情況的接成一行：「第 1 回合（依戰前情況）：我方血量減5%／10%」
            merged = []
            for head, what, cond, fl in out:
                if fl and merged and merged[-1][0] == head and merged[-1][3] == fl:
                    merged[-1][1] += "／" + what
                else:
                    merged.append([head, what, cond, fl])
            it["events"] = [f"{h}{f'（{c}）' if c else ''}：{w}" for h, w, c, _ in merged]
        elif it["t"] == "branch":
            for br in it["branches"]:
                plain_battle_events(script, br["items"])


for name, info in script_info.items():
    plain_battle_events(name, info["items"])

for name, info in script_info.items():
    index_flags(name, info["items"], [])

talk_labels = {}
for f, setters in flag_setters.items():
    if f.startswith("Talk_Option"):
        for x in setters:
            # 取路徑上最後一個「選項文字」（不是條件判斷）當作這個暫存旗標的名字
            options = [re.sub(r"　〔需：.*〕$", "", label) for label in x["path"]
                       if not re.search(r"旗標 |[≥≤≠<>]| = |以上皆非", re.sub(r"　〔需：.*〕$", "", label))]
            if x["v"] == 1 and options:
                talk_labels.setdefault((x["s"], f), options[-1])
TALK_COND = re.compile(r"旗標 (Talk_Option_\d+) (=|≥|≠|>) (\d+)")


def humanize(script, text):
    def sub(m):
        label = talk_labels.get((script, m.group(1)))
        if not label:
            return m.group(0)
        chosen = (m.group(2) in ("≥", ">") and int(m.group(3)) <= 1) or (m.group(2) == "=" and m.group(3) != "0") or (m.group(2) == "≠" and m.group(3) == "0")
        return f"已選過「{label}」" if chosen else f"還沒選過「{label}」"
    text = TALK_COND.sub(sub, text)
    # 多個暫存旗標可能對到同一個選項，白話後會重複，去掉重複的片段
    parts = text.split(" 且 ")
    return " 且 ".join(dict.fromkeys(parts))


def humanize_items(script, items):
    for it in items:
        if it["t"] == "branch":
            for br in it["branches"]:
                br["label"] = humanize(script, br["label"])
                humanize_items(script, br["items"])


for name, info in script_info.items():
    humanize_items(name, info["items"])
for setters in flag_setters.values():
    for x in setters:
        x["path"] = [humanize(x["s"], label) for label in x["path"]]


def first_line(script):
    info = script_info.get(script)
    if not info:
        return None
    for text in info["legend"]:
        for para in text.split("\n"):
            if para.strip():
                return para.strip()
    return None


for e in events:
    title = None
    for sc in e["scripts"]:
        title = first_line(sc)
        if title:
            break
    e["hasLegend"] = bool(title)
    if not title:
        for sc in e["scripts"]:
            text = loc.get("Story/" + script_first_say[sc]) if script_first_say.get(sc) else None
            if text:
                title = "「" + re.sub(r"<[^>]+>|\{[^}]*\}", "", text).replace("\n", "") + "」"
                break
    if e.get("meeting"):
        title = "唐門月會（選單）"
    elif e.get("meetingOption") and not e["hasLegend"]:
        title = f"月會：{e['meetingOption']}"
    e["title"] = title

# 腳本 → 所屬事件：先看事件腳本鏈，找不到就沿「誰接到這支腳本」往上追
owner = {}
for e in events:
    for s in e["scripts"]:
        owner.setdefault(s, e["id"])
parents = collections.defaultdict(set)
for name in script_info:
    for n in next_scripts(name):
        parents[n].add(name)


def find_owner(script):
    seen, queue = {script}, [script]
    while queue:
        s = queue.pop(0)
        if s in owner:
            return owner[s], s
        for p in parents.get(s, ()):
            if p not in seen:
                seen.add(p)
                queue.append(p)
    return None, None


used = {s for e in events for s in e["scripts"]}
for pts in lover_points.values():
    for x in pts:
        used.add(x["s"])
        ev, via = find_owner(x["s"])
        if ev:
            x["ev"] = ev
            if via != x["s"]:
                x["via"] = via
for setters in flag_setters.values():
    for x in setters:
        used.add(x["s"])
        ev, via = find_owner(x["s"])
        if ev:
            x["ev"] = ev
            if via != x["s"]:
                x["via"] = via
# 女主角：G1000i＝相識、G1100i＝結緣（結局 ch8_8_1 依 Switch Ch_8_8_1_001 選 CG 4000x），心上人另有編號
HEROINES = [
    # (名字, G 旗標編號, 心上人編號, 結緣結局圖鑑)
    # 上官螢、魏菊、瑞杏尚未實裝結緣結局，先不列
    ("小師妹", 0, 0, "40000"), ("葉雲裳", 2, 2, "40003"), ("龍湘", 3, 8, "40001"),
    ("虞小梅", 4, 3, "40004"), ("夏侯蘭", 5, 5, "40002"), ("郁竹", 6, 6, "40005"),
]


def setters_with_owner(flag):
    out = []
    for x in flag_setters.get(flag, []):
        x = dict(x)
        ev, via = find_owner(x["s"])
        if ev:
            x["ev"] = ev
            if via != x["s"]:
                x["via"] = via
        out.append(x)
    return out


# 進入某支腳本前要經過的選項／條件：往上找呼叫它的腳本與分支路徑，
# 只經過無條件銜接的就繼續往上，遇到有條件的那層就記下來（最多 6 層）
entry_paths = collections.defaultdict(list)


def index_entries(script, items, path):
    for it in items:
        if it["t"] == "next":
            entry_paths[it["s"].lower()].append({"from": script, "path": [humanize(script, label) for label in path]})
        elif it["t"] == "branch":
            for br in it["branches"]:
                index_entries(script, br["items"], path + [br["label"]])


for name, info in script_info.items():
    index_entries(name, info["items"], [])


# 走到某支腳本的路線：從它往回追到事件開頭，列出每一條走得到的路線（沿途要選的選項、要符合的條件）。
# 只沿同一個事件裡的腳本往回追；有多個入口時每個入口各算一條路線。
event_by_id_lower = {e["id"].lower(): e for e in events}


HUB_NAME = {"1": "崆峒留學期間", "2": "青城留學期間"}
FREE_SCRIPT = re.compile(r"^section_0*\d+_free_")


def entry_routes(script, ev):
    e = event_by_id_lower.get((ev or "").lower())
    chain = set(e["scripts"]) if e else None
    start = e["start"] if e else None
    routes = []

    def walk(cur, acc, seen):
        if len(routes) >= 40:
            return
        parents = [x for x in entry_paths.get(cur, []) if x["from"] not in seen and (chain is None or x["from"] in chain)]
        if cur == start or cur in entry_scripts or not parents or len(acc) >= 10:
            routes.append((acc[::-1], seen))
            return
        for x in parents:
            hub = FREE_HUB.match(x["from"])
            if hub:
                # 養成選單的地點：只寫「某某期間去哪裡」，地點本身的開啟條件放在「其他條件」
                place = re.sub(r"　〔需：.*〕$", "", x["path"][-1]) if x["path"] else ""
                routes.append((([{"from": x["from"], "into": cur, "path": [place], "hub": HUB_NAME.get(hub.group(1), "留學期間")}] + acc[::-1]) if place else acc[::-1], seen))
                continue
            walk(x["from"], acc + ([{"from": x["from"], "into": cur, "path": x["path"]}] if x["path"] else []), seen + (x["from"],))

    # seen：路上經過的腳本，依序（從目標往回）
    walk(script, [], (script,))
    # 同一個旗標前後要求互相矛盾（先要「沒有 X」又要「X」），而且路上沒有地方會改它：這條路線走不通
    possible = [(r, seen) for r, seen in routes if route_possible(r, seen)]
    routes = possible or routes
    out, sigs = [], set()
    for r, seen in routes:
        sig = tuple((x["from"], tuple(x["path"])) for x in r)
        if sig not in sigs:
            sigs.add(sig)
            out.append(Route(r))
            out[-1].seen = seen
    # 有一條不用任何條件就走得到：其他路線都不必列
    if any(not r for r in out):
        return [[]]
    for r in out:
        for x in r:
            if (branch_read(x["from"], x["path"]) or 0) > 0:
                x["done"] = True
    return simplify_routes(out)[:6]


class Route(list):
    """路線（步驟清單），seen 記下路上經過的所有腳本（判斷旗標會不會在半路被改）"""
    seen = None


NEED_ATOM = re.compile(r"^旗標 ([A-Za-z0-9_]+) (=|≠|<|≤|>|≥) (-?\d+)$")
TEMP_FLAG_RE = re.compile(r"^(C\d|TC\d|A\d|B\d|Talk_Option|BattleResult|Prologue|ActionCheck)")


def label_constraints(label):
    """分支標籤裡對旗標的要求：（旗標, 要成立?, 比較, 數值）；「以上皆非（不是：…）」「〔前提不是：…〕」是不成立"""
    out = []
    lab = re.sub(r"^(勝利|落敗|符合|不符合)：", "", label)
    pre = re.search(r"　〔前提不是：(.*)〕$", lab)
    lab = re.sub(r"　〔.*〕$", "", lab)
    clauses = []
    if lab.startswith("以上皆非（不是："):
        clauses += [(c, False) for c in lab[8:-1].split("；")]
    elif " 或 " not in lab:
        clauses += [(c, True) for c in lab.split(" 且 ")]
    if pre:
        clauses += [(c, False) for c in pre.group(1).split("；")]
    for c, pos in clauses:
        m = NEED_ATOM.match(c.strip().strip("（）"))
        if m:
            out.append((m.group(1), pos, m.group(2), int(m.group(3))))
    return out


def route_possible(route, scripts):
    """scripts 是 tuple 時是路上依序經過的腳本（從目標往回）：只有夾在兩個要求之間的腳本改了旗標，前後不同才說得通；
    是 set 時不知道順序，路上任何地方會改它就不判斷。"""
    order = list(reversed(scripts)) if isinstance(scripts, tuple) else None
    pos_of = {sc: i for i, sc in enumerate(order)} if order else {}
    allowed, last = {}, {}
    for x in route:
        here = pos_of.get(x["from"])
        for label in x["path"]:
            for f, want, op, v in label_constraints(label):
                # 暫存旗標每段劇情重設
                if TEMP_FLAG_RE.match(f):
                    continue
                setters = {y["s"] for y in flag_setters.get(f, [])}
                if order is None or here is None:
                    if setters & set(scripts):
                        continue
                elif f in last and any(last[f] <= pos_of[sc] <= here for sc in setters if sc in pos_of):
                    allowed.pop(f, None)
                vals = {k for k in range(-1, 30) if satisfies(k, op, v) == want}
                allowed[f] = allowed.get(f, vals) & vals
                last[f] = here if here is not None else last.get(f, 0)
                if not allowed[f]:
                    return False
    return True


def branch_read(script, labels):
    """沿著分支標籤往下找，回傳最深那個分支的已讀比例；路上有條件分歧（不是選項、擲骰、戰鬥）就回傳 None。"""
    items, read = script_info.get(script, {}).get("items", []), None
    for label in labels:
        node, found = next(((it, br) for it in items if it["t"] == "branch" for br in it["branches"] if br["label"] == label), (None, None))
        if not found:
            return read
        if node["kind"] not in ("choice", "dice", "battle"):
            return None
        read, items = found.get("read"), found["items"]
    return read


def route_steps(r):
    return [(x["from"], tuple(x["path"])) for x in r]


def simplify_routes(routes):
    """條件完全包含另一條的路線不列（較寬鬆的就夠了）；只差在「X」與「不是 X」的兩條合併成一條。"""
    routes = sorted(routes, key=len)
    changed = True
    while changed:
        changed = False
        for i in range(len(routes)):
            for j in range(len(routes)):
                if i == j:
                    continue
                a, b = route_steps(routes[i]), route_steps(routes[j])
                if len(a) == len(b):
                    diff = [k for k in range(len(a)) if a[k] != b[k]]
                    if len(diff) == 1:
                        k = diff[0]
                        la, lb = a[k][1], b[k][1]
                        if a[k][0] == b[k][0] and len(la) == len(lb) == 1 and (lb[0] == f"以上皆非（不是：{la[0]}）" or la[0] == f"以上皆非（不是：{lb[0]}）"):
                            merged = Route(routes[i][:k] + routes[i][k + 1:])
                            merged.seen = getattr(routes[i], "seen", None)
                            routes[i] = merged
                            del routes[j]
                            changed = True
                            break
                if all(step in b for step in a) and len(a) < len(b):
                    del routes[j]
                    changed = True
                    break
            if changed:
                break
    return routes


def event_via(e):
    """事件開頭的腳本被其他事件／養成選單接過來時，列出那些入口的路線。"""
    # 事件結束常回到留學的養成選單，選單也會被算進事件自己的腳本鏈：選單的腳本一律當成外部入口
    own = {sc for sc in e["scripts"] if not FREE_SCRIPT.match(sc)}
    out = []
    for x in [x for x in entry_paths.get(e["start"], []) if x["from"] not in own][:4]:
        owner_ev, _ = find_owner(x["from"])
        last = [{"from": x["from"], "path": x["path"]}] if x["path"] else []
        for r in entry_routes(x["from"], owner_ev)[:2]:
            steps = [{k: v for k, v in y.items() if k != "into"} for y in r] + last
            if owner_ev and not (steps and steps[0].get("hub")):
                steps = [{"from": x["from"], "path": [], "ev": owner_ev}] + steps
            if route_possible(steps, r.seen if getattr(r, "seen", None) else (set(event_by_id_lower[owner_ev.lower()]["scripts"]) if owner_ev else set()) | {y["from"] for y in steps}):
                out.append(steps)
    return simplify_routes([r for r in out if r])[:3]


mission_points = collections.defaultdict(list)


def index_missions(script, items, path):
    for it in items:
        if it["t"] == "mission":
            mission_points[(it["m"], it["k"])].append({"from": script, "path": path})
        elif it["t"] == "branch":
            for br in it["branches"]:
                index_missions(script, br["items"], path + [br["label"]])


for _name, _info in script_info.items():
    index_missions(_name, _info["items"], [])


def event_activate(e):
    """事件要先被別段劇情啟動（Mission）：列出啟動它的路線。"""
    out = []
    for x in mission_points.get((e["mission"], e["key"]), [])[:4]:
        owner_ev, _ = find_owner(x["from"])
        last = [{"from": x["from"], "path": x["path"]}] if x["path"] else []
        for r in entry_routes(x["from"], owner_ev)[:2]:
            steps = [{k: v for k, v in y.items() if k != "into"} for y in r] + last
            if owner_ev and owner_ev != e["id"] and not (steps and steps[0].get("hub")):
                steps = [{"from": x["from"], "path": [], "ev": owner_ev}] + steps
            if route_possible(steps, r.seen if getattr(r, "seen", None) else (set(event_by_id_lower[owner_ev.lower()]["scripts"]) if owner_ev else set()) | {y["from"] for y in steps}):
                out.append(steps)
    return simplify_routes([r for r in out if any(y["path"] for y in r)])[:3]


def entry_conditions(script):
    """舊格式（由近到遠的步驟，每步列出可選的入口）：只有一條路線時逐步列；多條路線時合成一步「以下任一」。"""
    ev, _ = find_owner(script)
    # 最多取最短的 3 條，避免旗標、圖鑑的每個設定位置都帶一大串
    routes = [r for r in entry_routes(script, ev) if r][:3]
    if len(routes) == 1:
        return [{"into": x["into"], "options": [{"from": x["from"], "path": x["path"]}]} for x in reversed(routes[0])]
    if routes:
        return [{"into": script, "options": [{"from": r[0]["from"], "path": [label for x in r for label in x["path"]]} for r in routes]}]
    return []


heroines = []
for name, gi, lover, cg in HEROINES:
    heroines.append({
        "name": name,
        "meet": setters_with_owner(f"G1000{gi}") if gi is not None else [],
        "bond": setters_with_owner(f"G1100{gi}") if gi is not None else [],
        "bondFlag": f"G1100{gi}" if gi is not None else None,

        "ending": loc.get(f"Library/Desc/{cg}") if cg else None,
        "hidden": False,
    })
for h in heroines:
    for lst in (h["meet"], h["bond"]):
        for x in lst:
            used.add(x["s"])
            x["entry"] = entry_conditions(x["s"])

for setters in flag_setters.values():
    for x in setters[:12]:
        x["entry"] = entry_conditions(x["s"])


# ---------- 前置條件往前推 ----------
# 一個「單元」＝走到某支腳本某一行要經過的選項／條件；條件裡的旗標再往前找「誰把它設成需要的值」，遞迴下去。
# 暫存／戰鬥用的旗標（同一段劇情裡馬上設、馬上判斷）不往前追。
LOCAL_FLAG = re.compile(r"^(C\d|TC\d|A\d|B\d|Talk_Option|BattleResult|Prologue|ActionCheck)")
FLAG_COND = re.compile(r"旗標 ([A-Za-z0-9_]+)(?:（[^）]*）)? (=|≠|<|≤|>|≥) (-?\d+)")


def unit_steps(script, path):
    steps = [{"into": st["into"], "alts": [o["path"] for o in st["options"]], "froms": [o["from"] for o in st["options"]]}
             for st in reversed(entry_conditions(script))]
    if path:
        steps.append({"into": script, "alts": [path], "froms": [script]})
    return steps


def requirement(script, path, depth, seen):
    ev, _ = find_owner(script)
    event = next((e for e in events if e["id"] == ev), None)
    steps = unit_steps(script, path)
    unit = {
        "script": script,
        "ev": ev,
        "time": script_time.get(script) or (event["time"].get("from") if event and event.get("time") and event["time"].get("from") else None),
        "steps": steps,
        "eventConds": event["conds"] if event else [],
        "needs": [],
    }
    used.add(script)
    def flags_of(labels):
        return {m for label in labels for m in FLAG_COND.findall(re.sub(r"　〔前提不是：.*〕", "", re.sub(r"以上皆非（不是：.*）", "", label)))}
    texts = list(unit["eventConds"])
    for st in steps:
        if len(st["alts"]) == 1:
            texts.extend(st["alts"][0])
        else:
            common = set.intersection(*[flags_of(alt) for alt in st["alts"]]) if st["alts"] else set()
            texts.extend(f"旗標 {f} {op} {n}" for f, op, n in common)
    found = []
    for text in texts:
        # 「以上皆非（不是：…）」「〔前提不是：…〕」裡的條件是被排除的，不是需要達成的
        text = re.sub(r"以上皆非（不是：.*）", "", text)
        text = re.sub(r"　〔前提不是：.*〕", "", text)
        for f, op, n in FLAG_COND.findall(text):
            if LOCAL_FLAG.match(f) or (f, op, n) in found:
                continue
            found.append((f, op, n))
    for f, op, n in found:
        need = {"flag": f, "op": op, "val": int(n), "by": [], "adds": [], "changers": []}
        if op == "=" and int(n) == 0:
            # 需要 = 0 就是維持預設值：不往前追「誰設成 0」，改列出會把它改掉的地方
            for x in [x for x in flag_setters.get(f, []) if x.get("op") == "SetFlag" and x["v"] != 0][:6]:
                owner, _ = find_owner(x["s"])
                used.add(x["s"])
                need["changers"].append({"s": x["s"], "v": x["v"], "path": x["path"], "ev": owner, "time": script_time.get(x["s"])})
            need["default"] = True
        elif depth < 5 and f not in seen:
            for x in [x for x in flag_setters.get(f, []) if x.get("op") == "SetFlag" and satisfies(x["v"], op, int(n))][:3]:
                need["by"].append(requirement(x["s"], x["path"], depth + 1, seen | {f}))
        for x in ([] if need.get("default") else [x for x in flag_setters.get(f, []) if x.get("op") == "AddFlag"][:12]):
            owner, _ = find_owner(x["s"])
            used.add(x["s"])
            need["adds"].append({"s": x["s"], "v": x["v"], "path": x["path"], "ev": owner, "time": script_time.get(x["s"]),
                                 "steps": unit_steps(x["s"], [])})
        unit["needs"].append(need)
    return unit


for h in heroines:
    h["routes"] = [requirement(x["s"], x["path"], 0, {h["bondFlag"]}) for x in h["bond"] if x["v"] == 1 and x.get("op") == "SetFlag"]


def legend_containing(text):
    return next((v for k, v in loc.items() if k.startswith("LegendInfo/") and text in v), None)


# ---------- 旗標被哪些事件拿來判斷 ----------
FLAG_IN_TEXT = re.compile(r"旗標 ([A-Za-z0-9_]+)")
readers = collections.defaultdict(set)
for name, conds in script_cond_names.items():
    ev = find_owner(name)[0]
    if not ev:
        continue
    for c in conds:
        texts = switch_conditions(c) or [condition_text(c)]
        for t in texts:
            if t.startswith("以上皆非"):
                continue
            for f in FLAG_IN_TEXT.findall(t):
                readers[f].add(ev)
for e in events:
    for c in e["conds"]:
        for f in FLAG_IN_TEXT.findall(c):
            readers[f].add(e["id"])


# ---------- 無劇情事件：沒有傳說摘要、沒有選項／擲骰／戰鬥、也沒設定之後會被判斷的旗標 ----------
def has_story_branch(items):
    for it in items or []:
        if it["t"] == "branch":
            if it["kind"] in ("choice", "dice", "battle") or has_story_branch([x for b in it["branches"] for x in b["items"]]):
                return True
        if it["t"] in ("battle", "ending"):
            return True
    return False


def sets_used_flag(items, self_id):
    for it in items or []:
        if it["t"] == "flag" and not LOCAL_FLAG.match(it["f"]) and readers.get(it["f"], set()) - {self_id}:
            return True
        if it["t"] == "branch" and any(sets_used_flag(b["items"], self_id) for b in it["branches"]):
            return True
    return False


for e in events:
    infos = [script_info.get(sc) for sc in e["scripts"] if script_info.get(sc)]
    e["quiet"] = not e["hasLegend"] and not any(has_story_branch(i["items"]) for i in infos) \
        and not any(sets_used_flag(i["items"], e["id"]) for i in infos)

# ---------- 劇情地點：依背景圖與傳說中的地名打分數，少數人工指定 ----------
VIEW_PLACE = [
    (re.compile(r"^(section_001|forge2)"), "崆峒"),
    (re.compile(r"^(section_002|section_room1|section_006)"), "青城"),
    (re.compile(r"^section_100"), "錦香宮"),
    (re.compile(r"^snow_mountain"), "大雪山"),
    (re.compile(r"^(battlefield|boat2|bamboo_villa|center2|citygate|backyard1|ferry_day|banquet|champaign_night)"), "江陵／襄陽"),
    (re.compile(r"^(fortress|tang_|center|alchemy|room|study|kitchen|backmountain|martial|princess|cellar|forge|champaign)"), "唐門"),
    (re.compile(r"^(inn|teashop|mall1|outsideshop|paddy|temple_|house1)"), "唐門山下"),
]
WORD_PLACE = {"江陵": "江陵／襄陽", "襄陽": "江陵／襄陽", "南宮世家": "江陵／襄陽", "錦香宮": "武林大會・錦香宮",
              "武林大會": "武林大會・錦香宮", "雪山": "大雪山", "眉山": "唐門"}
PLACE_ORDER = ["唐門", "唐門山下", "崆峒", "青城", "江陵／襄陽", "武林大會・錦香宮", "大雪山", "旅途／其他"]
# 背景圖判斷不準的事件（逐一看過劇情開頭後指定）
PLACE_OVERRIDES = {
    "Main/M2006_01": "唐門", "Main/M2007_02": "唐門", "Main/M2008_02": "唐門", "Main/M7003_01": "唐門",
    "Main/M7001_01": "唐門", "M7001_02/M7001_02_01": "唐門", "M6003_07/M6003_07_01": "唐門", "S0604/S0604_01": "唐門",
    "Main/M2006_03": "崆峒", "S0014/S0014_01": "崆峒", "S2200/S2200_01": "崆峒", "S2310/S2310_01": "崆峒",
    "S3004/S3004_01": "青城",
    "Main/M2008_01": "江陵／襄陽", "S0208/S0208_01": "江陵／襄陽", "S0301/S0301_01": "江陵／襄陽",
    "S0302/S0302_01": "江陵／襄陽", "S0304/S0304_01": "江陵／襄陽", "S0305/S0305_01": "江陵／襄陽",
    "Main/M5001_04": "武林大會・錦香宮",
    "S2504/S2504_01": "大雪山",
    "S0213/S0213_01": "唐門山下", "S0801/S0801_01_01": "唐門山下",
    "S0303/S0303_01": "旅途／其他",
}


# 事件常是一長串劇情、會換好幾個地方：從開頭的腳本往後找，第一支有地點線索的就用它
def event_place(e):
    if e["id"] in PLACE_OVERRIDES:
        return PLACE_OVERRIDES[e["id"]]
    if e["pos"]:
        return "唐門"
    for sc in e["scripts"]:
        score = collections.Counter()
        for view, n in script_views.get(sc, {}).items():
            for pattern, place in VIEW_PLACE:
                if pattern.match(view):
                    score[place] += n
                    break
        if score:
            return score.most_common(1)[0][0]
    # 月會選項：背景圖分不出來就是在唐門開會
    if e.get("meetingOption"):
        return "唐門"
    # 背景圖都分不出來：才看傳說裡提到的地名（內文常順帶提到別處，所以放最後）
    score = collections.Counter()
    for sc in e["scripts"][:3]:
        info = script_info.get(sc)
        text = "".join(info["legend"]) if info else ""
        for word, place in WORD_PLACE.items():
            score[place] += text.count(word)
    # 每個地名都算過一次（次數 0 也在 Counter 裡），要看最高分是不是真的有出現
    best = score.most_common(1)
    return best[0][0] if best and best[0][1] > 0 else "旅途／其他"


for e in events:
    e["place"] = event_place(e)
EVENT_NOTES = {
    "S2902/S2902_01": "遊戲資料要求「剛好第3年5月下旬」，同時又要「目前時間 = 小竹回家結束那一旬」（小竹回家在崆峒留學期間）。"
                      "兩者不可能同時成立，第3年5月下旬也沒有行動，照目前版本應該觸發不了。",
}
for e in events:
    if e["id"] in EVENT_NOTES:
        e["note"] = EVENT_NOTES[e["id"]]

# ---------- 圖鑑：汗青書／結局 CG／死法 ----------
# 單一腳本的地點：看它自己的背景圖，分不出來就用所屬事件的地點
event_by_id = {e["id"]: e for e in events}


def script_place(sc, ev):
    score = collections.Counter()
    for view, n in script_views.get(sc, {}).items():
        for pattern, place in VIEW_PLACE:
            if pattern.match(view):
                score[place] += n
                break
    if score:
        return score.most_common(1)[0][0]
    return event_by_id[ev]["place"] if ev in event_by_id else None

lib_points = collections.defaultdict(list)


def index_lib(script, items, path):
    for it in items:
        if it["t"] in ("ending", "cg"):
            lib_points[it["id"]].append({"s": script, "path": path, "how": it["t"]})
        elif it["t"] == "scene" and it["s"] == "GameOver":
            lib_points[it["key"]].append({"s": script, "path": path, "how": "gameover"})
        elif it["t"] == "battle" and it.get("dead"):
            lib_points[it["dead"]].append({"s": script, "path": path, "how": "battle", "enemy": it.get("enemy", "")})
        elif it["t"] == "branch":
            for br in it["branches"]:
                index_lib(script, br["items"], path + [br["label"]])


for name, info in script_info.items():
    index_lib(name, info["items"], [])

lib_got = {}
if universe_path != "-" and os.path.exists(universe_path):
    uni = json.load(open(universe_path, encoding="utf-8"))
    for k in ("LibraryData1", "LibraryData2", "LibraryData4"):
        for x in uni.get(k) or []:
            lib_got[x["Name"]] = x["Count"]
LIB_KIND = {"1": "dead", "2": "end", "4": "cg"}
library = {}
for o in by_name["LibraryItemData"].values():
    lid = o["m_Name"]
    if lid[:1] not in LIB_KIND:
        continue
    points = []
    for x in lib_points.get(lid, []):
        ev, via = find_owner(x["s"])
        x = dict(x, ev=ev, entry=entry_conditions(x["s"]), place=script_place(x["s"], ev))
        if via and via != x["s"]:
            x["via"] = via
        used.add(x["s"])
        points.append(x)
    library[lid] = {"kind": LIB_KIND[lid[0]], "title": loc.get("Library/Title/" + lid) or o.get("_title", ""),
                    "desc": loc.get("Library/Desc/" + lid) or o.get("_desc", ""), "got": lib_got.get(lid, 0), "points": points}
for name, gi, lover, cg in HEROINES:
    if cg in library:
        library[cg]["title"] = f"{name}結緣結局"
# 汗青書、死法的達成方式改看 smilin.net wiki：網頁只留結緣結局（腳本仍照樣收進來）
library = {lid: item for lid, item in library.items() if item["kind"] == "cg"}
for e in events:
    e["libs"] = sorted({lid for lid, item in library.items() for x in item["points"] if x["ev"] == e["id"]})

# ---------- 唐門各地點的隨機事件 ----------
# 地點腳本用 checkpointmanager.Position(組名) 依權重抽一個結果腳本（組的前綴 + "_" + 代碼）。
# 有兩層的地點（後山、鍛冶場、大門、外堡）先抽「有沒有人插進來」，再抽行動結果。
# 第 5 欄是選單上這個行動出現的條件（例如鍛冶場「雜匠」要小竹在唐門）。
POSITION_GROUPS = [
    ("唐門", "正心堂", "incense", ["Mall_Work_001"]),
    ("唐門", "正心堂", "meditate", ["Mall_Free_001"]),
    ("唐門", "校場", "sweep", ["Center_Work_001"]),
    ("唐門", "校場", "practice", ["Center_Free_001"]),
    ("唐門", "煉丹房", "alchemy", ["Alchemy_Work_001"]),
    ("唐門", "鍛冶場", "forge", ["Forge_01", "Forge_Work_001"]),
    ("唐門", "鍛冶場", "craft2", ["Craft_Work_001"], "E12004_01"),
    ("唐門", "後山", "pickwood", ["Back_02", "Back_Work_001"]),
    ("唐門", "後山", "training", ["Back_03", "Back_Free_001"]),
    ("唐門", "弟子房", "transaction", ["Room_Work_001"]),
    ("唐門", "講經堂", "book", ["Study_Work_001"]),
    ("唐門", "伙房", "cook", ["Kitchen_Work_001"]),
    ("唐門", "女弟子房", "voyeur", ["GirlRoom_Work_001"], "GirlRoom_Work_001"),
    ("唐門", "女弟子房", "origami", ["GirlRoom_Free_001"], "GirlRoom_Free_001"),
    ("唐門", "大門", "（經過大門時）", ["Door_02"]),
    ("唐門", "大門", "O_Door_001_005", ["Door_Work_001"]),
    ("唐門山下", "鎮上", "walk", ["Door_Free_001"]),
    ("唐門山下", "外堡", "housekeeper", ["Fortress_02", "Fortress_Work_001"]),
    ("唐門山下", "茶館", "teashop", ["Teashop_Work_001"]),
    ("唐門山下", "藥鋪", "doctor", ["Pharmacy_Work_001"]),
    ("唐門山下", "溫泉", "spa", ["Spa_Free_001"]),
    ("唐門山下", "農田", "farm", ["Farm_Work_001"]),
    ("唐門山下", "破廟時期（不留學，第2年6～8月）", "釣魚", ["Fish_01"]),
    ("唐門山下", "破廟時期（不留學，第2年6～8月）", "散步", ["Walk_01"]),
    ("唐門山下", "破廟時期（不留學，第2年6～8月）", "賭場", ["Casino_01"]),
    ("崆峒（留學）", "窩居", "（進入時）", ["Section_01_00"]),
    ("崆峒（留學）", "飛天殿", "immortal", ["Section_01_01"]),
    ("崆峒（留學）", "小梅找你跑步（飛天門修練、鐵拳門打鐵時）", "O_Section_01_Free_01_01_003", ["Section_01_07", "Section_01_07_01"]),
    ("崆峒（留學）", "小梅找你跑步（飛天門修練、鐵拳門打鐵時）", "O_Section_01_Free_01_01_004", ["Section_01_07_02", "Section_01_07_02_502"]),
    ("崆峒（留學）", "奪魄森林", "（進入時）", ["Section_01_02_Start"]),
    ("崆峒（留學）", "奪魄森林", "training3", ["Section_01_02"]),
    ("崆峒（留學）", "鐵拳巷", "forge2", ["Section_01_03"]),
    ("崆峒（留學）", "鐵拳巷", "craft1", ["Craft_Work_001"]),
    ("崆峒（留學）", "玄功洞", "write", ["Section_01_04"]),
    ("崆峒（留學）", "無色廣場", "walk", ["Section_01_06_01"]),
    ("崆峒（留學）", "無色廣場", "casino", ["Section_01_06_02", "Section_01_06_02_01"]),
    ("崆峒（留學）", "奪魄峰", "chess", ["Chess_01", "Chess_02", "Chess_03"]),
    ("崆峒（留學）", "鶴崖", "（鶴崖事件中）", ["Section_01_08_06"]),
    ("崆峒（留學）", "鎮魂獄（坐牢期間）", "坐牢", ["S2800_02_Break_01"]),
    ("青城（留學）", "飲食", "（進入時）", ["Section_02_00"]),
    ("青城（留學）", "常風觀", "training4", ["Section_02_01_01"]),
    ("青城（留學）", "常風觀", "walk2", ["Section_02_01_02"]),
    ("青城（留學）", "上清宮", "cultivate", ["Section_02_02_01"]),
    ("青城（留學）", "上清宮", "out1", ["Section_02_02_02"]),
    ("青城（留學）", "青城山鎮", "walk", ["Section_02_03_01"]),
    ("青城（留學）", "青城山鎮", "forge3", ["Section_02_03_02"]),
    ("青城（留學）", "青城山鎮", "doctor2", ["Section_02_03_03"]),
    ("青城（留學）", "祖師壽誕（第2年11月下旬）", "（考較期間）", ["Ch_3_1_7_2_01"]),
    ("江陵／襄陽", "南宮世家（第2年9月）", "上街消遣", ["Ch_3_6_1_01"]),
    ("江陵／襄陽", "襄陽（與小梅同行）", "閒逛", ["S2321_04_03_02", "S2321_04_03_03"]),
    ("武林大會・錦香宮", "錦香宮", "華音閣（聽曲）", ["Ch_6_4_3_2_01"]),
    ("大雪山", "雪山", "修練武功", ["Travel_S2503_01"]),
    ("旅途（移動途中）", "大師兄找譚霸刀（第1年10月）", "途中", ["Travel_001"]),
    ("旅途（移動途中）", "前往南宮壽宴（第1年11月）", "途中", ["Travel_002"]),
    ("旅途（移動途中）", "第2年8月出行", "途中", ["Travel_302"]),
    ("旅途（移動途中）", "江陵回唐門（第2年10月）", "途中", ["Travel_310"]),
    ("旅途（移動途中）", "陪大師兄下山（第3年1月）", "途中", ["Travel_401"]),
    ("旅途（移動途中）", "前往崆峒（第3年5月）", "途中", ["Travel_501"]),
    ("旅途（移動途中）", "前往武林大會（第3年9月）", "途中", ["Travel_601_01", "Travel_601_02"]),
    ("旅途（移動途中）", "雪山行（第3年6月）", "途中", ["Travel_S2501_01"]),
    ("旅途（移動途中）", "小竹回家", "去程", ["Travel_S2901_02"]),
    ("旅途（移動途中）", "小竹回家", "回程", ["Travel_S2901_05"]),
]
char_names = {o["Value"]: o["Key"] for o in by_name.get("StoryMappingItem", {}).values() if not o["m_Name"].startswith("P_")}
# 出場的人：說話者、立繪（characters.Get），再加上傳說、台詞裡提到的名字（只有旁白、插圖的結果，例如跑步）。
# 文字裡只認有好感度的角色名（和女主角的小名），一般字詞（「被抓」這類角色標籤）不算
LEGEND_NAMES = sorted({re.sub(r"_.*$", "", n) for n in parse_enum_strings("RelationshipStatType") if n != "主角"}
                      | {"小梅", "小竹", "小蘭", "小菊"}, key=len, reverse=True)


def block_legend(block, out):
    for it in block:
        if it["t"] == "story":
            t = loc.get("LegendInfo/" + it["k"])
            if t:
                out.append(t)
        elif it["t"] == "if":
            for br in it["branches"]:
                block_legend(br["block"], out)
    return out


def legend_names(text):
    found = set()
    for n in LEGEND_NAMES:
        if n in text:
            found.add(n)
            text = text.replace(n, "")
    return found


for key, (block, _) in scripts.items():
    script_chars[key] = script_chars.get(key, set()) | legend_names("".join(block_legend(block, [])))
# 兒時立繪（回憶場景裡的小梅、小竹、小蘭、雲裳）不算本人出場
CHILD_FORM = re.compile(r"幼年|^小小梅手$")
GENERIC_CHAR = re.compile(r"^(弟子|女弟子|武師|店小二|路人|村民|官兵|捕快|乞丐|特殊|鄉民|小販)\d*$")


def block_text_keys(block, out):
    for it in block:
        if it["t"] == "text":
            out.append(it["k"])
        elif it["t"] == "if":
            for br in it["branches"]:
                block_text_keys(br["block"], out)
    return out


def result_chars(script):
    """地點事件的出場角色：說話者、立繪、傳說，再加上台詞／旁白裡提到的名字（跑步這類只有旁白的結果）"""
    seen, todo, out = {script}, [script], set()
    while todo:
        sc = todo.pop()
        out |= script_chars.get(sc, set())
        if sc in scripts:
            out |= legend_names("".join(story_text(k) or "" for k in block_text_keys(scripts[sc][0], [])))
        for n in next_scripts(sc):
            if n.startswith(script) and n not in seen:
                seen.add(n)
                todo.append(n)
    names = sorted({char_names.get(c, c) for c in out})
    return [n for n in names if not GENERIC_CHAR.match(n) and not CHILD_FORM.search(n)]


def action_title(key):
    return loc.get("Position/title/" + key) or story_text(key) or key


positions = []
pos_chain_label = {}
# 腳本 → 它設成 1 的旗標
sets_one_by_script = collections.defaultdict(set)
for f, setters in flag_setters.items():
    for x in setters:
        if x["v"] == 1 and x["op"] == "SetFlag":
            sets_one_by_script[x["s"]].add(f)
for area, place, action, groups, *option in POSITION_GROUPS:
    layers = []
    for gname in groups:
        grp = by_name["PositionResultData"].get(gname)
        if not grp:
            continue
        cands = []
        for ref in grp["_list"]:
            o = deref(ref)
            if not o:
                continue
            m = deref(o.get("_config"))
            code = m["Value"] if m else "?"
            script = f"{grp['_scriptPrefix']}_{code}".lower()
            info = script_info.get(script)
            if info:
                used.add(script)
            # 結果腳本常常沒有台詞、只是接到另一支（例如 door_02_501 → door_girl_03_01）：
            # 已讀、標題、出場角色看接下去第一支有台詞的；接下去設成 1 的旗標若也是出現條件（= 0），就是只會發生一次
            chain = trace_chain(script, None) if info else []
            content = next((sc for sc in chain if script_info[sc]["lines"]), script)
            cinfo = script_info.get(content)
            cond = cond_item_text(o["_activeCondition"]) if o.get("_toggleCondition") else ""
            sets_one = set().union(*(sets_one_by_script.get(sc, set()) for sc in chain))
            once = next((f for f in re.findall(r"旗標 ([A-Za-z0-9_]+) = 0", cond) if f in sets_one), None)
            for sc in chain:
                pos_chain_label.setdefault(sc, (place, (o.get("_devNote") or "").strip() or action_title(action)))
            cands.append({
                "id": o["m_Name"], "code": code, "script": script, "note": (o.get("_devNote") or "").strip(),
                "cond": cond, "once": once,
                "rate": o.get("_defaultRate", 0),
                "bonus": [{"cond": cond_item_text(r["_condition"]), "rate": r["_rate"]} for r in o.get("_eventRateItem", [])],
                "chars": sorted(set(result_chars(script)) | set(result_chars(content))), "read": cinfo["read"] if cinfo else None, "rs": content,
                "title": first_line(content) or (re.sub(r"<[^>]+>|\{[^}]*\}", "", loc.get("Story/" + script_first_say[content], "")).replace("\n", "")
                                                 if script_first_say.get(content) else ""),
            })
        layers.append({"group": gname, "candidates": cands})
    need = condition_text(option[0]).strip("（）") if option else ""
    positions.append({"area": area, "place": place, "action": action_title(action), "need": need, "layers": layers})

# 不屬於任務事件、在地點事件裡設的旗標：標上是哪個地點的哪個事件，網頁才寫得出「在哪裡」
# 地點選單之外接進來的（例如藥鋪坐診的病人 pharmacy_work_402）：用同名前綴的地點動作
pos_prefix = {}
for pos in positions:
    for ly in pos["layers"]:
        for c in ly["candidates"]:
            pos_prefix.setdefault(re.sub(r"(_\d+)+$", "", c["script"]), (pos["place"], pos["action"]))
for setters in flag_setters.values():
    for x in setters:
        if "ev" not in x and x["s"] in pos_chain_label:
            x["pos"] = "・".join(pos_chain_label[x["s"]])
        elif "ev" not in x and re.sub(r"(_\d+)+$", "", x["s"]) in pos_prefix:
            x["pos"] = "・".join(pos_prefix[re.sub(r"(_\d+)+$", "", x["s"])])

# ---------- 五塊錢：有台詞但還沒讀完的場景，以及沒讀到的原因 ----------
# 只因性格／技能而換台詞的分歧（走向相同）算「差分」：看過其中一個版本就算讀過
IGNORE_STAT = re.compile(r"^(性情|道德|處世|修養|學問|嘴力|心相|陰陽|內力|體力|廚藝|輕功|變心|全武學點數|全毒藥點數|全鍛造點數|天賦·.*)$")
ATOM_LHS = re.compile(r"^(.*?) (=|≠|<|≤|>|≥) (.*)$")
HEROINE_NAMES = [v for k, v in loc.items() if k.startswith("PlayerInfo/Lover/") and v != "自己"]
NICKNAMES = {"小竹": "郁竹", "小梅": "虞小梅", "小蘭": "夏侯蘭", "小菊": "魏菊"}


def is_variant(kind, labels, block):
    if kind not in ("switch", "cond") or len({outcome_sig(br["block"]) for br in block["branches"]}) != 1:
        return False
    seen = False
    for label, _ in labels:
        label = re.sub(r"^(符合|不符合)：", "", re.sub(r"　〔(前提不是|需)：.*〕$", "", label))
        if label.startswith("以上皆非") or label == "其他":
            continue
        for a in re.split(r" 且 | 或 ", label):
            m = ATOM_LHS.match(a.strip().strip("（）"))
            if not m or not IGNORE_STAT.match(m.group(1)):
                return False
            seen = True
    return seen


def branch_texts(it, vars_):
    kind, name, labels, _ = resolve_if(it, vars_)
    out = []
    # 選項文字不算（遊戲不記選項的已讀）；遊戲裡不會出現的選項（條件不存在）也不算
    for br, (label, key) in zip(it["branches"], labels):
        if not never_shown(label):
            out.append((label, eff_texts(br["block"], vars_), br))
    return kind, labels, out


def best_branch(branches):
    return max(branches, key=lambda b: (read_ratio(b[1]) or 0, -len(b[1])))


def text_tree(block, vars_):
    """台詞樹：k 是一定要讀的台詞（劇情分支全部算），g 是差分組，每組是幾個版本（各自又是一棵樹）"""
    node = {"k": [], "g": []}
    for it in block:
        if it["t"] == "text":
            node["k"].append(it["k"])
        elif it["t"] == "if":
            kind, labels, branches = branch_texts(it, vars_)
            subs = [text_tree(br["block"], vars_) for _, _, br in branches]
            if is_variant(kind, labels, it):
                subs = [x for x in subs if x["k"] or x["g"]]
                if subs:
                    node["g"].append(subs)
            else:
                for x in subs:
                    node["k"] += x["k"]
                    node["g"] += x["g"]
    return node


def tree_keys(node, all_variants, read):
    """不列入差分：每組取讀得最多的版本；列入差分：每個版本都算"""
    keys = list(node["k"])
    for group in node["g"]:
        if all_variants:
            for alt in group:
                keys += tree_keys(alt, True, read)
        else:
            alts = [tree_keys(alt, False, read) for alt in group]
            keys += max(alts, key=lambda ks: (sum(k in read for k in set(ks)) / len(set(ks)) if ks else 0, -len(set(ks))))
    return keys


def tree_strip(node, kp):
    return {"k": [k[len(kp):] for k in dict.fromkeys(node["k"])], **({"g": [[tree_strip(a, kp) for a in grp] for grp in node["g"]]} if node["g"] else {})}


def tree_all(node):
    out = list(node["k"])
    for grp in node["g"]:
        for a in grp:
            out += tree_all(a)
    return out


def eff_texts(block, vars_):
    texts = []
    for it in block:
        if it["t"] == "text":
            texts.append(it["k"])
        elif it["t"] == "if":
            kind, labels, branches = branch_texts(it, vars_)
            if is_variant(kind, labels, it):
                texts.extend(best_branch(branches)[1])
            else:
                for _, t, _ in branches:
                    texts.extend(t)
    return texts


LOVER_NAMES = {k[len("PlayerInfo/Lover/"):]: v for k, v in loc.items() if k.startswith("PlayerInfo/Lover/")}
FLAG_NOTE = {o["m_Name"]: (o.get("_devNote") or "") for o in by_name["FlagData"].values()}


def heroine_of(name):
    for nick, full in NICKNAMES.items():
        if nick in name:
            name = name.replace(nick, full)
    return [h for h in HEROINE_NAMES if h in name]


# 地點本身就寫明是誰的（「小梅找你跑步」）：底下每個結果都算她（有些結果的旁白沒提到名字）
for p in positions:
    p["who"] = heroine_of(p["place"] + p["action"])


def block_heroines(block, out):
    for it in block:
        if it["t"] == "char":
            n = char_names.get(it["c"], it["c"])
            if not CHILD_FORM.search(n):
                out.update(heroine_of(n))
        elif it["t"] == "story" and loc.get("LegendInfo/" + it["k"]):
            for n in legend_names(loc["LegendInfo/" + it["k"]]):
                out.update(heroine_of(n))
        elif it["t"] == "if":
            for br in it["branches"]:
                block_heroines(br["block"], out)
    return out


def unread_reasons(block, vars_, path, out, variant=False):
    for it in block:
        if it["t"] != "if":
            continue
        kind, labels, branches = branch_texts(it, vars_)
        if is_variant(kind, labels, it):
            # 差分：讀得最多的版本照常往下找；其他版本標成差分（網頁勾「列入差分」才顯示）
            best = best_branch(branches)
            unread_reasons(best[2]["block"], vars_, path, out, variant)
            for label, t, br in branches:
                if br is best[2]:
                    continue
                r = read_ratio(tree_all(text_tree(br["block"], vars_)))
                if r == 0:
                    who = block_heroines(br["block"], set())
                    out.append({"kind": "variant", "label": label, "path": path[-3:], "lines": len(set(t)), "heroines": sorted(who), "variant": True})
                elif r is not None and r < 1:
                    unread_reasons(br["block"], vars_, path + [label], out, True)
            continue
        for label, t, br in branches:
            if re.match(r"^(exit\+|~x)", label):
                continue
            r = read_ratio(t)
            if r is None:
                continue
            if r == 0:
                # 地點選單的「行動+work」標籤換成行動名稱（挑柴、掌廚…）
                m = re.match(r"^([a-z0-9]+)\+(work|free)", label)
                if m:
                    label = loc.get("Position/title/" + m.group(1), label)
                who = block_heroines(br["block"], set())
                out.append({"kind": kind, "label": label, "path": path[-3:], "lines": len(set(t)), "heroines": sorted(who), **({"variant": True} if variant else {})})
            elif r < 1:
                unread_reasons(br["block"], vars_, path + [label], out, variant)


def heroines_in(script):
    names = set()
    for c in script_chars.get(script, ()):
        n = char_names.get(c, c)
        if CHILD_FORM.search(n):
            continue
        for nick, full in NICKNAMES.items():
            if nick in n:
                n = full
        for h in HEROINE_NAMES:
            if h in n:
                names.add(h)
    return sorted(names)


unread = []
if read_keys:
    for name, (block, vars_) in scripts.items():
        CURRENT[0] = name
        tree = text_tree(block, vars_)
        texts = tree_keys(tree, False, read_keys)
        r = read_ratio(texts)
        r_all = read_ratio(tree_all(tree))
        if name in script_info and r is not None:
            # 流程圖的已讀度也用「差分看一種就算」；列入差分時網頁改用 readAll
            script_info[name]["read"] = r
            if r_all != r:
                script_info[name]["readAll"] = r_all
        if r is None or r_all >= 1:
            continue
        ev, _ = find_owner(name)
        # 台詞鍵（去掉共同前綴）：網頁連上遊戲時用遊戲目前的已讀紀錄即時重算
        uniq = list(dict.fromkeys(tree_all(tree)))
        kp = os.path.commonprefix(uniq)
        item = {"s": name, "ev": ev, "read": r, "readAll": r_all, "lines": len(set(texts)), "linesAll": len(uniq), "heroines": heroines_in(name),
                "kp": kp, "kt": tree_strip(tree, kp),
                "place": script_place(name, ev), "title": first_line(name) or (
                    re.sub(r"<[^>]+>|\{[^}]*\}", "", loc.get("Story/" + script_first_say[name], "")).replace("\n", "") if script_first_say.get(name) else "")}
        if r == 0:
            routes = entry_routes(name, ev)
            # 網頁只列 3 條，其餘只記有沒有
            item["routes"] = [[{k: v for k, v in x.items() if k != "into"} for x in r] for r in routes[:3]]
            item["moreRoutes"] = len(routes) > 3
            hubs = {(r[0].get("hub"), r[0]["path"][0]) for r in routes if r and r[0].get("hub")}
            if hubs and all(r and r[0].get("hub") for r in routes) and len(hubs) == 1:
                hub, place = next(iter(hubs))
                item["hubGroup"] = f"{hub}・{place}"
        else:
            reasons = []
            unread_reasons(block, vars_, [], reasons)
            item["reasons"] = reasons[:12]
        unread.append(item)

for pos in positions:
    for ly in pos["layers"]:
        for c in ly["candidates"]:
            info = script_info.get(c["rs"])
            if info:
                c["read"] = info["read"]
                if "readAll" in info:
                    c["readAll"] = info["readAll"]

for e in events:
    act = event_activate(e)
    if act:
        e["activate"] = act
    via = event_via(e)
    if via:
        e["via"] = via
        # 任務檢查點停用、實際由養成行動等接進來的事件：時間改用觸發路線裡的時間條件
        if not e["active"]:
            los, his = [], []
            for r in via:
                lo = hi = None
                for x in r:
                    for label in x.get("path", []):
                        for op, y, m, st in NOW_COND.findall(re.sub(r"　〔前提不是：.*〕$", "", label)):
                            t = (int(y), int(m), "上中下".index(st) + 1)
                            if op in ("=", "≥", ">"):
                                lo = t if not lo or t > lo else lo
                            if op in ("=", "≤", "<"):
                                hi = t if not hi or t < hi else hi
                los.append(lo)
                his.append(hi)
            if los and all(los):
                lo = min(los)
                hi = max(his) if all(his) else None
                tt = lambda t: {"y": t[0], "m": t[1], "s": t[2]}
                e["time"] = {"type": "at", "from": tt(lo)} if hi == lo else                     {"type": "range", "from": tt(lo), "to": tt(hi)} if hi else {"type": "range", "from": tt(lo), "to": {"y": 4, "m": 3, "s": 3}, "open": True}

# ---------- 限定路線 ----------
# 劇情分岔的旗標（開發備註逐行寫了各數值的意思）：事件要求其中一個值，就是限定那條路線。
# 會往上繼承：啟動／觸發它的劇情、它需要的旗標在哪個事件裡設，那些事件限定的路線它也一樣。
ROUTE_FLAG_NAMES = ["M20008", "M20011", "M20028", "M40036", "M60016", "M70015"]
ROUTE_PREFIX = {"M20008": "留學：", "M20011": "崆峒門派：", "M20028": "離家出走：", "M40036": "臥雲崗：",
                "M60016": "武林大會：", "M70015": "決策："}
ROUTE_VALUES = {}
for _f in ROUTE_FLAG_NAMES:
    _vals = {}
    for _line in (FLAG_NOTE.get(_f) or "").replace("\r", "").split("\n")[1:]:
        _m = re.match(r"^\s*(\d+)\s*[.:：、]?\s*(.+)$", _line)
        if _m:
            _vals[int(_m.group(1))] = ROUTE_PREFIX[_f] + _m.group(2).strip()
    ROUTE_VALUES[_f] = _vals
ROUTE_VALUES["M70015"][2] = "決策：戰他娘親（頑抗路線）"
ROUTE_VALUES["M70052"] = {1: "決策：戰他娘親（頑抗路線）"}
HUB_ROUTE = {"崆峒留學期間": "留學：崆峒", "青城留學期間": "留學：青城"}
ROUTE_ATOM = re.compile(r"旗標 (" + "|".join(ROUTE_VALUES) + r")(?:（[^）]*）)? = (\d+)")


def route_atoms(text):
    """文字裡「旗標 路線旗標 = 值」的路線名稱（被排除的「以上皆非（不是：…）」「前提不是」不算）"""
    text = re.sub(r"以上皆非（不是：.*?）|　〔前提不是：.*〕", "", text)
    return {ROUTE_VALUES[f][int(v)] for f, v in ROUTE_ATOM.findall(text) if int(v) in ROUTE_VALUES[f]}


_route_memo = {}


def event_routes(e, depth=0):
    """事件限定的路線（集合）。多個入口時取共同的部分。"""
    key = e["id"]
    if key in _route_memo:
        return _route_memo[key]
    _route_memo[key] = set()          # 先占位，避免互相引用時無限遞迴
    tags = set()
    for c in e["conds"]:
        tags |= route_atoms(c)
    if depth < 4:
        def route_tags(r):
            out = set()
            for x in r:
                if x.get("hub") in HUB_ROUTE:
                    out.add(HUB_ROUTE[x["hub"]])
                if x.get("ev") and event_by_id_lower.get(x["ev"].lower()):
                    out |= event_routes(event_by_id_lower[x["ev"].lower()], depth + 1)
                for label in x.get("path", []):
                    out |= route_atoms(label)
            return out
        for routes in (e.get("activate"), e.get("via")):
            if routes:
                tags |= set.intersection(*[route_tags(r) for r in routes])
        # 條件要的旗標（不是路線旗標本身）：所有符合的設定點都在某條路線上，就繼承
        for f, op, v in re.findall(r"旗標 ([A-Za-z0-9_]+)(?:（[^）]*）)? (=|≥|>) (\d+)", " ".join(e["conds"])):
            if f in ROUTE_VALUES or (op == "=" and v == "0"):
                continue
            sets = []
            for x in flag_setters.get(f, []):
                if x.get("op") != "SetFlag" or not satisfies(x["v"], op, int(v)):
                    continue
                owner = event_by_id_lower.get((x.get("ev") or "").lower())
                t = set().union(*[route_atoms(label) for label in x["path"]]) if x["path"] else set()
                if owner and owner["id"] != e["id"]:
                    t |= event_routes(owner, depth + 1)
                sets.append(t)
            if sets:
                tags |= set.intersection(*sets)
    _route_memo[key] = tags
    return tags


for e in events:
    r = event_routes(e)
    if r:
        e["routeOnly"] = sorted(r)

# 每支腳本最短的進入路線（只留最後幾個標籤）：網頁把「一進這段就設的暫存旗標」翻成是哪個選項接過來的
script_via = {}
for name in script_info:
    ev, _ = find_owner(name)
    if not ev:
        continue
    r = next(iter(entry_routes(name, ev)), [])
    labels = [label for x in r for label in x["path"]]
    if labels:
        script_via[name] = labels[-4:]

# 其他目標條件（不是結緣的結局分歧）
TARGETS = [
    {"name": "葉雲裳（不結緣・存活）", "flag": "M40055", "val": 1,
     "note": "結局時（ch8_6_3_2、ch8_1_2）看 M40055 = 1：唐芳贈殭屍散、北上求醫成功；沒有的話雲裳在途中病逝。"
             "白話：第3年1月上旬的支線裡，擲骰（1～50 + 好感·葉雲裳）≥ 80 進「葉雲裳的抵抗」→ 選「勸葉雲舟留」"
             "→ 對話選單先問「雲裳的傷情」，再選「治療方法」；而且之前沒去青城留學（M20008 ≠ 1）。"
             "選「勸葉雲裳走」或擲骰 < 80 會直接讓她離開，拿不到殭屍散。",
     "ending": legend_containing("受惠於唐芳所贈殭屍散")},
    {"name": "大師兄存活（醫術治好）", "flag": "M40034", "val": 1,
     "note": "第3年1月下旬大師兄重傷：醫術天賦 ≥ 5 或全毒藥點數 ≥ 250 才能用「自己的醫術方案」→ 選「決意」運功療傷；"
             "療傷時依內功等判定累加治療進度 M40033，≥ 2 時設 M40034 = 1（大師兄當下仍會離開，但之後的劇情會看這個旗標）。",
     "ending": None},
    {"name": "遇到南溪", "flag": "M60075", "val": 1,
     "note": "第3年10月中旬武林大會期間的客棧：先選「叫一桶水洗澡」，再選「下樓喝酒」；"
             "此時要葉雲裳已結緣（G11002 = 1）且 E12100 = 1（而且 M60083 不是 1），才會進到遇見南溪的劇情（M60075 = 1）。"
             "若當下處世 ≤ 40 且修養 ≥ 60 會設為 2，結局段落有些內容要 M60075 ≥ 2。",
     "ending": None},
    {"name": "唐大鯨加入唐門", "flag": "E13002", "val": 1,
     "note": "先完成支線「乞丐與和尚」（E20004 = 1）→ 第1年9月中旬～第2年4月下旬到「大門」觸發 → 擲骰後的三個選項："
             "「我還是先不插手」、「惡霸，我來接你的招！」（和許大鯨打一場，輸贏都行）都會讓他加入；"
             "「竟敢得罪我唐門的好朋友，和尚看拳！」（和福韞打）要打輸才會加入，打贏就不會。",
     "ending": None},
    {"name": "唐嬌嬌加入唐門", "flag": "E13003", "val": 1,
     "note": "留在唐門（不去留學、主角在唐門）且練武場的掃除／團練做過 2 次以上 → 第2年5月自動觸發 → 選「我就偏不信，上前領教」"
             "→ 和狄傲決鬥打贏 → 不要選「好，成親吧」，選另外兩個（「那我就安心了，妳總不能看上我」「妳擦亮眼看看我！」）。"
             "第4年1月「峨嵋回音」的某些分支會讓她離開。",
     "ending": None},
    # brief：只列條件和步驟，不附自動產生的詳細追溯
    {"name": "孟仙謠投奔、到崆峒", "flag": "M60091", "val": 1, "brief": True,
     "conds": [{"t": "走小梅線：崆峒辭行時選「執意不受」，成為崆峒掌派人", "c": "flag:M60015=1"},
               {"t": "小梅同行武林大會：第3年8月中旬～下旬到「伙房」邀請（劇情對話像是一定同行，但沒去邀請就不算）", "c": "flag:M60004=1"},
               {"t": "瑞笙好感 ≥ 30", "c": "rel:special999>=30"},
               {"t": "孟仙謠好感 ≥ 2（第2年10月下旬和小梅同行襄陽時累積）", "c": "flag:H04003>=2"}],
     "steps": ["第3年10月武林大會（錦香宮）期間，在「武林交際」裡選「動心忍性」",
               "選單出現「拜會孤雲山派」，去拜會",
               {"t": "擲骰 ≥ 80 選「靠山來了！（投奔）」（沒投奔的話，下一步聽不到抱怨，最後也不會請求收容）", "c": "flag:M60083=1"},
               {"t": "客棧先「叫一桶水洗澡」，再「下樓喝酒」（聽到孟仙謠的抱怨；收容請求要有這一步）", "c": "flag:M60088=1"},
               "大會結束時孟仙謠請求收容，選「點頭答應收容」（選「我拒絕」會變成小梅賭氣）"],
     "ending": None},
    {"name": "崆峒探險隊成立", "flag": "E22000", "val": 1, "brief": True,
     "conds": [{"t": "認識小梅，小梅好感 ≥ 20（第2年3月中旬「小梅邀請」認識）", "c": "flag:G10004=1&rel:girl5>=20"},
               {"t": "認識瑞笙，瑞笙好感 ≥ 10（留學期間：「小梅邀請」那場戰鬥撐到第 8 回合以上打贏；不留學的話第2年3月上旬「南宮來客」）",
                "c": "flag:G30000=1&rel:special999>=10"},
               {"t": "認識南宮淺，南宮淺好感 ≥ 10（第1年10月「譚霸刀」選「上前幫忙南宮淺」或「出聲責問家丁尊卑不分」；或第2年3月下旬飛天門「拜碼頭」、鐵拳門「不速之客」）",
                "c": "flag:G30015=1&rel:special103>=10"}],
     "steps": ["第2年4月上旬～5月上旬（崆峒留學期間），條件都符合時自動觸發",
               "成立後養成選單會出現「崆峒探險隊的活動時間到了」"],
     "ending": None},
    {"name": "開啟養成地點：鶴崖（崆峒）", "flag": "M00030", "val": 1, "brief": True,
     "conds": [{"t": "崆峒留學", "c": "flag:M20008=2"},
               {"t": "加入飛天門", "c": "flag:M20011=1"},
               "沒開的話照遊戲資料也能去：身上帶著睡丹、還剩 2 次以上行動（睡丹藥方在加入玄功門、奪魄門時取得，崆峒探險隊、四師兄那邊也有）。"
               "※ 玩家回報：實際上無法達成"],
     "steps": ["第2年3月下旬到「飛天殿」修練，觸發「拜碼頭」",
               "和顏疆打一場（輸贏都會往下接）",
               "擲骰逃脫：一般 ≥ 60；若讓南宮淺一起參戰（曾在南宮家宴為她出頭、擲骰 ≥ 50 選「看不下去」）要 ≥ 70 → 成功就在鶴崖會合並開啟",
               "逃脫失敗會入獄：瑞笙參戰（南宮淺那條，或瑞笙好感 ≥ 7）的話，之後小梅劫獄時選「乖」也會開啟",
               "開啟後一直開著，第2年7月鶴崖事件結束時關閉"],
     "ending": None},
    {"name": "開啟養成地點：奪魄森林（崆峒）", "flag": "S0014_02", "val": 1,
     "note": "崆峒留學期間養成選單的「奪魄森林」：拜夏侯蘭為師（S0014_02 = 1）後才會出現。",
     "ending": None},
]
for t in TARGETS:
    t["routes"] = [requirement(x["s"], x["path"], 0, {t["flag"]}) for x in flag_setters.get(t["flag"], [])
                   if x.get("op") == "SetFlag" and x["v"] == t["val"]]

# 沒有設時間的事件（例如到某地點就觸發）：觸發條件要的旗標最早什麼時候才會被設定，就從那時起
TKEY = lambda t: (t["y"], t["m"], t["s"])
# 一段劇情可能同時算在好幾個事件裡（例如經由留學養成選單）：名稱和事件編號相同的（s2900_03 ↔ S2900）最準，其次是所屬事件
script_starts = {}
for e in events:
    t = (e["time"] or {}).get("from")
    if t and t.get("y", 0) >= 1:
        for sc in e["scripts"]:
            if sc.startswith(e["mission"].lower() + "_") or sc not in script_starts:
                if sc.startswith(e["mission"].lower() + "_") or (find_owner(sc)[0] or "").lower() == e["id"].lower():
                    script_starts[sc] = t
for e in events:
    if e["time"]:
        continue
    ts = []
    for f, op, v in re.findall(r"旗標 ([A-Za-z0-9_]+)(?:（[^）]*）)? (=|≥|>) (\d+)", " ".join(e["conds"])):
        v = int(v)
        if op == "=" and v == 0:
            continue
        for x in flag_setters.get(f, []):
            if x.get("op") != "SetFlag" or not satisfies(x["v"], op, v):
                continue
            # 設定點所在事件的開始時間（腳本推算時間取的是最晚的那條路徑，不準）
            t = script_starts.get(x["s"]) or script_time.get(x["s"])
            if t and t.get("y", 0) >= 1:
                ts.append(t)
    if ts:
        e["time"] = {"type": "range", "from": min(ts, key=TKEY), "to": {"y": 4, "m": 3, "s": 3}, "open": True, "after": True}

out = {
    "heroines": heroines,
    "targets": TARGETS,
    "scriptTime": script_time,
    "events": events,
    "scripts": {k: v for k, v in script_info.items() if k in used or k in entry_scripts},
    "flags": {k: v[:12] for k, v in flag_setters.items()},
    "lovers": {str(k): v for k, v in lover_points.items()},
    "loverNames": {k[len("PlayerInfo/Lover/"):]: v for k, v in loc.items() if k.startswith("PlayerInfo/Lover/")},
    "flagNames": {k[len("Flag/Name/"):]: v for k, v in loc.items() if k.startswith("Flag/Name/")},
    "readers": {k: sorted(v)[:12] for k, v in readers.items()},
    "places": PLACE_ORDER,
    "library": library,
    "positions": positions,
    "unread": unread,
    # 「旗標暫存N」是開發用的暫存欄位說明，對玩家沒有意義
    "flagNotes": {o["m_Name"]: o["_devNote"].strip() for o in by_name["FlagData"].values()
                  if (o.get("_devNote") or "").strip() and not re.match(r"^旗標暫存\d*$", o["_devNote"].strip())},
    "stats": {"scripts": len(scripts), "events": len(events), "readKeys": len(read_keys)},
    # 決鬥關卡打贏／打輸時寫入的旗標值（網頁把劇本裡找不到設定位置的暫存旗標翻成「戰鬥勝利／落敗」）
    "battleFlags": battle_flag_values,
    "scriptVia": script_via,
    # 網頁連上遊戲時判斷條件用：條件文字裡的名稱 → 存檔鍵名
    # 任務時間是在哪個事件裡記下的、記成多久之後
    "missionTimes": {k: [{"ev": find_owner(sc)[0], "off": off} for sc, off in v] for k, v in mission_time_set.items()},
    "liveKeys": {"stat": parse_enum_strings("GameStatType"), "rel": parse_enum_strings("RelationshipStatType")},
}
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("events", len(events), "scripts in graph", len(out["scripts"]), "size", os.path.getsize(out_path))
