"""PFI auto-pull — full automation. Reads the outputs of the 4 enabled ContinuityOS schedules
(pfi-frontier-sweep -> pfi_signals.json, pfi-robotics-beat -> robotics_beat_signals.json, plus any
machine-economy / trading digests) and runs them through the MAWorld untrusted-input pipeline
(pfi_bridge -> input_guard + memory_provenance). Emits a PROPOSED-intel feed the Cockpit reads.
No manual paste. Degrades gracefully on missing/partial files (never raises)."""
from __future__ import annotations
import json, os, stat, time
from types import MappingProxyType
from maworld_core.pfi_bridge import from_frontier_rows, ingest

SOURCES = MappingProxyType({  # schedule -> its signal store file
    "pfi-frontier-sweep": "pfi_signals.json",
    "pfi-robotics-beat": "robotics_beat_signals.json",
    "cosmos3": "cosmos3_signals.json",
})
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_ROWS_PER_SOURCE = 1000

def _windows_final_path(fd: int) -> str:
    """Resolve the path of the already-open handle; unavailable platforms fail closed."""
    if os.name != "nt":
        raise OSError("Windows handle resolution requested on another platform")
    import ctypes
    import msvcrt

    handle = msvcrt.get_osfhandle(fd)
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(  # type: ignore[attr-defined]
        handle, buffer, len(buffer), 0
    )
    if not length or length >= len(buffer):
        raise OSError("cannot resolve opened source path")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return os.path.realpath(value)


def _load(root, filename):
    if not isinstance(filename, str) or os.path.basename(filename) != filename:
        return []
    fd = root_fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        if os.name == "posix":
            root_fd = os.open(root, flags | getattr(os, "O_DIRECTORY", 0))
            fd = os.open(
                filename,
                flags | getattr(os, "O_NOFOLLOW", 0),
                dir_fd=root_fd,
            )
        elif os.name == "nt":
            fd = os.open(os.path.join(root, filename), flags)
            final_path = _windows_final_path(fd)
            if os.path.commonpath((root, final_path)) != root:
                return []
        else:
            return []
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
            return []
        with os.fdopen(fd, "rb", closefd=True) as handle:
            fd = -1
            payload = handle.read(MAX_SOURCE_BYTES + 1)
        if len(payload) > MAX_SOURCE_BYTES:
            return []
        data = json.loads(
            payload.decode("utf-8", errors="strict"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value: {value}")
            ),
        )
        rows = data if isinstance(data, list) else data.get("signals", []) if isinstance(data, dict) else []
        return rows[:MAX_ROWS_PER_SOURCE] if isinstance(rows, list) else []
    except Exception:
        return []
    finally:
        if fd >= 0:
            os.close(fd)
        if root_fd >= 0:
            os.close(root_fd)

def pull(*, pfi_dir, mem_key):
    """Read fixed filenames beneath one explicit root and return proposals only."""
    if not isinstance(pfi_dir, (str, os.PathLike)):
        raise ValueError("explicit pfi_dir is required")
    if not isinstance(mem_key, bytes) or len(mem_key) < 16:
        raise ValueError("explicit provenance key of at least 16 bytes is required")
    pfi_dir = os.path.realpath(os.path.abspath(os.fspath(pfi_dir)))
    all_rows, per_source = [], {}
    for sched, fname in SOURCES.items():
        rows = _load(pfi_dir, fname)
        per_source[sched] = len(rows); all_rows += rows
    signals = from_frontier_rows(all_rows)
    res = ingest(signals, mem_key, source_label="pfi:autopull")
    feed = {"generated_at": time.time(), "per_source": per_source,
            "proposed": len(res["proposed_memory"]), "actions": len(res["action_proposals"]),
            "rejected_injection": len(res["rejected_injection"]),
            "note": "PROPOSED frontier intel (confidence-scored), NOT canon; actions are gated proposals",
            "items": res["proposed_memory"][:50], "action_proposals": res["action_proposals"][:50]}
    return feed

def write_feed(out_path, pfi_dir=None):
    """Legacy direct-write API is disabled; route persistence through Action Authority."""
    raise PermissionError("direct PFI feed writes are disabled; use an authorized effect handler")
