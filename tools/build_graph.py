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
        return [f"第 {i + 1} 種次數條件" for i in range(len(o.get("_countItems", [])))] + ["其他次數"]
    items = [cond_item_text(ci) for ci in o.get("_items", [])]
    # 「以上皆非」補上它排除了哪些條件，讀的人才知道實際要滿足什麼
    others = "；".join(x if len(x) <= 80 else x[:80] + "…" for x in items)
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
}


def option_label(raw):
    raw = raw.strip()
    m = re.match(r'^(\w+) and "(.*)" or "~x"$', raw)
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
        return key, story_text(key) or loc.get(f"Position/Talk/{key}") or "+".join(parts[:2]), cond_var
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
        for k in ("next", "curscript", "travel", "lover", "scene", "mission", "setflag", "story", "text", "time", "ending", "cg", "save"):
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
    return root, vars_


def resolve_if(node, vars_):
    """標註 if 的種類與每個分支的標籤。"""
    first = node["branches"][0]["cond"]
    m = re.match(r"^(\w+) == (\d+)$", first)
    var = m.group(1) if m else re.sub(r"^not ", "", first)
    info = vars_.get(var, {})
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
            if significant and depth < 12:
                branches = []
                for br, (label, key) in zip(it["branches"], labels):
                    sub = summarize(br["block"], vars_, depth + 1)
                    sub_texts = sub.pop("_texts")
                    if key:
                        sub_texts = [key] + sub_texts
                    branches.append({"label": label, "read": read_ratio(sub_texts), **sub})
                    texts.extend(sub_texts)
                node = {"t": "branch", "kind": kind, "name": name, "branches": branches}
                if battles:
                    node["battles"] = battles
                items.append(node)
            else:
                for br, (label, key) in zip(it["branches"], labels):
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
        # 從事件開頭一路追到底（不設上限），順便推算每支腳本開始時的遊戲時間
        start_time = time.get("from") if time and time.get("from", {}).get("y", 0) >= 1 else None
        chain, queue = [], [(c["_startScript"].lower(), start_time)] if c["_startScript"] else []
        # 多條路徑到同一支腳本時取較晚的時間；時間變晚才重新往下傳
        in_chain, t_of = set(), {}
        tkey = lambda t: (t["y"], t["m"], t["s"]) if t else (0, 0, 0)
        while queue:
            s, t = queue.pop(0)
            if s not in script_info:
                continue
            if s in in_chain and tkey(t) <= tkey(t_of.get(s)):
                continue
            if s not in in_chain:
                chain.append(s)
                in_chain.add(s)
            t_of[s] = t
            after = time_after(s) or t
            for n in next_scripts(s):
                if n not in entry_scripts:
                    queue.append((n, after))
        for s, t in t_of.items():
            if t and tkey(t) > tkey(script_time.get(s)):
                script_time[s] = t
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
        })

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


def entry_conditions(script):
    steps, cur, seen = [], script, {script}
    for _ in range(6):
        parents = [p for p in entry_paths.get(cur, []) if p["from"] not in seen]
        if not parents or cur in entry_scripts:
            break
        conditional = [p for p in parents if p["path"]]
        # 只要有一個入口不需要條件，這一步就不是必要條件（例如回程旅途走完也會接到同一段）
        if conditional and len(conditional) == len(parents):
            steps.append({"into": cur, "options": conditional[:6]})
        if len({p["from"] for p in parents}) != 1:
            break
        cur = parents[0]["from"]
        seen.add(cur)
    return steps


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


def satisfies(v, op, n):
    return {"=": v == n, "≠": v != n, "<": v < n, "≤": v <= n, ">": v > n, "≥": v >= n}[op]


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
    (re.compile(r"^(tang_|center|alchemy|room|study|kitchen|backmountain|martial|princess|cellar|forge|champaign)"), "唐門"),
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
    # 背景圖都分不出來：才看傳說裡提到的地名（內文常順帶提到別處，所以放最後）
    score = collections.Counter()
    for sc in e["scripts"][:3]:
        info = script_info.get(sc)
        text = "".join(info["legend"]) if info else ""
        for word, place in WORD_PLACE.items():
            score[place] += text.count(word)
    return score.most_common(1)[0][0] if score else "旅途／其他"


for e in events:
    e["place"] = event_place(e)

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
    ("武林大會・錦香宮", "錦香宮", "（作客期間）", ["Ch_6_4_3_2_01"]),
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
# 兒時立繪（回憶場景裡的小梅、小竹、小蘭、雲裳）不算本人出場
CHILD_FORM = re.compile(r"幼年|^小小梅手$")
GENERIC_CHAR = re.compile(r"^(弟子|女弟子|武師|店小二|路人|村民|官兵|捕快|乞丐|特殊|鄉民|小販)\d*$")


def result_chars(script):
    seen, todo, out = {script}, [script], set()
    while todo:
        sc = todo.pop()
        out |= script_chars.get(sc, set())
        for n in next_scripts(sc):
            if n.startswith(script) and n not in seen:
                seen.add(n)
                todo.append(n)
    names = sorted({char_names.get(c, c) for c in out})
    return [n for n in names if not GENERIC_CHAR.match(n) and not CHILD_FORM.search(n)]


def action_title(key):
    return loc.get("Position/title/" + key) or story_text(key) or key


positions = []
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
            cands.append({
                "id": o["m_Name"], "code": code, "script": script, "note": (o.get("_devNote") or "").strip(),
                "cond": cond_item_text(o["_activeCondition"]) if o.get("_toggleCondition") else "",
                "rate": o.get("_defaultRate", 0),
                "bonus": [{"cond": cond_item_text(r["_condition"]), "rate": r["_rate"]} for r in o.get("_eventRateItem", [])],
                "chars": result_chars(script), "read": info["read"] if info else None,
                "title": first_line(script) or (re.sub(r"<[^>]+>|\{[^}]*\}", "", loc.get("Story/" + script_first_say[script], "")).replace("\n", "")
                                                if script_first_say.get(script) else ""),
            })
        layers.append({"group": gname, "candidates": cands})
    need = condition_text(option[0]).strip("（）") if option else ""
    positions.append({"area": area, "place": place, "action": action_title(action), "need": need, "layers": layers})

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
    for br, (label, key) in zip(it["branches"], labels):
        out.append((label, ([key] if key else []) + eff_texts(br["block"], vars_), br))
    return kind, labels, out


def best_branch(branches):
    return max(branches, key=lambda b: (read_ratio(b[1]) or 0, -len(b[1])))


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


def unread_reasons(block, vars_, path, out):
    for it in block:
        if it["t"] != "if":
            continue
        kind, labels, branches = branch_texts(it, vars_)
        if is_variant(kind, labels, it):
            unread_reasons(best_branch(branches)[2]["block"], vars_, path, out)
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
                out.append({"kind": kind, "label": label, "path": path[-3:], "lines": len(set(t))})
            elif r < 1:
                unread_reasons(br["block"], vars_, path + [label], out)


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
        texts = eff_texts(block, vars_)
        r = read_ratio(texts)
        if r is None or r >= 1:
            continue
        ev, _ = find_owner(name)
        item = {"s": name, "ev": ev, "read": r, "lines": len(set(texts)), "heroines": heroines_in(name),
                "place": script_place(name, ev), "title": first_line(name) or (
                    re.sub(r"<[^>]+>|\{[^}]*\}", "", loc.get("Story/" + script_first_say[name], "")).replace("\n", "") if script_first_say.get(name) else "")}
        if r == 0:
            item["entry"] = entry_conditions(name)
        else:
            reasons = []
            unread_reasons(block, vars_, [], reasons)
            item["reasons"] = reasons[:12]
        unread.append(item)

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
]
for t in TARGETS:
    t["routes"] = [requirement(x["s"], x["path"], 0, {t["flag"]}) for x in flag_setters.get(t["flag"], [])
                   if x.get("op") == "SetFlag" and x["v"] == t["val"]]

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
}
json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
print("events", len(events), "scripts in graph", len(out["scripts"]), "size", os.path.getsize(out_path))
