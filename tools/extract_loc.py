import sys, os, collections
import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
game_root, out_dir, lang = sys.argv[1], os.path.abspath(sys.argv[2]), sys.argv[3]
data_dir = os.path.join(game_root, "Mortal_Data")
os.chdir(data_dir)
files = [f for f in os.listdir(".") if f in ("globalgamemanagers", "globalgamemanagers.assets", "resources.assets")
         or (f.startswith("sharedassets") and f.endswith(".assets")) or (f.startswith("level") and "." not in f)]
env = UnityPy.load(*files)
gen = TypeTreeGenerator("2020.3.49f1"); gen.load_local_dll_folder(os.path.join(data_dir, "Managed"))
base = lambda n: os.path.basename(n).lower()
sfiles = {base(k): f for k, f in env.files.items() if hasattr(f, "objects")}
scripts = {}
for obj in sfiles["globalgamemanagers.assets"].objects.values():
    if obj.type.name == "MonoScript":
        d = obj.read(); scripts[obj.path_id] = (d.m_AssemblyName, d.m_Namespace, d.m_ClassName)
def head(obj):
    r = obj.reader; r.Position = obj.byte_start
    r.read_int(); r.read_long(); r.read_u_byte(); r.align_stream()
    return r.read_int(), r.read_long()
os.makedirs(out_dir, exist_ok=True)
seen = set(); n = 0
for fn, f in sfiles.items():
    for obj in f.objects.values():
        if obj.type.name != "MonoBehaviour": continue
        try:
            sf, sp = head(obj)
            if sf <= 0 or base(f.externals[sf-1].path) != "globalgamemanagers.assets": continue
            asm, ns, cls = scripts.get(sp, ("", "", ""))
        except Exception: continue
        if cls != "LeanLanguageCSV": continue
        tt = obj.read_typetree(nodes=gen.get_nodes_up(asm, f"{ns}.{cls}" if ns else cls), wrap=False, check_read=False)
        if tt.get("Language") != lang: continue
        src = tt["Source"]; fid, pid = src["m_FileID"], src["m_PathID"]
        tf = fn if fid == 0 else base(f.externals[fid-1].path)
        key = (tf, pid)
        if key in seen or pid == 0: continue
        seen.add(key)
        ta = sfiles[tf].objects[pid].read()
        s = ta.m_Script
        b = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
        with open(os.path.join(out_dir, f"{ta.m_Name}.txt"), "wb") as fp: fp.write(b)
        n += 1
print("csv files", n)
