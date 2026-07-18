//! Extraction events into the KF hash-chained ledger (build-seq E: intake -> KF events).
//! Same append-only + prev-hash pattern as kf-intake meta.rs. Emits raw_blob.observed,
//! occurrence.created and extraction.created so the identity flows into Knowledge Foundry.
use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};

const GENESIS: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const MAX_LEDGER_BYTES: u64 = 64 * 1024 * 1024;
const MAX_EVENT_BYTES: usize = 1024 * 1024;

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Event {
    seq: u64,
    kind: String,
    payload: serde_json::Value,
    prev_hash: String,
    hash: String,
}

struct LedgerTail {
    last_hash: String,
    seq: u64,
}

impl LedgerTail {
    fn genesis() -> Self {
        Self {
            last_hash: GENESIS.to_string(),
            seq: 0,
        }
    }
}

fn allowed_kind(kind: &str) -> bool {
    matches!(
        kind,
        "raw_blob.observed" | "occurrence.created" | "extraction.created"
    )
}

fn hash_event(
    prev_hash: &str,
    kind: &str,
    seq: u64,
    payload: &serde_json::Value,
) -> Result<String> {
    let body = serde_json::to_string(payload)?;
    let mut h = Sha256::new();
    h.update(prev_hash.as_bytes());
    h.update(kind.as_bytes());
    h.update(seq.to_string().as_bytes());
    h.update(body.as_bytes());
    Ok(hex::encode(h.finalize()))
}

fn validate_ledger(path: &Path) -> Result<LedgerTail> {
    let link_metadata = match std::fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(LedgerTail::genesis()),
        Err(error) => return Err(error.into()),
    };
    if link_metadata.file_type().is_symlink() || !link_metadata.is_file() {
        bail!("event ledger must be a regular, non-symlink file");
    }
    if link_metadata.len() > MAX_LEDGER_BYTES {
        bail!("event ledger exceeds {MAX_LEDGER_BYTES} byte limit");
    }
    let mut file = File::open(path).context("open event ledger for validation")?;
    let opened_size = file.metadata()?.len();
    if opened_size > MAX_LEDGER_BYTES {
        bail!("opened event ledger exceeds {MAX_LEDGER_BYTES} byte limit");
    }
    let capacity = usize::try_from(opened_size)
        .context("event ledger cannot fit in memory on this platform")?;
    let mut bytes = Vec::with_capacity(capacity);
    Read::by_ref(&mut file)
        .take(MAX_LEDGER_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 != opened_size || bytes.len() as u64 > MAX_LEDGER_BYTES {
        bail!("event ledger changed or exceeded its limit while being read");
    }
    let mut tail = LedgerTail::genesis();
    if bytes.is_empty() {
        return Ok(tail);
    }
    if !bytes.ends_with(b"\n") {
        bail!("event ledger has a partial terminal line");
    }
    for (line_index, encoded_line) in bytes[..bytes.len() - 1]
        .split(|byte| *byte == b'\n')
        .enumerate()
    {
        let line_number = line_index + 1;
        if encoded_line.is_empty() {
            bail!("empty event ledger line {line_number}");
        }
        if encoded_line.len() > MAX_EVENT_BYTES {
            bail!("event ledger line {line_number} exceeds {MAX_EVENT_BYTES} byte limit");
        }
        let line = std::str::from_utf8(encoded_line)
            .with_context(|| format!("event ledger line {line_number} is not UTF-8"))?;

        let event: Event = serde_json::from_str(line)
            .with_context(|| format!("malformed event ledger line {line_number}"))?;
        if !allowed_kind(&event.kind) {
            bail!("unknown event kind at line {line_number}: {}", event.kind);
        }
        if !event.payload.is_object() {
            bail!("event payload must be an object at line {line_number}");
        }

        let expected_seq = tail.seq.checked_add(1).context("event sequence overflow")?;
        if event.seq != expected_seq {
            bail!(
                "non-contiguous event sequence at line {line_number}: expected {expected_seq}, got {}",
                event.seq
            );
        }
        if event.prev_hash != tail.last_hash {
            bail!("previous hash mismatch at event sequence {}", event.seq);
        }

        let expected_hash = hash_event(&event.prev_hash, &event.kind, event.seq, &event.payload)?;
        if event.hash != expected_hash {
            bail!("event hash mismatch at event sequence {}", event.seq);
        }

        tail.last_hash = event.hash;
        tail.seq = event.seq;
    }
    Ok(tail)
}

fn with_ledger_lock<T>(path: &Path, operation: impl FnOnce() -> Result<T>) -> Result<T> {
    let file_name = path
        .file_name()
        .and_then(|name| name.to_str())
        .context("event ledger path has no valid file name")?;
    let lock_path = path.with_file_name(format!("{file_name}.lock"));
    match std::fs::symlink_metadata(&lock_path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            bail!("event ledger lock must be a regular, non-symlink file")
        }
        Ok(_) => {}
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let lock_file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(&lock_path)?;
    if !lock_file.metadata()?.is_file() {
        bail!("opened event ledger lock is not a regular file");
    }
    lock_file.lock()?;
    let operation_result = operation();
    let unlock_result = lock_file.unlock();
    match (operation_result, unlock_result) {
        (Ok(value), Ok(())) => Ok(value),
        (Err(error), Ok(())) => Err(error),
        (Ok(_), Err(error)) => Err(error.into()),
        (Err(error), Err(unlock_error)) => Err(error.context(format!(
            "event ledger operation failed and unlock also failed: {unlock_error}"
        ))),
    }
}

pub struct EventLedger {
    path: PathBuf,
    last_hash: String,
    seq: u64,
}

impl EventLedger {
    pub fn open(path: impl Into<PathBuf>) -> Result<Self> {
        let path = path.into();
        let tail = with_ledger_lock(&path, || validate_ledger(&path))?;
        Ok(Self {
            path,
            last_hash: tail.last_hash,
            seq: tail.seq,
        })
    }

    pub fn append<T: Serialize>(&mut self, kind: &str, payload: &T) -> Result<String> {
        if !allowed_kind(kind) {
            bail!("unknown event kind: {kind}");
        }

        let path = self.path.clone();
        with_ledger_lock(&path, || {
            let disk = validate_ledger(&path)?;
            if disk.seq != self.seq || disk.last_hash != self.last_hash {
                bail!("stale event-ledger state; reopen before appending");
            }
            let payload = serde_json::to_value(payload)?;
            if !payload.is_object() {
                bail!("event payload must be an object");
            }
            let next_seq = self.seq.checked_add(1).context("event sequence overflow")?;
            let hash = hash_event(&self.last_hash, kind, next_seq, &payload)?;
            let event = Event {
                seq: next_seq,
                kind: kind.to_string(),
                payload,
                prev_hash: self.last_hash.clone(),
                hash: hash.clone(),
            };
            let mut encoded = serde_json::to_vec(&event)?;
            if encoded.len() > MAX_EVENT_BYTES {
                bail!("event exceeds {MAX_EVENT_BYTES} byte limit");
            }
            let disk_size = std::fs::metadata(&path).map_or(0, |metadata| metadata.len());
            if disk_size.saturating_add(encoded.len() as u64 + 1) > MAX_LEDGER_BYTES {
                bail!("event ledger would exceed {MAX_LEDGER_BYTES} byte limit");
            }
            encoded.push(b'\n');

            let mut file = OpenOptions::new().create(true).append(true).open(&path)?;
            file.write_all(&encoded)?;
            file.sync_data()?;

            self.seq = next_seq;
            self.last_hash = hash.clone();
            Ok(hash)
        })
    }

    pub fn verify(&self) -> Result<(bool, u64)> {
        let tail = with_ledger_lock(&self.path, || validate_ledger(&self.path))?;
        Ok((true, tail.seq))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("kf-parser-ledger-{label}-{}", uuid::Uuid::now_v7()));
            std::fs::create_dir_all(&path).expect("create test directory");
            Self(path)
        }

        fn ledger_path(&self) -> PathBuf {
            self.0.join("events.jsonl")
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn make_event(seq: u64, kind: &str, payload: serde_json::Value, prev_hash: &str) -> Event {
        let hash = hash_event(prev_hash, kind, seq, &payload).expect("hash event");
        Event {
            seq,
            kind: kind.to_string(),
            payload,
            prev_hash: prev_hash.to_string(),
            hash,
        }
    }

    fn write_events(path: &Path, events: &[Event]) {
        let lines = events
            .iter()
            .map(|event| serde_json::to_string(event).expect("serialize event"))
            .collect::<Vec<_>>()
            .join("\n");
        std::fs::write(path, format!("{lines}\n")).expect("write ledger");
    }

    #[test]
    fn valid_ledger_reopens_at_verified_tail() {
        let dir = TestDir::new("valid");
        let path = dir.ledger_path();
        let mut ledger = EventLedger::open(&path).expect("open empty ledger");
        ledger
            .append(
                "raw_blob.observed",
                &serde_json::json!({"sha256": "a".repeat(64)}),
            )
            .expect("append first event");
        ledger
            .append(
                "occurrence.created",
                &serde_json::json!({"source_native_id": "source-1"}),
            )
            .expect("append second event");
        drop(ledger);

        let reopened = EventLedger::open(&path).expect("reopen valid ledger");
        assert_eq!(reopened.seq, 2);
        assert_eq!(reopened.verify().expect("verify ledger"), (true, 2));
    }

    #[test]
    fn tampered_tail_is_rejected_instead_of_resumed() {
        let dir = TestDir::new("tampered");
        let path = dir.ledger_path();
        let first = make_event(
            1,
            "raw_blob.observed",
            serde_json::json!({"sha256": "a".repeat(64)}),
            GENESIS,
        );
        let mut second = make_event(
            2,
            "extraction.created",
            serde_json::json!({"blocks": 1}),
            &first.hash,
        );
        let replacement = if second.hash.starts_with('f') {
            "e"
        } else {
            "f"
        };
        second.hash.replace_range(0..1, replacement);
        write_events(&path, &[first, second]);

        assert!(EventLedger::open(&path).is_err());
    }

    #[test]
    fn sequence_gap_is_rejected_even_with_matching_hash() {
        let dir = TestDir::new("sequence");
        let event = make_event(
            2,
            "raw_blob.observed",
            serde_json::json!({"sha256": "a".repeat(64)}),
            GENESIS,
        );
        write_events(&dir.ledger_path(), &[event]);

        assert!(EventLedger::open(dir.ledger_path()).is_err());
    }

    #[test]
    fn unknown_kind_is_rejected_even_with_matching_hash() {
        let dir = TestDir::new("kind");
        let event = make_event(1, "future.event", serde_json::json!({}), GENESIS);
        write_events(&dir.ledger_path(), &[event]);

        assert!(EventLedger::open(dir.ledger_path()).is_err());
    }

    #[test]
    fn extra_event_field_is_rejected() {
        let dir = TestDir::new("extra-field");
        let event = make_event(
            1,
            "raw_blob.observed",
            serde_json::json!({"sha256": "a".repeat(64)}),
            GENESIS,
        );
        let mut value = serde_json::to_value(event).expect("serialize event");
        value
            .as_object_mut()
            .expect("event object")
            .insert("unexpected".to_string(), serde_json::json!(true));
        std::fs::write(
            dir.ledger_path(),
            format!("{}\n", serde_json::to_string(&value).expect("encode event")),
        )
        .expect("write ledger");

        assert!(EventLedger::open(dir.ledger_path()).is_err());
    }

    #[test]
    fn empty_and_malformed_lines_are_rejected() {
        let empty_dir = TestDir::new("empty-line");
        std::fs::write(empty_dir.ledger_path(), "\n").expect("write empty line");
        assert!(EventLedger::open(empty_dir.ledger_path()).is_err());

        let malformed_dir = TestDir::new("malformed-line");
        std::fs::write(malformed_dir.ledger_path(), "{not-json}\n").expect("write malformed line");
        assert!(EventLedger::open(malformed_dir.ledger_path()).is_err());
    }

    #[test]
    fn partial_and_oversized_event_lines_are_rejected() {
        let partial_dir = TestDir::new("partial-line");
        std::fs::write(partial_dir.ledger_path(), b"{\"seq\":1}").expect("write partial line");
        assert!(EventLedger::open(partial_dir.ledger_path()).is_err());

        let oversized_dir = TestDir::new("oversized-line");
        let mut line = vec![b'a'; MAX_EVENT_BYTES + 1];
        line.push(b'\n');
        std::fs::write(oversized_dir.ledger_path(), line).expect("write oversized line");
        assert!(EventLedger::open(oversized_dir.ledger_path()).is_err());
    }

    #[test]
    fn failed_write_does_not_advance_in_memory_tail() {
        let dir = TestDir::new("write-failure");
        let blocked_path = dir.0.join("blocked");
        std::fs::create_dir(&blocked_path).expect("create directory at ledger path");
        let mut ledger = EventLedger {
            path: blocked_path,
            last_hash: GENESIS.to_string(),
            seq: 0,
        };

        assert!(ledger
            .append("raw_blob.observed", &serde_json::json!({"sha256": "a"}))
            .is_err());
        assert_eq!(ledger.seq, 0);
        assert_eq!(ledger.last_hash, GENESIS);
    }

    #[test]
    fn rejected_append_does_not_create_or_advance_ledger() {
        let dir = TestDir::new("bad-append");
        let path = dir.ledger_path();
        let mut ledger = EventLedger::open(&path).expect("open empty ledger");

        assert!(ledger
            .append("unknown.event", &serde_json::json!({}))
            .is_err());
        assert_eq!(ledger.seq, 0);
        assert_eq!(ledger.last_hash, GENESIS);
        assert!(!path.exists());

        let oversized = "x".repeat(MAX_EVENT_BYTES);
        assert!(ledger
            .append(
                "raw_blob.observed",
                &serde_json::json!({"payload": oversized}),
            )
            .is_err());
        assert_eq!(ledger.seq, 0);
        assert!(!path.exists());
    }

    #[test]
    fn stale_concurrent_writer_cannot_fork_the_ledger() {
        use std::sync::{Arc, Barrier};

        let dir = TestDir::new("concurrent");
        let path = Arc::new(dir.ledger_path());
        let ready = Arc::new(Barrier::new(3));
        let mut workers = Vec::new();
        for source in ["source-a", "source-b"] {
            let path = Arc::clone(&path);
            let ready = Arc::clone(&ready);
            workers.push(std::thread::spawn(move || {
                let mut ledger = EventLedger::open(path.as_path()).expect("open worker ledger");
                ready.wait();
                ledger.append("raw_blob.observed", &serde_json::json!({"source": source}))
            }));
        }
        ready.wait();
        let results = workers
            .into_iter()
            .map(|worker| worker.join().expect("worker did not panic"))
            .collect::<Vec<_>>();
        assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
        assert_eq!(results.iter().filter(|result| result.is_err()).count(), 1);

        let ledger = EventLedger::open(path.as_path()).expect("reopen surviving ledger");
        assert_eq!(ledger.verify().expect("verify surviving ledger"), (true, 1));
    }
}
