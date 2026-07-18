"""Non-authoritative, immutable evaluation registry.

An evaluation result can make a rollout *eligible for an authority proposal*;
it can never return ``PROMOTE``.  Golden sets and evaluator callbacks are fixed
at construction, records are immutable and retained internally, and a baseline
can only be established once from an exact perfect record produced by this
registry.  A rollout still needs the canonical Action Authority boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping


def _canonical(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@dataclass(frozen=True)
class GoldenSet:
    dataset_id: str
    cases: tuple | list
    version: str = "1"


@dataclass(frozen=True)
class EvalRecord:
    eval_id: str
    target_type: str
    target_id: str
    prompt_version: str
    model_binding: str
    dataset_id: str
    dataset_digest: str
    evaluator_id: str
    pass_rate: float
    passed_cases: int
    total_cases: int
    regression: bool
    baseline_id: str | None
    drift_significant: bool
    created_at: int
    authoritative: bool = False

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.__dict__).encode()).hexdigest()


class EvalRegistry:
    def __init__(
        self,
        golden_sets: Mapping[str, GoldenSet],
        evaluators: Mapping[str, Callable[[object], object]],
        *,
        clock=time.time,
    ):
        if not golden_sets or not evaluators:
            raise ValueError("fixed golden sets and evaluator registry are required")
        frozen_sets = {}
        for dataset_id, supplied in golden_sets.items():
            if dataset_id != supplied.dataset_id or not dataset_id or not supplied.version:
                raise ValueError("golden-set identity/version mismatch")
            try:
                cases = json.loads(_canonical(list(supplied.cases)))
            except (TypeError, ValueError) as exc:
                raise ValueError("golden cases must be canonical JSON") from exc
            if not cases or any(not isinstance(c, dict) or set(c) != {"input", "expected"} for c in cases):
                raise ValueError("golden set must contain non-empty input/expected cases")
            frozen_sets[dataset_id] = (
                supplied.version,
                tuple(_canonical(c) for c in cases),
                hashlib.sha256(_canonical({"version": supplied.version, "cases": cases}).encode()).hexdigest(),
            )
        if any(not isinstance(k, str) or not k or not callable(v) for k, v in evaluators.items()):
            raise ValueError("evaluator ids and callbacks must be fixed and valid")
        self._golden = MappingProxyType(frozen_sets)
        self._evaluators = MappingProxyType(dict(evaluators))
        self._clock = clock
        self._baselines: dict[str, tuple[str, float, str]] = {}
        self._records: dict[str, tuple[str, EvalRecord]] = {}

    def run(
        self,
        target_type: str,
        target_id: str,
        prompt_version: str,
        model_binding: str,
        dataset_id: str,
        evaluator_id: str,
        *,
        regression_budget: float = 0.0,
    ) -> EvalRecord:
        if target_type not in {"prompt", "model_binding"}:
            raise ValueError("unsupported target_type")
        if not all(isinstance(v, str) and v.strip() for v in
                   (target_id, prompt_version, model_binding, dataset_id, evaluator_id)):
            raise ValueError("evaluation identities must be non-empty strings")
        try:
            budget = float(regression_budget)
        except (TypeError, ValueError) as exc:
            raise ValueError("regression_budget must be finite in [0,1]") from exc
        if not math.isfinite(budget) or not 0.0 <= budget <= 1.0:
            raise ValueError("regression_budget must be finite in [0,1]")
        if dataset_id not in self._golden or evaluator_id not in self._evaluators:
            raise KeyError("unknown fixed dataset or evaluator")
        _version, encoded_cases, dataset_digest = self._golden[dataset_id]
        evaluator = self._evaluators[evaluator_id]
        passed = 0
        for encoded in encoded_cases:
            case = json.loads(encoded)
            passed += evaluator(case["input"]) == case["expected"]
        total = len(encoded_cases)
        rate = passed / total
        baseline = self._baselines.get(target_id)
        baseline_rate = baseline[1] if baseline else None
        regression = baseline_rate is not None and (baseline_rate - rate) > budget
        drift = baseline_rate is not None and abs(baseline_rate - rate) > 0.10
        record = EvalRecord(
            eval_id="eval-" + uuid.uuid4().hex,
            target_type=target_type,
            target_id=target_id,
            prompt_version=prompt_version,
            model_binding=model_binding,
            dataset_id=dataset_id,
            dataset_digest=dataset_digest,
            evaluator_id=evaluator_id,
            pass_rate=rate,
            passed_cases=passed,
            total_cases=total,
            regression=regression,
            baseline_id=baseline[0] if baseline else None,
            drift_significant=drift,
            created_at=int(self._clock()),
        )
        self._records[record.eval_id] = (record.digest(), record)
        return record

    def set_baseline(self, target_id: str, record: EvalRecord) -> bool:
        """Pin a perfect internally produced record once; never overwrite it."""
        stored = self._records.get(getattr(record, "eval_id", ""))
        if (
            target_id in self._baselines
            or stored is None
            or stored[0] != record.digest()
            or stored[1] != record
            or record.target_id != target_id
            or record.pass_rate != 1.0
            or record.regression
        ):
            return False
        self._baselines[target_id] = (record.eval_id, record.pass_rate, record.dataset_digest)
        return True

    def gate(self, record: EvalRecord) -> str:
        """Return a non-authoritative eligibility verdict, never promotion authority."""
        stored = self._records.get(getattr(record, "eval_id", ""))
        if stored is None or stored[0] != record.digest() or stored[1] != record:
            return "BLOCK_UNTRUSTED_RECORD"
        baseline = self._baselines.get(record.target_id)
        if baseline is None:
            return "HOLD_NO_BASELINE"
        if record.dataset_digest != baseline[2]:
            return "BLOCK_DATASET_CHANGED"
        if record.regression or record.pass_rate != 1.0:
            return "BLOCK_REGRESSION"
        return "ELIGIBLE_PROPOSAL"
