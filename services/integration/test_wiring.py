import os, sys
from wiring import all_seams
root = os.environ.get("PROJECTS_ROOT") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../..")
)
seams = all_seams(root)
if not os.environ.get("PROJECTS_ROOT") and all(
    seam.missing == ["<file not found>"] for seam in seams
):
    print("SKIP external seam AST check: sibling projects are not present; no runtime acceptance claimed")
    sys.exit(0)
print("== Integration wiring seams (real code vs MAWorld adapter needs) ==")
ok = True
for s in seams:
    status = "OK" if s.ok else "MISSING " + ",".join(s.missing)
    print(f"  {'PASS' if s.ok else 'FAIL'} | {s.name:20s} {s.cls or '(module)':22s} -> {status}")
    ok = ok and s.ok
print("\n"+("ALL SEAMS COMPATIBLE ("+str(sum(s.ok for s in seams))+"/"+str(len(seams))+")" if ok else "SEAM MISMATCH"))
sys.exit(0 if ok else 1)
