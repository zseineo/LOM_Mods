"""比較遊戲更新前後的 graph.json：事件條件、劇本分歧／旗標、旗標設定位置的差異。
遊戲更新後拿來對照手寫條件（build_graph.py 的 TARGETS、guides.json）有沒有要跟著改。
用法：python -I diff_graph.py <舊 graph.json> <新 graph.json>
"""
import difflib
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
old = json.load(open(sys.argv[1], encoding="utf-8"))
new = json.load(open(sys.argv[2], encoding="utf-8"))
here = os.path.dirname(os.path.abspath(__file__))


def flat(items, pre=""):
    out = []
    for x in items:
        if x["t"] == "branch":
            out.append(f"{pre}[{x['kind']} {x.get('name')}]")
            for b in x["branches"]:
                out.append(f"{pre} - {b['label']}")
                out += flat(b["items"], pre + "    ")
        elif x["t"] in ("flag", "next", "time", "ending"):
            out.append(pre + json.dumps({k: v for k, v in x.items() if k != "t"}, ensure_ascii=False))
    return out


print("==== 事件（時間、觸發條件）")
a = {e["id"]: e for e in old["events"]}
b = {e["id"]: e for e in new["events"]}
for k in sorted(set(a) | set(b)):
    x, y = a.get(k) or {}, b.get(k) or {}
    for f in ("time", "conds", "active"):
        if x.get(f) != y.get(f):
            print(f"{k} {f}: {x.get(f)} → {y.get(f)}")

print("\n==== 劇本分歧與旗標")
for k in sorted(set(old["scripts"]) | set(new["scripts"])):
    fx = flat((old["scripts"].get(k) or {"items": []})["items"])
    fy = flat((new["scripts"].get(k) or {"items": []})["items"])
    if fx != fy:
        print("##", k)
        for line in difflib.unified_diff(fx, fy, lineterm="", n=1):
            if not line.startswith(("---", "+++")):
                print(line)

# 手寫條件提到的旗標：設定位置有變的列出來
src = open(f"{here}/build_graph.py", encoding="utf-8").read()
hand = src[src.index("TARGETS = ["):src.index("for t in TARGETS")] + open(f"{here}/guides.json", encoding="utf-8").read()
key = lambda x: json.dumps({k: x.get(k) for k in ("s", "op", "v", "path")}, ensure_ascii=False, sort_keys=True)
print("\n==== 手寫條件用到的旗標，設定位置有變")
for f in sorted(set(re.findall(r"\b([A-Z]{1,2}\d{4,5}(?:_\d+)?)\b", hand))):
    ka = {key(x): x for x in old["flags"].get(f, [])}
    kb = {key(x): x for x in new["flags"].get(f, [])}
    if ka.keys() != kb.keys():
        print("==", f, new["flagNotes"].get(f))
        for k in ka.keys() - kb.keys():
            print("  -", ka[k]["s"], ka[k]["op"], ka[k]["v"], ka[k].get("path"))
        for k in kb.keys() - ka.keys():
            print("  +", kb[k]["s"], kb[k]["op"], kb[k]["v"], kb[k].get("path"))

# 地點事件：候選事件的開啟條件、權重、加成（遊戲更新常改「需認識某人」這類條件）
def cands(g):
    out = {}
    for p in g.get("positions", []):
        for ly in p["layers"]:
            for c in ly["candidates"]:
                out[(p["place"], p["action"], c["id"])] = (c.get("cond"), c.get("rate"), json.dumps(c.get("bonus"), ensure_ascii=False), c.get("note"))
    return out


print("\n==== 地點事件候選（條件、權重）")
ca, cb = cands(old), cands(new)
for k in sorted(set(ca) | set(cb)):
    if ca.get(k) != cb.get(k):
        print("·".join(k[:2]), k[2], (cb.get(k) or ca.get(k))[3] or "")
        print("  -", ca.get(k))
        print("  +", cb.get(k))
