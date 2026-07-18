//! Closure v1.1 §2.1 identity split: RawBlob (global dedup) != Occurrence (project access)
//! != Version. Access is via occurrence/project, never global blob identity alone.
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RawBlob {
    pub blob_id: String,
    pub sha256: String,
    pub byte_size: u64,
    pub storage_uri: String,
    pub media_type_detected: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactOccurrence {
    pub occurrence_id: String,
    pub project_id: String,
    pub source_system_id: String,
    pub source_native_id: String, // stable per-source key (e.g. observed path)
    pub observed_path: String,
    pub blob_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArtifactVersion {
    pub version_id: String,
    pub occurrence_id: String,
    pub blob_id: String,
    pub source_revision_key: String,
    pub parent_version_id: Option<String>,
}
