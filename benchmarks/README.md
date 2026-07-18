# benchmarks/
Харнессы (D2 §benchmark plan): checkpoint create/replay; handoff payload size; sandbox cold/warm/teardown; hot-path: direct call vs bounded channel vs SPSC (p50/p95/p99/p99.9, allocs); kill-switch visibility.
Обязательная запись окружения: CPU, NUMA, OS, kernel, компилятор, pinning, governor, SMT.
Falsification: direct call <500нс + zero-alloc на 1M order intents → ring buffer отвергнут навсегда (ADR-D5).
Кастомный MPMC из старого Gemini-концепта — хранить только как анти-пример в тестах.
