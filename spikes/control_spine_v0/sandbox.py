from __future__ import annotations
import shutil, subprocess, tempfile, os
from dataclasses import dataclass
@dataclass
class SandboxResult:
    ok: bool; stdout: str; stderr: str; exit_code: int; mechanism: str; egress_blocked: bool
_HAVE_BWRAP = shutil.which("bwrap") is not None
def run_python(code, timeout=15):
    workdir = tempfile.mkdtemp(prefix="maw_sbx_")
    script = os.path.join(workdir, "task.py")
    open(script, "w").write(code)
    if _HAVE_BWRAP:
        cmd = ["bwrap","--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib"]
        if os.path.exists("/lib64"): cmd += ["--ro-bind","/lib64","/lib64"]
        cmd += ["--ro-bind",script,"/work/task.py","--tmpfs","/work/out","--proc","/proc","--dev","/dev",
                "--unshare-all","--die-with-parent","--chdir","/work","python3","/work/task.py"]
        mech, egress = "bwrap", True
    else:
        cmd = ["python3", script]; mech, egress = "UNSAFE_fallback", False
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return SandboxResult(p.returncode==0, p.stdout, p.stderr, p.returncode, mech, egress)
    except subprocess.TimeoutExpired:
        return SandboxResult(False,"","TIMEOUT",124,mech,egress)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
