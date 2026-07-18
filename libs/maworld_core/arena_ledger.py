"""Arena ledger — RFC 9162 Merkle + I-JSON canonicalization + externally anchored manifests.

This module exists because an adversarial DR round REFUTED the first version. Each part is a
falsification turned into code:

  A) duplicate-last Merkle produced the SAME root for [a,b,c] and [a,b,c,c] (CVE-2012-2459 class;
     Bitcoin Core carries an explicit warning about this). Reproduced on our own code.
     -> RFC 6962/9162: LeafHash = H(0x00 || leaf), NodeHash = H(0x01 || L || R), size-determined
        split (largest power of two < n). No duplicate-last. Domain separation additionally kills
        the leaf/internal-node confusion class.
  C) RFC 8785 alone is NOT hash stability: duplicate keys, Unicode NFC/NFD, and numbers outside the
     IEEE-754 safe range break byte-identity across languages/serializers — semantically, not
     cryptographically. -> I-JSON discipline enforced at the input contract; floats are BANNED in
     hashed payloads; money must be int minor units or decimal strings.
  B) A commitment published only by us proves NOTHING about when it was published. An internal
     hash-chain gives no independent time. -> Manifest + external anchor (RFC 3161 TSA /
     transparency log / OpenTimestamps) + a pre-registered round schedule with mandatory
     NULL-MANIFEST, so omission (silently skipping an inconvenient round) is detectable too.

Honest scope: this makes backdating and omission DETECTABLE by a third party. It does not make the
operator trustworthy by itself, and it proves nothing about lookahead (see arena_bridge docs).
"""
from __future__ import annotations
import hashlib, json, time, unicodedata
from dataclasses import dataclass, asdict, field

# ---------------------------------------------------------------- I-JSON canonicalization (fix C)
class CanonError(ValueError): pass

MAX_SAFE_INT = 2**53 - 1          # IEEE-754 double-safe integer range (RFC 8785 constraint)

def _validate(o, path="$"):
    if isinstance(o, bool) or o is None:
        return
    if isinstance(o, int):
        if abs(o) > MAX_SAFE_INT:
            raise CanonError(f"{path}: int {o} outside IEEE-754 safe range — use a decimal string")
        return
    if isinstance(o, float):
        raise CanonError(f"{path}: float forbidden in a hashed payload — use int minor units or a "
                         f"decimal string (0.1+0.2 != 0.3 is not a hash-stable fact)")
    if isinstance(o, str):
        if unicodedata.normalize("NFC", o) != o:
            raise CanonError(f"{path}: string is not Unicode NFC — normalize at the input contract")
        return
    if isinstance(o, list):
        for i, v in enumerate(o): _validate(v, f"{path}[{i}]")
        return
    if isinstance(o, dict):
        for k, v in o.items():
            if not isinstance(k, str):
                raise CanonError(f"{path}: non-string key {k!r}")
            if unicodedata.normalize("NFC", k) != k:
                raise CanonError(f"{path}: key {k!r} is not Unicode NFC")
            _validate(v, f"{path}.{k}")
        return
    raise CanonError(f"{path}: type {type(o).__name__} is not I-JSON")

def canon_bytes(obj) -> bytes:
    """RFC 8785-style canonical JSON, but only over I-JSON-safe input. Rejects rather than silently
    hashing something whose bytes differ across implementations."""
    _validate(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")

def canon_from_json_text(text: str) -> bytes:
    """Parse untrusted JSON text and reject DUPLICATE KEYS (json.loads silently keeps the last one,
    which is exactly how two parties end up hashing 'the same' object differently)."""
    def _no_dupes(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen: raise CanonError(f"duplicate key {k!r} — not I-JSON")
            seen.add(k)
        return dict(pairs)
    return canon_bytes(json.loads(text, object_pairs_hook=_no_dupes))

def minor_units(amount: str, scale: int) -> int:
    """Money -> int in minimal units (the only hash-stable way to carry it)."""
    from decimal import Decimal
    q = (Decimal(amount) * (10 ** scale)).to_integral_value()
    if abs(int(q)) > MAX_SAFE_INT: raise CanonError("amount too large for a safe int; use a string")
    return int(q)

# ---------------------------------------------------------------- RFC 9162 Merkle (fix A)
def _leaf_hash(b: bytes) -> bytes:  return hashlib.sha256(b"\x00" + b).digest()
def _node_hash(l: bytes, r: bytes) -> bytes: return hashlib.sha256(b"\x01" + l + r).digest()

def _split(n: int) -> int:
    """Largest power of two strictly less than n (RFC 6962 size-determined split)."""
    k = 1
    while k * 2 < n: k *= 2
    return k

def _mth(leaves: list) -> bytes:
    n = len(leaves)
    if n == 0: return hashlib.sha256(b"").digest()      # RFC 6962: MTH({}) = SHA-256()
    if n == 1: return _leaf_hash(leaves[0])
    k = _split(n)
    return _node_hash(_mth(leaves[:k]), _mth(leaves[k:]))

def merkle_root(objs) -> str:
    """Unique root per LIST (not per multiset): [a,b,c] and [a,b,c,c] now differ, as they must."""
    return _mth([canon_bytes(o) for o in objs]).hex()

# ---------------------------------------------------------------- manifest + anchoring (fix B)
@dataclass
class Manifest:
    """What actually gets committed. Binding root ALONE is not enough: the round, the ruleset, the
    snapshot and the count must all be inside one signed object, or they can be swapped."""
    round_id: str
    ruleset_hash: str
    snapshot_hash: str
    root: str
    count: int
    close_policy_version: str = "v1"
    null_reason: str = ""            # non-empty => this is an explicit NULL-MANIFEST
    def digest(self) -> str:
        return hashlib.sha256(canon_bytes(asdict(self))).hexdigest()

class AnchorError(RuntimeError): pass

class NullAnchor:
    """Explicitly NOT an anchor. Refuses, loudly. Present so that 'we forgot to configure an anchor'
    can never silently degrade into 'we published a commitment to ourselves and called it proof'."""
    name = "none"
    def stamp(self, digest: str) -> dict:
        raise AnchorError("no external time anchor: a self-published commitment does not prove WHEN "
                          "it was published (RFC 3161 TSA / transparency log / OTS required)")

class ExternalAnchor:
    """Adapter for a real external time source. `transport(digest) -> proof dict` is injected:
    RFC 3161 TSA (fast, trusts the TSA key+clock), a transparency log (public append-only; note
    Rekor v1 integratedTime is NOT independently verifiable on its own), or OpenTimestamps/Bitcoin
    (weakest trust, slowest finality). Use several: fast operational proof + slow independent proof."""
    def __init__(self, name: str, transport):
        self.name = name; self._transport = transport
    def stamp(self, digest: str) -> dict:
        try:
            proof = self._transport(digest)
        except Exception as e:
            raise AnchorError(f"anchor {self.name} failed: {type(e).__name__}") from None
        if not proof or "time" not in proof:
            raise AnchorError(f"anchor {self.name} returned no verifiable time")
        return {"anchor": self.name, "digest": digest, **proof}

def anchored_commit(manifest: Manifest, anchors: list) -> dict:
    """Fail-closed: a commitment is only 'anchored' if at least one EXTERNAL anchor stamped it.
    Without one we must say UNANCHORED out loud rather than claim we proved anything."""
    d = manifest.digest()
    if not anchors:
        raise AnchorError("refusing to publish an unanchored commitment as proof")
    stamps = [a.stamp(d) for a in anchors]
    return {"manifest": asdict(manifest), "digest": d, "anchors": stamps, "anchored": True}

def verify_manifest(published: dict, trades) -> dict:
    """Third-party check: recompute root+count from the revealed set and re-derive the digest."""
    m = published["manifest"]
    root = merkle_root(trades); count = len(trades)
    root_ok = (root == m["root"]); count_ok = (count == m["count"])
    digest_ok = (Manifest(**m).digest() == published["digest"])
    anchored = bool(published.get("anchored") and published.get("anchors"))
    return {"ok": root_ok and count_ok and digest_ok and anchored,
            "root_ok": root_ok, "count_ok": count_ok, "digest_ok": digest_ok, "anchored": anchored,
            "reason": ("complete" if (root_ok and count_ok and digest_ok and anchored) else
                       "unanchored (no independent time)" if not anchored else
                       "trade dropped/truncated" if not count_ok else
                       "manifest tampered" if not digest_ok else "trade altered")}

# ---------------------------------------------------------------- omission (fix B, second half)
class RoundSchedule:
    """Pre-registered round cadence. Anchoring stops backdating; it does NOT stop the operator from
    silently never publishing an inconvenient round. A public schedule + mandatory NULL-MANIFEST
    makes omission detectable by anyone."""
    def __init__(self, round_ids):
        self._scheduled = list(round_ids)
        self._published = {}
    def publish(self, round_id: str, manifest_digest: str):
        if round_id not in self._scheduled:
            raise AnchorError(f"round {round_id} was never pre-registered (unscheduled publication)")
        self._published[round_id] = {"digest": manifest_digest, "null": False, "ts": time.time()}
    def publish_null(self, round_id: str, reason: str):
        if not reason: raise AnchorError("a NULL-MANIFEST requires an explicit public reason")
        self._published[round_id] = {"digest": None, "null": True, "reason": reason, "ts": time.time()}
    def audit(self) -> dict:
        missing = [r for r in self._scheduled if r not in self._published]
        return {"scheduled": len(self._scheduled), "published": len(self._published),
                "missing": missing, "complete": not missing,
                "reason": "complete" if not missing else f"OMISSION: {missing} scheduled but never published"}

# ---------------------------------------------------------------- selective abort (fix D)
class NonRevealForfeit(RuntimeError): pass

class ThresholdCommittee:
    """Model of a threshold-decryption committee (production: Shutter / drand style, t-of-n shares).
    Modelled here with an injectable opener so the ARENA LOGIC is testable without shipping a
    half-baked crypto implementation. What matters for the refutation is the property, not the curve:
    the payload can be opened WITHOUT the agent's cooperation once the deadline passes."""
    def __init__(self, opener, threshold: int = 2, shares: int = 3):
        self._opener = opener; self.threshold = threshold; self.shares = shares
    def seal(self, payload_bytes: bytes) -> bytes:
        return self._opener.seal(payload_bytes)
    def open(self, ciphertext: bytes, shares_present: int) -> bytes:
        if shares_present < self.threshold:
            raise NonRevealForfeit(f"committee below threshold ({shares_present}/{self.threshold})")
        return self._opener.open(ciphertext)

class ForcedRevealRound:
    """Plain commit-reveal is refuted: a contestant can hide a losing decision by simply never
    revealing it, converting 'I lost' into 'I didn't participate' (the last-revealer attack from the
    randomness-beacon literature). Fix: at commit time the agent submits BOTH H(payload||salt) AND a
    ciphertext sealed to the committee. After the deadline the committee opens it regardless of the
    agent. Non-reveal becomes FORFEIT — never non-participation."""
    def __init__(self, committee: ThresholdCommittee):
        self._c = committee; self._commits = {}; self._revealed = {}

    def commit(self, agent_id: str, payload: dict, salt: str) -> dict:
        body = canon_bytes(payload) + salt.encode()
        h = hashlib.sha256(body).hexdigest()
        self._commits[agent_id] = {"hash": h, "ct": self._c.seal(body), "salt_len": len(salt)}
        return {"agent_id": agent_id, "hash": h, "sealed": True}

    def reveal(self, agent_id: str, payload: dict, salt: str) -> dict:
        c = self._commits.get(agent_id)
        if not c: raise NonRevealForfeit(f"{agent_id}: nothing committed")
        if hashlib.sha256(canon_bytes(payload) + salt.encode()).hexdigest() != c["hash"]:
            raise NonRevealForfeit(f"{agent_id}: reveal does not match the commitment")
        self._revealed[agent_id] = {"payload": payload, "how": "voluntary"}
        return self._revealed[agent_id]

    def settle(self, shares_present: int = 3) -> dict:
        """After the deadline: everything that was committed gets opened, one way or the other."""
        out = {}
        for aid, c in self._commits.items():
            if aid in self._revealed:
                out[aid] = {"status": "REVEALED", **self._revealed[aid]}
                continue
            try:
                body = self._c.open(c["ct"], shares_present)
                payload = json.loads(body[: len(body) - c["salt_len"]].decode())
                out[aid] = {"status": "FORCE_OPENED", "payload": payload, "how": "committee",
                            "note": "non-reveal did NOT become non-participation"}
            except NonRevealForfeit as e:
                out[aid] = {"status": "FORFEIT", "reason": str(e)}
        return out
