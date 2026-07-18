"""LifeOS private-agent layer with proposal-only external actions.

LifeOS owns private memory and lifecycle state; it owns no capability verifier,
execution handler, canon writer, or external-effect authority.  World-changing
actions leave this layer only as explicitly non-authoritative proposals.

Persistent state is available only through :class:`LifeStore`.  A store fixes
one real filesystem root and one relative database filename at construction,
rejects traversal and symlink database paths, and is passed to restore as the
same object.  In-memory operation is available only through the explicit
``LifeStore.in_memory()`` helper.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import stat
import time
import uuid
from dataclasses import dataclass


STATES = [
    "SEED", "BOOTSTRAPPING", "ACTIVE", "ENGAGED", "REFLECTING", "LEARNING",
    "RESTING", "HIBERNATING", "RESTORING", "DEGRADED", "QUARANTINED",
    "FORKING", "MERGING", "RETIRING", "ARCHIVED", "TERMINATED",
]
TERMINAL = {"ARCHIVED", "TERMINATED"}
TRANSITIONS = {
    "SEED": {"BOOTSTRAPPING", "TERMINATED"},
    "BOOTSTRAPPING": {"ACTIVE", "DEGRADED", "TERMINATED"},
    "ACTIVE": {
        "ENGAGED", "REFLECTING", "LEARNING", "RESTING", "HIBERNATING",
        "FORKING", "MERGING", "DEGRADED", "QUARANTINED", "RETIRING",
    },
    "ENGAGED": {"ACTIVE", "REFLECTING", "DEGRADED", "QUARANTINED"},
    "REFLECTING": {"ACTIVE", "LEARNING", "RESTING"},
    "LEARNING": {"ACTIVE", "REFLECTING", "RESTING"},
    "RESTING": {"ACTIVE", "HIBERNATING"},
    "HIBERNATING": {"RESTORING"},
    "RESTORING": {"ACTIVE", "DEGRADED", "QUARANTINED"},
    "DEGRADED": {"ACTIVE", "QUARANTINED", "RETIRING"},
    "QUARANTINED": {"RESTORING", "RETIRING", "TERMINATED"},
    "FORKING": {"ACTIVE"},
    "MERGING": {"ACTIVE", "QUARANTINED"},
    "RETIRING": {"ARCHIVED"},
    "ARCHIVED": set(),
    "TERMINATED": set(),
}

POLICY = {
    state: {"model_calls": True, "memory_writes": True, "may_propose_effects": True}
    for state in STATES
}
POLICY["HIBERNATING"] = {
    "model_calls": False, "memory_writes": False, "may_propose_effects": False,
}
POLICY["ARCHIVED"] = POLICY["TERMINATED"] = {
    "model_calls": False, "memory_writes": False, "may_propose_effects": False,
}
POLICY["QUARANTINED"] = {
    "model_calls": True, "memory_writes": False, "may_propose_effects": False,
}
POLICY["RESTING"] = {
    "model_calls": False, "memory_writes": True, "may_propose_effects": False,
}

MEM_LAYERS = ("core", "episodic", "working", "procedural", "relational")


class LifecycleError(RuntimeError):
    pass


class AuthorityViolation(RuntimeError):
    pass


class StorePathViolation(ValueError):
    pass


class LifeStore:
    """SQLite store confined to a root and filename fixed at construction."""

    def __init__(self, root: str, db_name: str):
        if not isinstance(root, str) or not root.strip() or root == ":memory:":
            raise StorePathViolation("explicit filesystem root required")
        self._validate_db_name(db_name)

        requested_root = os.path.abspath(root)
        os.makedirs(requested_root, exist_ok=True)
        resolved_root = os.path.realpath(requested_root)
        if not os.path.isdir(resolved_root):
            raise StorePathViolation("store root must be a directory")

        candidate = os.path.join(resolved_root, db_name)
        self._assert_confined(resolved_root, candidate)
        self._prepare_regular_file(candidate)
        self._assert_confined(resolved_root, candidate)

        self._root = resolved_root
        self._db_name = db_name
        self._db_path = candidate
        self._memory = False
        self._connection = sqlite3.connect(candidate)
        self._initialize()

    @classmethod
    def in_memory(cls) -> "LifeStore":
        """Create an explicit process-local store; no path string is accepted."""

        store = cls.__new__(cls)
        store._root = None
        store._db_name = None
        store._db_path = None
        store._memory = True
        store._connection = sqlite3.connect(":memory:")
        store._initialize()
        return store

    @staticmethod
    def _validate_db_name(db_name: object) -> None:
        if (
            not isinstance(db_name, str)
            or not db_name.strip()
            or db_name in {".", "..", ":memory:"}
            or os.path.isabs(db_name)
            or bool(os.path.splitdrive(db_name)[0])
            or os.path.basename(db_name) != db_name
            or "/" in db_name
            or "\\" in db_name
            or "\x00" in db_name
        ):
            raise StorePathViolation("db_name must be one relative filename")

    @staticmethod
    def _assert_confined(root: str, candidate: str) -> None:
        if os.path.islink(candidate):
            raise StorePathViolation("symlink database paths are forbidden")
        resolved_candidate = os.path.realpath(candidate)
        try:
            confined = os.path.normcase(os.path.commonpath([root, resolved_candidate])) == os.path.normcase(root)
        except ValueError:
            confined = False
        if not confined:
            raise StorePathViolation("database path escapes fixed store root")

    @staticmethod
    def _prepare_regular_file(candidate: str) -> None:
        if not os.path.lexists(candidate):
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(candidate, flags, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        if os.path.islink(candidate):
            raise StorePathViolation("symlink database paths are forbidden")
        try:
            mode = os.stat(candidate, follow_symlinks=False).st_mode
        except OSError as exc:
            raise StorePathViolation(f"database path unavailable: {exc}") from exc
        if not stat.S_ISREG(mode):
            raise StorePathViolation("database path must be a regular file")
        try:
            os.chmod(candidate, 0o600)
        except OSError:
            pass

    @property
    def root(self) -> str | None:
        return self._root

    @property
    def db_path(self) -> str | None:
        return self._db_path

    @property
    def is_memory(self) -> bool:
        return self._memory

    def _initialize(self) -> None:
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS hibernation(
            agent_id TEXT PRIMARY KEY, manifest_sha TEXT, blob TEXT, hibernated_at REAL)"""
        )
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS genealogy(
            child_id TEXT PRIMARY KEY, parent_id TEXT, forked_at REAL)"""
        )
        self._connection.commit()

    def save_hibernation(
        self, agent_id: str, manifest_sha: str, blob: str, hibernated_at: float
    ) -> None:
        self._connection.execute(
            """INSERT INTO hibernation(agent_id,manifest_sha,blob,hibernated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(agent_id) DO UPDATE SET
                 manifest_sha=excluded.manifest_sha,
                 blob=excluded.blob,
                 hibernated_at=excluded.hibernated_at""",
            (agent_id, manifest_sha, blob, hibernated_at),
        )
        self._connection.commit()

    def load_hibernation(self, agent_id: str):
        return self._connection.execute(
            "SELECT manifest_sha, blob FROM hibernation WHERE agent_id=?", (agent_id,)
        ).fetchone()

    def record_genealogy(self, child_id: str, parent_id: str, forked_at: float) -> None:
        self._connection.execute(
            "INSERT OR REPLACE INTO genealogy VALUES(?,?,?)",
            (child_id, parent_id, forked_at),
        )
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()


@dataclass
class Skill:
    name: str
    proficiency: float


@dataclass
class Relationship:
    peer_id: str
    trust: float


class LifeAgent:
    """Private life layer with no external-effect authority."""

    def __init__(
        self,
        name: str,
        store: LifeStore,
        agent_id: str | None = None,
        parent_id: str | None = None,
        model: str = "fable-5",
    ):
        if not isinstance(store, LifeStore):
            raise TypeError("explicit LifeStore required")
        self.agent_id = agent_id or ("agent-" + uuid.uuid4().hex[:12])
        self.name = name
        self.parent_id = parent_id
        self.model = model
        self.state = "SEED"
        self.memory = {layer: [] for layer in MEM_LAYERS}
        self.skills = {}
        self.relationships = {}
        self.temporal = {"historian": [], "present": None, "future_hypotheses": []}
        self.store = store

    def transition(self, new_state: str):
        if self.state in TERMINAL:
            raise LifecycleError(f"terminal state {self.state} cannot transition")
        if new_state not in TRANSITIONS.get(self.state, set()):
            raise LifecycleError(f"invalid {self.state} -> {new_state}")
        self.temporal["historian"].append((time.time(), self.state, new_state))
        self.state = new_state
        return self.state

    def policy(self):
        return POLICY[self.state]

    def remember(self, layer: str, item: object) -> None:
        if layer not in MEM_LAYERS:
            raise ValueError(layer)
        if not self.policy()["memory_writes"]:
            raise LifecycleError(f"memory writes forbidden in {self.state}")
        self.memory[layer].append({"t": time.time(), "item": item})

    def propose_promotion(self, layer: str, index: int) -> dict:
        item = self.memory[layer][index]
        return {
            "kind": "MEMORY_PROMOTION_PROPOSAL",
            "agent_id": self.agent_id,
            "layer": layer,
            "payload": item,
            "authoritative": False,
            "requires": ["memory-governor", "CanonPromoter", "human_approval"],
        }

    def write_canon(self, *_args, **_kwargs):
        raise AuthorityViolation(
            "LifeOS != Control Spine: canon writes are impossible from the life layer"
        )

    def learn_skill(self, name: str, proficiency: float) -> None:
        self.skills[name] = Skill(name, proficiency)

    def bond(self, peer_id: str, trust: float) -> None:
        self.relationships[peer_id] = Relationship(peer_id, trust)

    def propose_external_action(
        self,
        action: str,
        *,
        resource: str = "*",
        payload: object | None = None,
    ) -> dict:
        """Emit data only; no token, verifier, executor, or authority is present."""

        if not self.policy()["may_propose_effects"]:
            raise LifecycleError(f"external-action proposals forbidden in {self.state}")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("action must be a non-empty string")
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("resource must be a non-empty string")
        try:
            copied_payload = json.loads(json.dumps({} if payload is None else payload))
        except (TypeError, ValueError) as exc:
            raise ValueError("proposal payload must be JSON-serializable") from exc
        return {
            "kind": "EXTERNAL_ACTION_PROPOSAL",
            "agent_id": self.agent_id,
            "action": action,
            "resource": resource,
            "payload": copied_payload,
            "authoritative": False,
            "requires": ["ActionVerifier", "ActionExecutor"],
        }

    def act_externally(self, *_args, **_kwargs):
        """Legacy execution-shaped API: permanently fail closed."""

        raise AuthorityViolation(
            "LifeOS cannot execute or validate external actions; emit a proposal instead"
        )

    def _manifest(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "state": self.state,
            "memory": self.memory,
            "model": self.model,
            "skills": {name: vars(skill) for name, skill in self.skills.items()},
            "relationships": {
                name: vars(relationship) for name, relationship in self.relationships.items()
            },
            "temporal": self.temporal,
        }

    def hibernate(self) -> str:
        if self.state != "HIBERNATING":
            self.transition("HIBERNATING")
        blob = json.dumps(self._manifest(), sort_keys=True, separators=(",", ":"))
        manifest_sha = hashlib.sha256(blob.encode()).hexdigest()
        self.store.save_hibernation(self.agent_id, manifest_sha, blob, time.time())
        return manifest_sha

    @classmethod
    def restore(
        cls,
        store: LifeStore,
        agent_id: str,
        *,
        expect_sha: str,
        model: str | None = None,
    ) -> "LifeAgent":
        if not isinstance(store, LifeStore):
            raise TypeError("restore requires the same explicit LifeStore")
        if not isinstance(expect_sha, str) or not expect_sha:
            raise LifecycleError("externally held manifest sha is required")
        row = store.load_hibernation(agent_id)
        if not row:
            raise LifecycleError("no hibernation manifest")
        manifest_sha, blob = row
        computed = hashlib.sha256(blob.encode()).hexdigest()
        if not hmac.compare_digest(computed, manifest_sha):
            raise LifecycleError("manifest tampered")
        if not hmac.compare_digest(manifest_sha, expect_sha):
            raise LifecycleError("manifest sha mismatch")
        try:
            manifest = json.loads(blob)
            if manifest.get("agent_id") != agent_id:
                raise LifecycleError("manifest identity mismatch")
            agent = cls(
                manifest["name"],
                store,
                agent_id=manifest["agent_id"],
                parent_id=manifest["parent_id"],
                model=model or manifest["model"],
            )
            agent.memory = manifest["memory"]
            agent.temporal = manifest["temporal"]
            agent.skills = {
                name: Skill(**value) for name, value in manifest["skills"].items()
            }
            agent.relationships = {
                name: Relationship(**value)
                for name, value in manifest["relationships"].items()
            }
        except LifecycleError:
            raise
        except Exception as exc:
            raise LifecycleError("malformed hibernation manifest") from exc
        agent.state = "RESTORING"
        return agent

    def fork(self, child_name: str) -> "LifeAgent":
        self.transition("FORKING")
        child = LifeAgent(
            child_name,
            LifeStore.in_memory(),
            parent_id=self.agent_id,
            model=self.model,
        )
        child.memory = json.loads(json.dumps(self.memory))
        child.skills = dict(self.skills)
        self.store.record_genealogy(child.agent_id, self.agent_id, time.time())
        self.transition("ACTIVE")
        return child


def model_swap_continuity_test(store: LifeStore) -> dict:
    """Hibernate and restore through one already-confined store object."""

    if not isinstance(store, LifeStore):
        raise TypeError("explicit LifeStore required")
    agent = LifeAgent("hermes", store, model="model-A")
    agent.transition("BOOTSTRAPPING")
    agent.transition("ACTIVE")
    agent.remember("episodic", "met the owner")
    agent.learn_skill("research", 0.8)
    manifest_sha = agent.hibernate()
    restored = LifeAgent.restore(
        store, agent.agent_id, expect_sha=manifest_sha, model="model-B"
    )
    passed = (
        restored.agent_id == agent.agent_id
        and restored.model == "model-B"
        and restored.memory["episodic"][0]["item"] == "met the owner"
        and restored.skills["research"].proficiency == 0.8
        and restored.state == "RESTORING"
    )
    return {
        "model_swap_test_passed": passed,
        "manifest_sha": manifest_sha,
        "agent_id": agent.agent_id,
    }


__all__ = [
    "AuthorityViolation",
    "LifeAgent",
    "LifeStore",
    "LifecycleError",
    "MEM_LAYERS",
    "POLICY",
    "Relationship",
    "STATES",
    "StorePathViolation",
    "Skill",
    "model_swap_continuity_test",
]
