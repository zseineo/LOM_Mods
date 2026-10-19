"""把 smilin.net 活俠傳 wiki 的事件名稱對應到流程圖的事件。

用法：python -I match_wiki.py <graph.json> <wiki_names.json> [wiki 頁面暫存資料夾]

wiki 的「主支線簡易表格」每個事件一頁（docs/event/simple/<年>-<月>-<旬>-<名稱>.md）。
用頁面裡的選項、擲骰結果（「…」、【…】）和我們事件裡的選項比對，越少見的選項分數越高，時間差越多分數越低。
自動配對的結果寫進 wiki_names.json；手動改過的項目（"manual": true）重跑時保留。
"""
import collections
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request

graph_path, out_path = sys.argv[1], sys.argv[2]
cache = sys.argv[3] if len(sys.argv) > 3 else os.path.join(os.path.dirname(os.path.abspath(out_path)), "..", "data", "wiki_events")
REPO = "Mr-Smilin/LoM-wiki"
os.makedirs(cache, exist_ok=True)

listing = json.load(urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/contents/docs/event/simple", timeout=30))
for x in listing:
    path = os.path.join(cache, x["name"])
    if x["name"].endswith(".md") and not os.path.exists(path):
        url = f"https://raw.githubusercontent.com/{REPO}/main/docs/event/simple/" + urllib.parse.quote(x["name"])
        open(path, "wb").write(urllib.request.urlopen(url, timeout=30).read())

norm = lambda s: re.sub(r"[\s（）()「」！!？?，,。…～~、：:]+", "", s)
wiki = []
for fn in sorted(os.listdir(cache)):
    m = re.match(r"^(\d+)-(\d+)-(\d+)-(.+)\.md$", fn)
    if not m:
        continue
    text = re.sub(r"<[^>]+>", " ", open(os.path.join(cache, fn), encoding="utf-8").read())
    opts = {norm(o) for o in re.findall(r"「([^」]{2,40})」", text)}
    opts |= {norm(o) for o in re.findall(r"【[^】]*】\s*([^\s→【】<]{2,30})", text)}
    opts |= {norm(o) for o in re.findall(r"【🎲[^】]*?\d+\s*([^\]】]{2,30})】", text)}
    wiki.append({"name": m.group(4), "y": int(m.group(1)), "m": int(m.group(2)), "path": fn[:-3],
                 "opts": {o for o in opts if len(o) >= 3}})
df = collections.Counter(o for w in wiki for o in w["opts"])

G = json.load(open(graph_path, encoding="utf-8"))


def event_options(e):
    out = set()

    def walk(items):
        for it in items:
            if it["t"] == "branch":
                for br in it["branches"]:
                    if it["kind"] in ("choice", "dice"):
                        label = re.sub(r"（(<|<=|>=|>|=)\d+）$", "", re.sub(r"　〔.*〕$", "", br["label"]))
                        if len(norm(label)) >= 3:
                            out.add(norm(label))
                    walk(br["items"])
    for sc in e["scripts"]:
        walk(G["scripts"].get(sc, {}).get("items", []))
    return out


old = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {}
result = {k: v for k, v in old.items() if v.get("manual")}
for e in G["events"]:
    if e["id"] in result or e.get("meeting"):
        continue
    mine = event_options(e)
    t = (e.get("time") or {}).get("from") or {}
    best = None
    for w in wiki:
        common = mine & w["opts"]
        if not common:
            continue
        score = sum(1 / math.log2(1 + df[o]) for o in common)
        dm = abs((w["y"] * 12 + w["m"]) - (t["y"] * 12 + t["m"])) if w["y"] and t.get("y") else None
        score *= 1.5 if dm == 0 else 1.0 if dm == 1 else 0.5 if dm is not None and dm <= 3 else 0.2 if dm is not None else 1.0
        if not best or score > best[0]:
            best = (score, w, dm)
    if not best:
        continue
    score, w, dm = best
    # 分數夠高；或分數普通但時間對得上（劇情段落另有段名，要求高一點）
    if score >= 2 or (score >= 0.9 and dm is not None and dm <= 1 and not e.get("part")):
        result[e["id"]] = {"name": w["name"], "path": w["path"], "score": round(score, 2)}
json.dump(dict(sorted(result.items())), open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"wiki 事件 {len(wiki)}，對上 {len(result)} 個事件")
