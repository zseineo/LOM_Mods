import sys, os, UnityPy, collections
data_dir, out_dir = sys.argv[1], sys.argv[2]
env = UnityPy.load(data_dir + "/globalgamemanagers", data_dir + "/resources.assets")
rm = None
for obj in env.objects:
    if obj.type.name == "ResourceManager":
        rm = obj.read_typetree()
        break
cont = rm["m_Container"]
print("container entries", len(cont))
# map (fileID, pathID) -> path
files = {}
gg = [f for f in env.files.values()]
res = None
for name, f in env.files.items():
    if name.endswith("resources.assets"):
        res = f
by_pid = {}
for path, pptr in cont:
    by_pid.setdefault(pptr["m_PathID"], []).append(path)
tops = collections.Counter()
n = 0
for obj in res.objects.values():
    if obj.type.name != "TextAsset":
        continue
    paths = by_pid.get(obj.path_id, [])
    d = obj.read()
    s = d.m_Script
    b = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
    for p in paths or ["_unmapped/" + d.m_Name]:
        tops["/".join(p.split("/")[:2])] += 1
        dst = os.path.join(out_dir, p + ".txt")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(b)
        n += 1
print("written", n)
for k, v in tops.most_common(30):
    print(v, k)
