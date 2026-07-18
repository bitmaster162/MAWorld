//! Deterministic native extraction with exact locators (closure v1.1 §claim/evidence needs
//! exact_source_excerpt + locator). Produces versioned blocks with 1-based line ranges so a
//! downstream Claim can point at an exact excerpt. Deterministic: same bytes -> same blocks.
use crate::router::ParserRoute;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Block {
    pub kind: String, // heading | paragraph | code_line | text
    pub text: String,
    pub start_line: u32, // 1-based, inclusive
    pub end_line: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Extraction {
    pub route: ParserRoute,
    pub blocks: Vec<Block>,
    pub sandbox_required: bool,
}

/// Parse text natively per route. SandboxRequired returns no blocks (must go to sandbox).
pub fn extract(text: &str, route: ParserRoute) -> Extraction {
    match route {
        ParserRoute::SandboxRequired => Extraction {
            route,
            blocks: vec![],
            sandbox_required: true,
        },
        ParserRoute::NativeMarkdown => Extraction {
            route,
            blocks: md_blocks(text),
            sandbox_required: false,
        },
        ParserRoute::NativeText | ParserRoute::NativeSource => Extraction {
            route,
            blocks: text_blocks(text, route),
            sandbox_required: false,
        },
    }
}

fn md_blocks(text: &str) -> Vec<Block> {
    let mut blocks = Vec::new();
    let mut para: Vec<&str> = Vec::new();
    let mut para_start = 0u32;
    let flush = |blocks: &mut Vec<Block>, para: &mut Vec<&str>, start: u32, end: u32| {
        if !para.is_empty() {
            blocks.push(Block {
                kind: "paragraph".into(),
                text: para.join("\n"),
                start_line: start,
                end_line: end,
            });
            para.clear();
        }
    };
    for (i, line) in text.lines().enumerate() {
        let ln = (i + 1) as u32;
        if let Some(h) = line.strip_prefix('#') {
            flush(
                &mut blocks,
                &mut para,
                para_start,
                ln.saturating_sub(1).max(para_start),
            );
            let level = line.len() - line.trim_start_matches('#').len();
            blocks.push(Block {
                kind: format!("heading{level}"),
                text: h.trim_start_matches('#').trim().to_string(),
                start_line: ln,
                end_line: ln,
            });
        } else if line.trim().is_empty() {
            flush(
                &mut blocks,
                &mut para,
                para_start,
                ln.saturating_sub(1).max(para_start),
            );
        } else {
            if para.is_empty() {
                para_start = ln;
            }
            para.push(line);
        }
    }
    let last = text.lines().count() as u32;
    flush(&mut blocks, &mut para, para_start, last);
    blocks
}

fn text_blocks(text: &str, route: ParserRoute) -> Vec<Block> {
    let kind = if route == ParserRoute::NativeSource {
        "code_line"
    } else {
        "text"
    };
    text.lines()
        .enumerate()
        .filter(|(_, l)| !l.trim().is_empty())
        .map(|(i, l)| Block {
            kind: kind.into(),
            text: l.to_string(),
            start_line: (i + 1) as u32,
            end_line: (i + 1) as u32,
        })
        .collect()
}
