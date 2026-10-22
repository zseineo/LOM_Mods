"""把 build_graph.py 的 JSON 與 guides.json 填進 HTML 範本。

用法：python -I render_preview.py <graph.json> <template.html> <out.html> [guides.json]
"""
import json
import os
import sys

graph, template, out = sys.argv[1:4]
guides_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides.json")
g = json.load(open(graph, encoding="utf-8"))


# 傳奇（劇情摘要）、結局文本不放進網頁：graph.json 留著給分析用
def strip_legend(o):
    if isinstance(o, dict):
        o.pop("legend", None)
        for v in o.values():
            strip_legend(v)
    elif isinstance(o, list):
        for v in o:
            strip_legend(v)


strip_legend(g["scripts"])
for x in g["heroines"] + g["targets"]:
    if x.get("ending"):
        x["ending"] = True
for x in g["library"].values():
    x.pop("desc", None)
data = json.dumps(g, ensure_ascii=False).replace("</", "<\\/")
guides_obj = json.load(open(guides_path, encoding="utf-8"))
guides = json.dumps(guides_obj, ensure_ascii=False).replace("</", "<\\/")
# 多語言對照（i18n/strings.json）：只放有改寫或有翻譯的字，沒有的網頁直接用原文
strings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "i18n", "strings.json")
i18n = {}
if os.path.exists(strings_path):
    for key, e in json.load(open(strings_path, encoding="utf-8"))["strings"].items():
        if e.get("unused") or (e.get("group") == "mod" and not e.get("also")):
            continue
        langs = {lang: e[lang] for lang in ("zh-TW", "ja", "ko") if e.get(lang)}
        if langs:
            i18n[key] = langs
i18n_json = json.dumps(i18n, ensure_ascii=False).replace("</", "<\\/")
html = open(template, encoding="utf-8").read().replace("__DATA__", data).replace("__GUIDES__", guides).replace("__I18N__", i18n_json)
open(out, "w", encoding="utf-8").write(html)
print("written", out, len(html))
