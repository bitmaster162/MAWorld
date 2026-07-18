"""Spike B (v1.4 §7 / DR2 report) — git commit with push HOLD, capability-scoped, crash-safe.

Owner requests "prepare patch and commit". ContinuityOS DelegationGrant permits repo.read,
worktree.write, test, commit — but NOT git.push. Work runs in a Tier2 sandbox (bwrap). The commit
is an idempotent ExternalEffect: kill after commit, recovery reconciles against git log and does
NOT create a duplicate commit. git push stays HOLD (capability not in grant) -> requires explicit
approval. Produces commit sha, diff, test result, audit, trace.
"""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess, sys, tempfile, uuid
from capability import Authority
from external_effect_registry import ExternalEffectRegistry

HERE = os.path.dirname(os.path.abspath(__file__))

def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=check)

def sandboxed_worktree_write(repo, rel, content):
    """worktree.write executed inside a Tier2 sandbox (bwrap): only the repo dir is writable."""
    if not shutil.which("bwrap"):
        with open(os.path.join(repo, rel), "w") as f: f.write(content); return "UNSAFE_fallback"
    code = "open('/work/repo/%s','w').write(%r)" % (rel, content)
    cmd = ["bwrap","--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib"]
    if os.path.exists("/lib64"): cmd += ["--ro-bind","/lib64","/lib64"]
    cmd += ["--bind", repo, "/work/repo","--proc","/proc","--dev","/dev",
            "--unshare-all","--die-with-parent","--chdir","/work","python3","-c",code]
    subprocess.run(cmd, check=True, timeout=15)
    return "bwrap"

def commit_marker(idem): return "MAWORLD_SPIKE_B:" + idem

def do_commit(repo, rel, idem):
    git(repo, "add", rel)
    git(repo, "commit", "-m", "spike B change\n\n" + commit_marker(idem))
    return git(repo, "rev-parse", "HEAD").stdout.strip()

def commit_exists(repo, idem):
    r = git(repo, "log", "--all", "--grep", commit_marker(idem), "--format=%H", check=False)
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else None

def main():
    st = tempfile.mkdtemp(prefix="spikeB-")
    repo = os.path.join(st, "repo"); os.makedirs(repo)
    git(repo, "init", "-q"); git(repo, "config", "user.email", "spike@maworld"); git(repo, "config", "user.name", "spike")
    open(os.path.join(repo, "README.md"), "w").write("# repo\n"); git(repo, "add", "."); git(repo, "commit", "-q", "-m", "init")
    reg = ExternalEffectRegistry(os.path.join(st, "eff.db"))
    A = Authority(b"spike-b-secret")
    idem = "commit-" + uuid.uuid4().hex[:8]

    print("="*62); print("SPIKE B: git commit + push HOLD (capability-scoped, crash-safe)"); print("="*62)

    # 1-3. DelegationGrant: commit-family capabilities, NOT push
    grant = A.issue_grant("projA", "codex-worker",
                          {"repo.read", "worktree.write", "test", "git.commit"}, ttl_sec=300)

    def cap(action_id, capability):
        tok, reason = A.mint_token(grant, action_id, "projA", capability)
        if tok is None: return None, reason
        return A.redeem(tok, action_id, capability)[0], reason

    # 4. worktree.write (capability-gated) inside sandbox
    wdec, _ = cap("act-write", "worktree.write")
    mech = sandboxed_worktree_write(repo, "feature.txt", "new feature line\n") if wdec == "ALLOW" else "DENIED"

    # 5. test (capability-gated)
    tdec, _ = cap("act-test", "test")
    tests_pass = (tdec == "ALLOW")  # mock: a real test command would run here

    # 6. commit as an idempotent external effect
    cdec, _ = cap("act-commit", "git.commit")
    committed_sha = None
    if cdec == "ALLOW" and tests_pass:
        reg.register_intent("commit", idem, "git", "IRREVERSIBLE")  # a commit is not auto-undoable
        # CRASH MODEL: the git commit lands in the repo, but the process is killed BEFORE the
        # registry records CONFIRMED. So we perform the commit and mark only SENT (not CONFIRMED).
        reg.con.execute("UPDATE external_effect SET execution_status='SENT' WHERE effect_id='commit'"); reg.con.commit()
        committed_sha = do_commit(repo, "feature.txt", idem)
        # <-- crash here: no CONFIRMED write persisted

    # 7. git push -> capability NOT in grant -> HOLD
    push_tok, push_reason = A.mint_token(grant, "act-push", "projA", "git.push")
    push_held = push_tok is None and push_reason == "CAPABILITY_NOT_IN_GRANT"

    # 8. CRASH SIMULATION + RECOVERY: pretend we crashed after commit before recording.
    # Recovery reconciles against git log; must NOT create a duplicate commit.
    reg2 = ExternalEffectRegistry(os.path.join(st, "eff.db"))   # fresh registry handle (post-restart)
    recon = reg2.reconcile("commit", lambda: "CONFIRMED" if commit_exists(repo, idem) else "ABSENT")
    # a naive recovery might try to re-commit; prove idempotency guards it:
    before = len(git(repo, "log", "--grep", commit_marker(idem), "--format=%H").stdout.strip().splitlines())
    replay = reg2.execute_once("commit", lambda: {"sha": do_commit(repo, "feature.txt", idem)})
    after = len(git(repo, "log", "--grep", commit_marker(idem), "--format=%H").stdout.strip().splitlines())

    # 9. evidence
    diff = git(repo, "show", "--stat", committed_sha, check=False).stdout if committed_sha else ""
    n_commits_total = len(git(repo, "log", "--format=%H").stdout.strip().splitlines())

    print(f"worktree.write sandbox   : {mech}")
    print(f"commit capability        : {cdec}  sha={committed_sha[:10] if committed_sha else None}")
    print(f"push capability          : {'HOLD (not in grant)' if push_held else push_reason}")
    print(f"reconcile after 'crash'  : {recon}")
    print(f"replay commit status     : {replay['status']}  commits_with_marker: {before}->{after}")
    print(f"evidence: diff stat      : {diff.strip().splitlines()[-1].strip() if diff.strip() else 'n/a'}")

    checks = {
        "worktree.write ran in sandbox": mech == "bwrap",
        "commit performed under capability": committed_sha is not None,
        "git push HELD (capability not granted)": push_held,
        "recovery reconciles commit as CONFIRMED": recon == "RECONCILED_CONFIRMED_NO_REFIRE",
        "replay did NOT duplicate the commit": replay["status"] == "REPLAYED_NO_REFIRE" and before == after == 1,
        "exactly one feature commit exists": after == 1,
        "evidence (sha+diff) produced": bool(committed_sha) and bool(diff),
    }
    print("\n-- checks --")
    ok=True
    for k,v in checks.items(): print(("PASS" if v else "FAIL"),"|",k); ok=ok and v
    reg.close(); reg2.close(); shutil.rmtree(st, ignore_errors=True)
    print("\n" + ("SPIKE B PASSED -- commit under capability, push HOLD, recovery no-duplicate." if ok else "SPIKE B FAILED"))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
