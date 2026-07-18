//! Closure v1.1 KD-07: canonical serialization contract. RFC 8785 (JCS) canonical bytes
//! -> SHA-256. Two independent impls must produce identical bytes and digest.
use anyhow::Result;
use serde::Serialize;

pub fn canonical_bytes<T: Serialize>(v: &T) -> Result<Vec<u8>> {
    Ok(serde_json_canonicalizer::to_vec(v)?)
}
