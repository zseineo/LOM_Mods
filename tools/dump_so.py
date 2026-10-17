import sys, os, json, collections, traceback
import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
game_root, out_path = sys.argv[1], os.path.abspath(sys.argv[2])
want = set(sys.argv[3].split(",")) if len(sys.argv) > 3 and sys.argv[3] else None
data_dir = os.path.join(game_root, "Mortal_Data")
os.chdir(data_dir)
files = [f for f in os.listdir(".")
         if f in ("globalgamemanagers", "globalgamemanagers.assets", "resources.assets")
         or (f.startswith("sharedassets") and f.endswith(".assets"))
         or (f.startswith("level") and "." not in f)]
env = UnityPy.load(*files)
gen = TypeTreeGenerator("2020.3.49f1")
gen.load_local_dll_folder(os.path.join(data_dir, "Managed"))

def base(n):
    return os.path.basename(n).lower()

sfiles = {base(k): f for k, f in env.files.items() if hasattr(f, "objects")}
# MonoScript table
scripts = {}
for obj in sfiles["globalgamemanagers.assets"].objects.values():
    if obj.type.name == "MonoScript":
        d = obj.read()
        scripts[obj.path_id] = (d.m_AssemblyName, d.m_Namespace, d.m_ClassName)

def head(obj):
    r = obj.reader
    r.Position = obj.byte_start
    r.read_int(); r.read_long()
    r.read_u_byte(); r.align_stream()
    sf, sp = r.read_int(), r.read_long()
    name = r.read_aligned_string()
    return sf, sp, name

def ext_name(f, fid):
    return base(f.externals[fid - 1].path) if fid > 0 else base(f.name)

index = {}
todo = []
cls_count = collections.Counter()
for fn, f in sfiles.items():
    for pid, obj in f.objects.items():
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            sf, sp, name = head(obj)
            if ext_name(f, sf) != "globalgamemanagers.assets":
                continue
            asm, ns, cls = scripts.get(sp, ("?", "?", "?"))
        except Exception:
            continue
        cls_count[cls] += 1
        index[(fn, pid)] = (cls, name)
        if want is None or cls in want:
            todo.append((fn, f, obj, asm, ns, cls, name))

def resolve(f, ptr):
    fid, pid = ptr.get("m_FileID", 0), ptr.get("m_PathID", 0)
    if pid == 0:
        return None
    try:
        tgt = ext_name(f, fid)
    except Exception:
        return f"?bad{fid}:{pid}"
    hit = index.get((tgt, pid))
    if hit:
        return f"{hit[0]}:{fixstr(hit[1])}@{tgt}:{pid}"
    o = sfiles.get(tgt, None)
    if o is not None and pid in o.objects:
        return f"<{o.objects[pid].type.name}>:{pid}"
    return f"?{tgt}:{pid}"

SKIP = {"m_GameObject", "m_Script", "m_Enabled", "m_EditorHideFlags", "m_EditorClassIdentifier"}
def fixstr(s):
    try:
        b = s.encode("utf-8", "surrogateescape")
    except Exception:
        return s
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp950", "replace")

def walk(f, v):
    if isinstance(v, str):
        return fixstr(v)
    if isinstance(v, dict):
        if set(v.keys()) == {"m_FileID", "m_PathID"}:
            return resolve(f, v)
        return {k: walk(f, x) for k, x in v.items() if k not in SKIP}
    if isinstance(v, list):
        return [walk(f, x) for x in v]
    return v

out = collections.defaultdict(list)
errs = 0
for fn, f, obj, asm, ns, cls, name in todo:
    try:
        node = gen.get_nodes_up(asm, f"{ns}.{cls}" if ns else cls)
        tt = obj.read_typetree(nodes=node, wrap=False, check_read=False)
        d = walk(f, tt)
        d["m_Name"] = fixstr(name)
        d["__file"] = fn
        d["__pid"] = obj.path_id
        out[cls].append(d)
    except Exception as e:
        errs += 1
        if errs < 5:
            traceback.print_exc(limit=2)
with open(out_path, "w", encoding="utf-8") as fp:
    json.dump(out, fp, ensure_ascii=False, indent=1)
print("errors", errs)
if want:
    for k in sorted(want):
        print(k, len(out.get(k, [])))
print("top classes:", cls_count.most_common(80))
