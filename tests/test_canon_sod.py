from __future__ import annotations

import hashlib
import hmac
import math
import os
import sqlite3
import tempfile
import threading
import time

import canon_sod as C


passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    ok = bool(condition)
    passed += int(ok)
    failed += int(not ok)
    print(("  PASS " if ok else "  FAIL ") + name + ("" if ok else f" <- {detail}"))


KEY_A = b"separate-human-a-key"
KEY_B = b"separate-human-b-key"
POLICY = "canon-policy-2026-07"


def signer(key):
    return lambda message: hmac.new(key, message, hashlib.sha256).hexdigest()


def verifier(key):
    return lambda message, signature: hmac.compare_digest(
        signature, hmac.new(key, message, hashlib.sha256).hexdigest()
    )


approver_a = C.Approver("human-a", signer(KEY_A))
approver_b = C.Approver("human-b", signer(KEY_B))
trust_source = {"human-a": verifier(KEY_A)}
approval_verifier = C.ApprovalVerifier(
    trust_source,
    policy_id=POLICY,
    max_ttl_s=120,
    max_future_skew_s=5,
)
# Mutating the constructor input cannot add a trusted issuer later.
trust_source["human-b"] = verifier(KEY_B)

with tempfile.TemporaryDirectory() as state:
    db = os.path.join(state, "canon.db")
    promoter = C.CanonPromoter(db, approval_verifier)

    candidate = {"claim": "BTC regime is trend", "evidence_ref": "ev-1"}
    candidate_digest = C.candidate_hash(candidate)
    approval = approver_a.approve(
        candidate_digest, "nonce-1", policy_id=POLICY, ttl_s=120
    )
    result = promoter.promote(candidate, approval)
    check(
        "valid separate-party approval promotes",
        result["ok"]
        and result["candidate_hash"] == candidate_digest
        and result["policy_id"] == POLICY
        and result["issuer_id"] == "human-a",
        result,
    )

    policy_row = promoter.con.execute(
        "SELECT policy_id,policy_fingerprint FROM canon_policy_v3 WHERE singleton=1"
    ).fetchone()
    stored = promoter.con.execute(
        "SELECT policy_id,issuer_id,nonce,candidate_json FROM canon_promotion_v3"
    ).fetchone()
    check(
        "policy id and configuration are durably pinned",
        policy_row == (POLICY, approval_verifier.policy_fingerprint)
        and stored[:3] == (POLICY, "human-a", "nonce-1"),
    )
    check("canonical candidate is durably stored", stored[3] == '{"claim":"BTC regime is trend","evidence_ref":"ev-1"}')

    replay_candidate = {"claim": "different work"}
    replay_approval = approver_a.approve(
        C.candidate_hash(replay_candidate), "nonce-1", policy_id=POLICY, ttl_s=120
    )
    replay = promoter.promote(replay_candidate, replay_approval)
    check("durable nonce replay rejected", not replay["ok"] and replay["reason"] == "NONCE_REPLAY", replay)

    new_nonce_same_candidate = approver_a.approve(
        candidate_digest, "nonce-not-consumed", policy_id=POLICY, ttl_s=120
    )
    duplicate = promoter.promote(candidate, new_nonce_same_candidate)
    check("duplicate candidate rejected", not duplicate["ok"] and duplicate["reason"] == "ALREADY_PROMOTED", duplicate)
    replacement = {"claim": "nonce remains usable after rolled-back duplicate"}
    replacement_result = promoter.promote(
        replacement,
        approver_a.approve(
            C.candidate_hash(replacement),
            "nonce-not-consumed",
            policy_id=POLICY,
            ttl_s=120,
        ),
    )
    check("failed duplicate does not consume nonce", replacement_result["ok"], replacement_result)

    forged_candidate = {"claim": "self approve me"}
    forged_hash = C.candidate_hash(forged_candidate)
    forged = approver_a.approve(forged_hash, "forged", policy_id=POLICY, ttl_s=120)
    forged["signature"] = "deadbeef"
    check("self-forged signature rejected", not promoter.promote(forged_candidate, forged)["ok"])

    wrong_candidate = {"claim": "wrong candidate"}
    check(
        "approval bound to exact candidate",
        not promoter.promote(
            wrong_candidate,
            approver_a.approve(forged_hash, "wrong-candidate", policy_id=POLICY),
        )["ok"],
    )

    untrusted = approver_b.approve(forged_hash, "issuer-b", policy_id=POLICY)
    check("allowlist is fixed and unknown issuer rejected", approval_verifier.verify(forged_hash, untrusted).reason == "UNTRUSTED_ISSUER")

    wrong_policy = approver_a.approve(forged_hash, "wrong-policy", policy_id="other-policy")
    check("approval policy is exact", approval_verifier.verify(forged_hash, wrong_policy).reason == "WRONG_POLICY")

    now = int(time.time())
    expired = approver_a.approve(
        forged_hash, "expired", policy_id=POLICY, ttl_s=60, issued_at=now - 61
    )
    check("expired approval rejected", approval_verifier.verify(forged_hash, expired).reason == "APPROVAL_EXPIRED")

    future = approver_a.approve(
        forged_hash, "future", policy_id=POLICY, ttl_s=60, issued_at=now + 60
    )
    check("far-future approval rejected", approval_verifier.verify(forged_hash, future).reason == "APPROVAL_FROM_FUTURE")

    excessive_ttl = approver_a.approve(
        forged_hash, "long-ttl", policy_id=POLICY, ttl_s=121, issued_at=now
    )
    check("issuer cannot exceed verifier TTL policy", approval_verifier.verify(forged_hash, excessive_ttl).reason == "INVALID_APPROVAL_TTL")

    full_payload = approver_a.approve(
        forged_hash, "full-payload", policy_id=POLICY, ttl_s=60
    )
    mutations = {
        "domain": "other.domain",
        "version": 99,
        "issuer_id": "human-b",
        "policy_id": "other-policy",
        "candidate_hash": "0" * 64,
        "nonce": "changed",
        "issued_at": full_payload["issued_at"] - 1,
        "expires_at": full_payload["expires_at"] + 1,
        "signature": "bad",
    }
    all_mutations_rejected = True
    for field, value in mutations.items():
        mutated = dict(full_payload)
        mutated[field] = value
        all_mutations_rejected &= not approval_verifier.verify(forged_hash, mutated).accepted
    unexpected = dict(full_payload)
    unexpected["approved"] = True
    all_mutations_rejected &= not approval_verifier.verify(forged_hash, unexpected).accepted
    check("signature/domain covers full exact approval payload", all_mutations_rejected)

    malformed_values = [
        None,
        {},
        {"candidate_hash": forged_hash},
        {**full_payload, "issued_at": True},
        {**full_payload, "expires_at": "tomorrow"},
        {**full_payload, "signature": None},
    ]
    malformed_safe = True
    for malformed in malformed_values:
        try:
            malformed_safe &= not promoter.promote(forged_candidate, malformed)["ok"]
        except Exception:
            malformed_safe = False
    check("malformed approval dictionaries fail closed without crash", malformed_safe)

    check(
        "canonical JSON rejects NaN",
        not promoter.promote({"claim": math.nan}, full_payload)["ok"],
    )
    try:
        C.candidate_hash({"claim": float("inf")})
        infinity_rejected = False
    except C.CandidateEncodingError:
        infinity_rejected = True
    check("canonical hash rejects infinity", infinity_rejected)

    noncanonical_candidates = [
        {1: "integer key"},
        {"tuple": (1, 2)},
        {"nested": [1, {"bad": math.nan}]},
        {"surrogate": "\ud800"},
    ]
    all_noncanonical_rejected = True
    for noncanonical in noncanonical_candidates:
        try:
            C.candidate_hash(noncanonical)
            all_noncanonical_rejected = False
        except C.CandidateEncodingError:
            pass
    check(
        "canonical hash rejects ambiguous or unsupported JSON shapes",
        all_noncanonical_rejected,
    )

    check("verifier exposes no signing method", not hasattr(approval_verifier, "approve") and not hasattr(approval_verifier, "sign"))
    check("promoter exposes no approval minting method", not hasattr(promoter, "approve") and not hasattr(promoter, "make_human_approval"))
    promoter.close()

    try:
        C.CanonPromoter(os.path.join(state, "legacy-api.db"), lambda *args: True)
        legacy_callable_rejected = False
    except C.LegacyVerifierAPIRejected:
        legacy_callable_rejected = not os.path.exists(os.path.join(state, "legacy-api.db"))
    check("callable-only verifier API fails before DB creation", legacy_callable_rejected)

    try:
        C.Approver(KEY_A)  # type: ignore[call-arg]
        raw_key_legacy_rejected = False
    except (TypeError, ValueError):
        raw_key_legacy_rejected = True
    check("raw-key legacy Approver API rejected", raw_key_legacy_rejected)

    first_policy_db = os.path.join(state, "policy-bound.db")
    first_policy_promoter = C.CanonPromoter(first_policy_db, approval_verifier)
    first_policy_promoter.close()
    other_verifier = C.ApprovalVerifier(
        {"human-a": verifier(KEY_A)}, policy_id="different-policy"
    )
    try:
        C.CanonPromoter(first_policy_db, other_verifier)
        policy_change_rejected = False
    except C.PolicyBindingError:
        policy_change_rejected = True
    check("database cannot be reopened under another policy", policy_change_rejected)

    changed_config = C.ApprovalVerifier(
        {"human-a": verifier(KEY_A), "human-b": verifier(KEY_B)},
        policy_id=POLICY,
        max_ttl_s=999,
    )
    try:
        C.CanonPromoter(first_policy_db, changed_config)
        policy_config_change_rejected = False
    except C.PolicyBindingError:
        policy_config_change_rejected = True
    check(
        "same policy id cannot hide allowlist or TTL drift",
        policy_config_change_rejected,
    )

    legacy_db = os.path.join(state, "legacy-v2.db")
    old = sqlite3.connect(legacy_db)
    old.execute("CREATE TABLE used_nonce(nonce TEXT PRIMARY KEY, ts REAL)")
    old.execute("CREATE TABLE canon(cand_hash TEXT PRIMARY KEY, ts REAL)")
    old.commit()
    old.close()
    try:
        C.CanonPromoter(legacy_db, approval_verifier)
        legacy_db_rejected = False
    except C.LegacyDatabaseRejected:
        legacy_db_rejected = True
    check("legacy database cannot silently lose replay history", legacy_db_rejected)

    concurrent_db = os.path.join(state, "concurrent.db")
    concurrent_candidate = {"claim": "one atomic winner"}
    concurrent_hash = C.candidate_hash(concurrent_candidate)
    barrier = threading.Barrier(2, timeout=10)
    outcomes: list[tuple[str, dict]] = []
    outcomes_lock = threading.Lock()

    def race(nonce):
        local = None
        outcome = None
        try:
            local = C.CanonPromoter(concurrent_db, approval_verifier)
            approval_value = approver_a.approve(
                concurrent_hash, nonce, policy_id=POLICY, ttl_s=120
            )
            barrier.wait()
            outcome = local.promote(concurrent_candidate, approval_value)
        except Exception as error:
            # Never leave the peer blocked forever if connection setup fails.
            barrier.abort()
            outcome = {
                "ok": False,
                "reason": f"RACE_SETUP_FAILED:{type(error).__name__}",
            }
        finally:
            if local is not None:
                try:
                    local.close()
                except Exception as error:
                    if outcome is None:
                        outcome = {
                            "ok": False,
                            "reason": f"RACE_CLOSE_FAILED:{type(error).__name__}",
                        }
        with outcomes_lock:
            outcomes.append(
                (nonce, outcome or {"ok": False, "reason": "RACE_NO_OUTCOME"})
            )

    threads = [
        threading.Thread(target=race, args=("race-a",), daemon=True),
        threading.Thread(target=race, args=("race-b",), daemon=True),
    ]
    for thread in threads:
        thread.start()
    join_deadline = time.monotonic() + 45
    for thread in threads:
        thread.join(max(0, join_deadline - time.monotonic()))
    threads_terminated = all(not thread.is_alive() for thread in threads)
    if not threads_terminated:
        barrier.abort()
    check(
        "concurrent initialization and promotion terminate within bound",
        threads_terminated,
        outcomes,
    )
    winners = [entry for entry in outcomes if entry[1]["ok"]] if threads_terminated else []
    losers = [entry for entry in outcomes if not entry[1]["ok"]] if threads_terminated else []
    check(
        "BEGIN IMMEDIATE gives one atomic winner",
        len(winners) == 1
        and len(losers) == 1
        and losers[0][1]["reason"] == "ALREADY_PROMOTED",
        outcomes,
    )
    counts = None
    if threads_terminated:
        audit = sqlite3.connect(concurrent_db)
        counts = (
            audit.execute("SELECT COUNT(*) FROM canon_nonce_v3").fetchone()[0],
            audit.execute("SELECT COUNT(*) FROM canon_promotion_v3").fetchone()[0],
        )
        audit.close()
    check("nonce and canon commit together", counts == (1, 1), counts)

print(f"\nTALLY canon-SoD v3: PASS={passed} FAIL={failed}")
raise SystemExit(1 if failed else 0)
