//! Parser router (closure v1.1 §2.7 + report Tier2 sandbox). Format-aware routing:
//! deterministic native parsers for safe text formats; rich/binary formats are NOT parsed
//! in-process -> they are routed to the sandbox (Tier2 gVisor in prod; the sandbox-broker owns
//! execution). The router decision itself is deterministic and testable.
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ParserRoute {
    NativeMarkdown,
    NativeText,
    NativeSource,
    SandboxRequired, // pdf/docx/xlsx/images/unknown -> disposable sandbox, no in-process parse
}

pub fn route(media_type: &str) -> ParserRoute {
    match media_type {
        "text/markdown" => ParserRoute::NativeMarkdown,
        "text/plain" => ParserRoute::NativeText,
        "text/x-rust" | "text/x-python" | "application/json" | "text/csv" => {
            ParserRoute::NativeSource
        }
        _ => ParserRoute::SandboxRequired, // pdf, docx, xlsx, images, unknown
    }
}
