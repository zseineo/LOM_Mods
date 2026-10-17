"""把 build_graph.py 的 JSON 與 guides.json 填進 HTML 範本。

用法：python -I render_preview.py <graph.json> <template.html> <out.html> [guides.json]
"""
import json
import os
import sys

graph, template, out = sys.argv[1:4]
guides_path = sys.argv[4] if len(sys.argv) > 4 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides.json")
data = open(graph, encoding="utf-8").read().replace("</", "<\\/")
guides_obj = json.load(open(guides_path, encoding="utf-8"))
# 汗青書／生死簿的 wiki 攻略（依遊戲圖鑑編號）
wiki_path = os.path.join(os.path.dirname(os.path.abspath(guides_path)), "library_wiki.json")
if os.path.exists(wiki_path):
    guides_obj["libraryWiki"] = json.load(open(wiki_path, encoding="utf-8"))
guides = json.dumps(guides_obj, ensure_ascii=False).replace("</", "<\\/")
html = open(template, encoding="utf-8").read().replace("__DATA__", data).replace("__GUIDES__", guides)
open(out, "w", encoding="utf-8").write(html)
print("written", out, len(html))
