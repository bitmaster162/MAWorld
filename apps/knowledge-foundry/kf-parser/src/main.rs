//! kfparse — Knowledge Foundry parser router + extraction demo (build-seq E+F).
//!   kfparse demo            # routes several media types, extracts MD/TXT natively, emits events
//!   kfparse parse <file>    # parse one file, print extraction JSON
mod events;
mod extract;
mod router;

use anyhow::{bail, Context, Result};
use router::{route, ParserRoute};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};

const MAX_INPUT_BYTES: u64 = 8 * 1024 * 1024;
const BINARY_MAGIC_PREFIXES: &[&[u8]] = &[
    b"%PDF-",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"\x7fELF",
    b"MZ",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"\x1f\x8b",
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
];

#[derive(Serialize)]
struct ExtractionRecord {
    extraction_id: String,
    blob_sha256: String,
    media_type: String,
    route: ParserRoute,
    block_count: usize,
    sandbox_required: bool,
}

fn media_of(path: &Path) -> String {
    match path.extension().and_then(|e| e.to_str()) {
        Some("md") => "text/markdown",
        Some("txt") => "text/plain",
        Some("rs") => "text/x-rust",
        Some("py") => "text/x-python",
        Some("json") => "application/json",
        Some("pdf") => "application/pdf",
        Some("docx") => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        _ => "application/octet-stream",
    }
    .to_string()
}

fn sha256(b: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(b);
    hex::encode(h.finalize())
}

fn read_bounded_regular_file(path: &Path) -> Result<Vec<u8>> {
    let path_metadata = std::fs::symlink_metadata(path)
        .with_context(|| format!("inspect input path {}", path.display()))?;
    if path_metadata.file_type().is_symlink() {
        bail!("input path must not be a symbolic link");
    }
    if !path_metadata.is_file() {
        bail!("input path must be a regular file");
    }
    if path_metadata.len() > MAX_INPUT_BYTES {
        bail!("input exceeds {MAX_INPUT_BYTES} byte limit");
    }

    let file = File::open(path).with_context(|| format!("open input file {}", path.display()))?;
    if !file.metadata()?.is_file() {
        bail!("opened input is not a regular file");
    }

    // The extra byte catches a file that grows after the metadata check.
    let mut bytes = Vec::with_capacity(path_metadata.len() as usize);
    file.take(MAX_INPUT_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_INPUT_BYTES {
        bail!("input exceeds {MAX_INPUT_BYTES} byte limit");
    }
    Ok(bytes)
}

fn has_binary_magic(bytes: &[u8]) -> bool {
    BINARY_MAGIC_PREFIXES
        .iter()
        .any(|magic| bytes.starts_with(magic))
}

fn safe_route(media_type: &str, bytes: &[u8]) -> ParserRoute {
    let candidate = route(media_type);
    if candidate == ParserRoute::SandboxRequired {
        return candidate;
    }

    if bytes.contains(&0) || has_binary_magic(bytes) || std::str::from_utf8(bytes).is_err() {
        ParserRoute::SandboxRequired
    } else {
        candidate
    }
}

fn parse_file(path: &Path) -> Result<serde_json::Value> {
    let bytes = read_bounded_regular_file(path)?;
    let media = media_of(path);
    let parser_route = safe_route(&media, &bytes);
    let extraction = if parser_route == ParserRoute::SandboxRequired {
        // Routing is the terminal action here. This process never invokes a rich parser.
        extract::extract("", parser_route)
    } else {
        let text = std::str::from_utf8(&bytes).context("native input is not valid UTF-8")?;
        extract::extract(text, parser_route)
    };

    Ok(serde_json::json!({
        "media_type": media,
        "route": parser_route,
        "sandbox_required": extraction.sandbox_required,
        "blocks": extraction.blocks,
    }))
}

fn run_demo() -> Result<()> {
    let tmp = std::env::temp_dir().join(format!("kfp-{}", uuid::Uuid::now_v7()));
    std::fs::create_dir_all(&tmp)?;
    let ledger_path = tmp.join("kf_events.jsonl");
    let mut led = events::EventLedger::open(&ledger_path)?;

    println!("== KF parser router + extraction (build-seq E+F) ==\n");

    // sample corpus across media types
    let md =
        "# MASTER\nMAWorld spine.\n\n## Invariant\nLLM never owns state.\nGate is mandatory.\n";
    let txt = "line one\n\nline two\nline three\n";
    let pdf_bytes: &[u8] = b"%PDF-1.7 fake";

    let samples: Vec<(&str, &str, Option<&str>)> = vec![
        ("00_MASTER.md", "text/markdown", Some(md)),
        ("notes.txt", "text/plain", Some(txt)),
        ("report.pdf", "application/pdf", None),
    ];

    let mut results = vec![];
    for (name, media, text) in &samples {
        let bytes = text
            .map(|t| t.as_bytes().to_vec())
            .unwrap_or_else(|| pdf_bytes.to_vec());
        let sha = sha256(&bytes);
        // E: identity events into KF ledger
        led.append(
            "raw_blob.observed",
            &serde_json::json!({"sha256": sha, "media_type": media}),
        )?;
        led.append(
            "occurrence.created",
            &serde_json::json!({"source_native_id": name, "sha256": sha}),
        )?;

        // F: route + native extract (rich -> sandbox)
        let r = route(media);
        let ex = if let Some(t) = text {
            extract::extract(t, r)
        } else {
            extract::extract("", r)
        };
        let rec = ExtractionRecord {
            extraction_id: format!("ext-{}", uuid::Uuid::now_v7()),
            blob_sha256: sha,
            media_type: media.to_string(),
            route: r,
            block_count: ex.blocks.len(),
            sandbox_required: ex.sandbox_required,
        };
        led.append("extraction.created", &serde_json::to_value(&rec)?)?;
        println!(
            "{:16} {:?}  blocks={:2}  sandbox_required={}",
            name, r, rec.block_count, rec.sandbox_required
        );
        // show MD locators
        if r == ParserRoute::NativeMarkdown {
            for b in &ex.blocks {
                println!(
                    "     [{}-{}] {:9} {:?}",
                    b.start_line, b.end_line, b.kind, b.text
                );
            }
        }
        results.push((r, rec.block_count, rec.sandbox_required));
    }

    let (chain_ok, n_events) = led.verify()?;
    println!("\n-- checks --");
    let md_ok = results[0].0 == ParserRoute::NativeMarkdown && results[0].1 >= 4 && !results[0].2;
    let txt_ok = results[1].0 == ParserRoute::NativeText && results[1].1 == 3 && !results[1].2;
    let pdf_ok = results[2].0 == ParserRoute::SandboxRequired && results[2].1 == 0 && results[2].2;
    println!("  markdown parsed natively w/ locators : {}", md_ok);
    println!("  text parsed natively (3 blocks)      : {}", txt_ok);
    println!("  pdf routed to sandbox (no in-proc)   : {}", pdf_ok);
    println!(
        "  KF event chain (E)                   : ok={} events={}",
        chain_ok, n_events
    );
    std::fs::remove_dir_all(&tmp).ok();
    let pass = md_ok && txt_ok && pdf_ok && chain_ok && n_events == 9;
    println!(
        "\n{}",
        if pass {
            "PARSER ROUTER PASSED"
        } else {
            "PARSER ROUTER FAILED"
        }
    );
    if !pass {
        anyhow::bail!("failed");
    }
    Ok(())
}

fn main() -> Result<()> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(|s| s.as_str()) {
        Some("demo") | None => run_demo(),
        Some("parse") => {
            if args.len() != 2 {
                bail!("usage: kfparse parse FILE");
            }
            let file = PathBuf::from(args.get(1).context("usage: kfparse parse FILE")?);
            println!("{}", serde_json::to_string_pretty(&parse_file(&file)?)?);
            Ok(())
        }
        _ => {
            eprintln!("usage: kfparse <demo|parse FILE>");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let path = std::env::temp_dir()
                .join(format!("kf-parser-input-{label}-{}", uuid::Uuid::now_v7()));
            std::fs::create_dir_all(&path).expect("create test directory");
            Self(path)
        }

        fn file(&self, name: &str, bytes: &[u8]) -> PathBuf {
            let path = self.0.join(name);
            std::fs::write(&path, bytes).expect("write test input");
            path
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn valid_utf8_markdown_uses_native_route() {
        let dir = TestDir::new("markdown");
        let path = dir.file("safe.md", b"# Heading\n\nSafe paragraph.\n");

        let output = parse_file(&path).expect("parse safe markdown");
        assert_eq!(output["route"], serde_json::json!("NativeMarkdown"));
        assert_eq!(output["sandbox_required"], serde_json::json!(false));
        assert_eq!(output["blocks"].as_array().expect("blocks").len(), 2);
    }

    #[test]
    fn invalid_utf8_native_candidate_routes_to_sandbox() {
        let dir = TestDir::new("invalid-utf8");
        let path = dir.file("hostile.txt", &[b'a', 0xff, b'b']);

        let output = parse_file(&path).expect("route invalid UTF-8");
        assert_eq!(output["route"], serde_json::json!("SandboxRequired"));
        assert_eq!(output["sandbox_required"], serde_json::json!(true));
        assert_eq!(output["blocks"], serde_json::json!([]));
    }

    #[test]
    fn nul_in_native_candidate_routes_to_sandbox() {
        let dir = TestDir::new("nul");
        let path = dir.file("hostile.md", b"safe prefix\0hidden suffix");

        let output = parse_file(&path).expect("route NUL input");
        assert_eq!(output["route"], serde_json::json!("SandboxRequired"));
        assert_eq!(output["blocks"], serde_json::json!([]));
    }

    #[test]
    fn binary_magic_overrides_safe_looking_extension() {
        let dir = TestDir::new("magic");
        let pdf = dir.file("disguised.txt", b"%PDF-1.7\nnot actually text");
        let zip = dir.file("disguised.md", b"PK\x03\x04archive bytes");

        for path in [pdf, zip] {
            let output = parse_file(&path).expect("route disguised binary");
            assert_eq!(output["route"], serde_json::json!("SandboxRequired"));
            assert_eq!(output["sandbox_required"], serde_json::json!(true));
        }
    }

    #[test]
    fn oversized_input_is_rejected_before_parsing() {
        let dir = TestDir::new("oversized");
        let path = dir.file("large.txt", &vec![b'a'; MAX_INPUT_BYTES as usize + 1]);

        assert!(parse_file(&path).is_err());
    }

    #[test]
    fn directory_is_rejected_as_non_regular_input() {
        let dir = TestDir::new("directory");
        assert!(parse_file(&dir.0).is_err());
    }

    #[cfg(unix)]
    #[test]
    fn symbolic_link_is_rejected() {
        use std::os::unix::fs::symlink;

        let dir = TestDir::new("symlink");
        let target = dir.file("target.txt", b"safe text");
        let link = dir.0.join("link.txt");
        symlink(target, &link).expect("create symlink");

        assert!(parse_file(&link).is_err());
    }
}
