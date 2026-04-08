# zensical-asciidoctor-backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Zensical module that renders AsciiDoc files via `asciidoctor` subprocess and post-processes the HTML for Material theme compatibility, producing `RenderedDoc` structs compatible with Zensical's page pipeline.

**Architecture:** Single Rust crate implementing `zrx::module::Module`. The module subscribes to file streams, filters `.adoc` files, renders them via the `asciidoctor` CLI, and post-processes the HTML (admonitions, callouts, tables, figures, xref URLs, TOC extraction). Business logic is split across three internal modules: `config` (configuration struct), `renderer` (subprocess execution), and `html` (HTML transformations).

**Tech Stack:** Rust (edition 2024), `zrx` v0.0.17 (git dep), `scraper` (HTML parsing), `thiserror` (errors), `tracing` (diagnostics), `insta` + `pretty_assertions` (testing)

**Spec:** `docs/superpowers/specs/2026-04-08-zensical-asciidoctor-backend-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `~/zensical-asciidoctor-backend/Cargo.toml` | Crate metadata, dependencies |
| `~/zensical-asciidoctor-backend/src/lib.rs` | `AsciiDoc` module struct, `Module` impl, `RenderedDoc` type, re-exports |
| `~/zensical-asciidoctor-backend/src/config.rs` | `Config` struct, `SafeMode` enum, defaults |
| `~/zensical-asciidoctor-backend/src/renderer.rs` | `Renderer` struct, subprocess execution, `RendererError` |
| `~/zensical-asciidoctor-backend/src/html.rs` | `HtmlProcessor`, all HTML transformations, `TocEntry`, `DocMeta`, `HtmlError` |
| `~/zensical-asciidoctor-backend/LICENSE.md` | MIT license |

---

### Task 1: Project scaffold and Config

**Files:**
- Create: `~/zensical-asciidoctor-backend/Cargo.toml`
- Create: `~/zensical-asciidoctor-backend/LICENSE.md`
- Create: `~/zensical-asciidoctor-backend/src/config.rs`
- Create: `~/zensical-asciidoctor-backend/src/lib.rs` (initial stub)

- [ ] **Step 1: Initialize git repo**

```bash
cd ~/zensical-asciidoctor-backend || mkdir -p ~/zensical-asciidoctor-backend && cd ~/zensical-asciidoctor-backend
git init
```

- [ ] **Step 2: Create Cargo.toml**

```toml
[package]
name = "zensical-asciidoctor-backend"
version = "0.1.0"
edition = "2024"
rust-version = "1.86"
description = "Zensical module for AsciiDoc support via Asciidoctor"
license = "MIT"
repository = "https://github.com/aireilly/zensical-asciidoctor-backend"

[dependencies]
scraper = "0.22"
thiserror = "2"
tracing = "0.1"
regex = "1"

# ZRX module system — pinned to the tag that shipped the module system
zrx = { git = "https://github.com/zensical/zrx.git", tag = "v0.0.17" }

[dev-dependencies]
insta = "1"
pretty_assertions = "1"

[features]
default = []
integration = [] # gates tests requiring `asciidoctor` binary
```

- [ ] **Step 3: Create LICENSE.md**

Use the MIT license text, matching the zensical ecosystem. Copyright holder: the project author.

- [ ] **Step 4: Create .gitignore**

```gitignore
/target
```

- [ ] **Step 5: Create src/config.rs**

```rust
//! Configuration for the AsciiDoc module.

use std::collections::HashMap;
use std::fmt;

/// Configuration for the AsciiDoc module.
#[derive(Clone, Debug)]
pub struct Config {
    /// Path to asciidoctor binary.
    pub asciidoctor_cmd: String,
    /// Safe mode for asciidoctor.
    pub safe_mode: SafeMode,
    /// Asciidoctor attributes passed as `-a key=value`.
    pub attributes: HashMap<String, String>,
    /// Ruby libraries to require via `-r`.
    pub requires: Vec<String>,
    /// Whether to fail the build on render errors.
    pub fail_on_error: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            asciidoctor_cmd: String::from("asciidoctor"),
            safe_mode: SafeMode::default(),
            attributes: HashMap::from([
                (String::from("showtitle"), String::new()),
                (String::from("sectanchors"), String::new()),
                (String::from("source-highlighter"), String::from("rouge")),
            ]),
            requires: Vec::new(),
            fail_on_error: true,
        }
    }
}

/// Asciidoctor safe mode.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum SafeMode {
    Unsafe,
    #[default]
    Safe,
    Server,
    Secure,
}

impl fmt::Display for SafeMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SafeMode::Unsafe => write!(f, "unsafe"),
            SafeMode::Safe => write!(f, "safe"),
            SafeMode::Server => write!(f, "server"),
            SafeMode::Secure => write!(f, "secure"),
        }
    }
}
```

- [ ] **Step 6: Create initial src/lib.rs stub**

```rust
//! Zensical module for AsciiDoc support.
//!
//! This crate provides a Zensical module that renders AsciiDoc files using
//! the `asciidoctor` CLI and post-processes the HTML output for Material
//! theme compatibility.

pub mod config;
pub mod html;
pub mod renderer;

pub use config::Config;
```

- [ ] **Step 7: Verify it compiles**

```bash
cd ~/zensical-asciidoctor-backend && cargo check
```

Expected: compiles successfully (html and renderer modules don't exist yet, so comment out those `pub mod` lines temporarily, or create empty files).

Actually, create empty stub files first:

```bash
touch ~/zensical-asciidoctor-backend/src/html.rs
touch ~/zensical-asciidoctor-backend/src/renderer.rs
```

Then run `cargo check`. Expected: success.

- [ ] **Step 8: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add Cargo.toml LICENSE.md .gitignore src/
git commit -m "feat: scaffold project with config module"
```

---

### Task 2: Renderer — command construction and subprocess execution

**Files:**
- Create: `~/zensical-asciidoctor-backend/src/renderer.rs`

- [ ] **Step 1: Write tests for command construction**

Add to `src/renderer.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Config, SafeMode};
    use std::collections::HashMap;

    #[test]
    fn test_build_args_default_config() {
        let config = Config::default();
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("asciidoctor")));
        assert!(args.contains(&String::from("-b")));
        assert!(args.contains(&String::from("html5")));
        assert!(args.contains(&String::from("-s")));
        assert!(args.contains(&String::from("-o")));
        assert!(args.contains(&String::from("-")));
        assert!(args.contains(&String::from("-S")));
        assert!(args.contains(&String::from("safe")));
        assert!(args.contains(&String::from("/tmp/test.adoc")));
    }

    #[test]
    fn test_build_args_custom_safe_mode() {
        let config = Config {
            safe_mode: SafeMode::Unsafe,
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("unsafe")));
    }

    #[test]
    fn test_build_args_with_attributes() {
        let config = Config {
            attributes: HashMap::from([
                (String::from("imagesdir"), String::from("images")),
            ]),
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("-a")));
        assert!(args.contains(&String::from("imagesdir=images")));
    }

    #[test]
    fn test_build_args_with_requires() {
        let config = Config {
            requires: vec![String::from("asciidoctor-diagram")],
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("-r")));
        assert!(args.contains(&String::from("asciidoctor-diagram")));
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib renderer::tests
```

Expected: FAIL — `Renderer` not defined.

- [ ] **Step 3: Implement Renderer**

Write `src/renderer.rs`:

```rust
//! Asciidoctor subprocess renderer.

use std::process::Command;

use thiserror::Error;

use crate::config::Config;

/// Errors that can occur during rendering.
#[derive(Debug, Error)]
pub enum RendererError {
    /// Asciidoctor binary not found.
    #[error("asciidoctor not found: '{cmd}'. Install with: gem install asciidoctor")]
    NotFound { cmd: String },
    /// Asciidoctor exited with an error.
    #[error("asciidoctor failed for {path}: {stderr}")]
    Failed { path: String, stderr: String },
    /// I/O error.
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// Renders AsciiDoc files via the `asciidoctor` CLI.
#[derive(Clone, Debug)]
pub struct Renderer {
    cmd: String,
    safe_mode: String,
    attributes: Vec<(String, String)>,
    requires: Vec<String>,
    fail_on_error: bool,
}

impl Renderer {
    /// Creates a new renderer from the given configuration.
    pub fn new(config: &Config) -> Self {
        Self {
            cmd: config.asciidoctor_cmd.clone(),
            safe_mode: config.safe_mode.to_string(),
            attributes: config.attributes.iter()
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect(),
            requires: config.requires.clone(),
            fail_on_error: config.fail_on_error,
        }
    }

    /// Builds the command-line arguments for asciidoctor.
    pub fn build_args(&self, src_path: &str) -> Vec<String> {
        let mut args = vec![
            self.cmd.clone(),
            String::from("-b"), String::from("html5"),
            String::from("-s"),
            String::from("-o"), String::from("-"),
            String::from("-S"), self.safe_mode.clone(),
        ];

        for lib in &self.requires {
            args.push(String::from("-r"));
            args.push(lib.clone());
        }

        for (key, value) in &self.attributes {
            args.push(String::from("-a"));
            if value.is_empty() {
                args.push(key.clone());
            } else {
                args.push(format!("{key}={value}"));
            }
        }

        args.push(src_path.to_string());
        args
    }

    /// Renders an AsciiDoc file and returns the raw HTML.
    ///
    /// # Errors
    ///
    /// Returns `RendererError` if the subprocess fails. When `fail_on_error`
    /// is false, rendering errors produce an HTML error block instead.
    pub fn render(&self, src_path: &str) -> Result<String, RendererError> {
        let args = self.build_args(src_path);

        let output = match Command::new(&args[0])
            .args(&args[1..])
            .output()
        {
            Ok(output) => output,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
                if self.fail_on_error {
                    return Err(RendererError::NotFound {
                        cmd: self.cmd.clone(),
                    });
                }
                return Ok(format!(
                    "<div class=\"admonition danger\"><p class=\"admonition-title\">Error</p>\
                     <p>asciidoctor not found: '{}'. Install with: gem install asciidoctor</p></div>",
                    self.cmd
                ));
            }
            Err(err) => return Err(RendererError::Io(err)),
        };

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr).to_string();
            if self.fail_on_error {
                return Err(RendererError::Failed {
                    path: src_path.to_string(),
                    stderr,
                });
            }
            return Ok(format!(
                "<div class=\"admonition danger\"><p class=\"admonition-title\">Error</p>\
                 <pre>{}</pre></div>",
                html_escape(&stderr)
            ));
        }

        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
}

/// Escapes HTML special characters.
fn html_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::{Config, SafeMode};
    use std::collections::HashMap;

    #[test]
    fn test_build_args_default_config() {
        let config = Config::default();
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("asciidoctor")));
        assert!(args.contains(&String::from("-b")));
        assert!(args.contains(&String::from("html5")));
        assert!(args.contains(&String::from("-s")));
        assert!(args.contains(&String::from("-o")));
        assert!(args.contains(&String::from("-")));
        assert!(args.contains(&String::from("-S")));
        assert!(args.contains(&String::from("safe")));
        assert!(args.contains(&String::from("/tmp/test.adoc")));
    }

    #[test]
    fn test_build_args_custom_safe_mode() {
        let config = Config {
            safe_mode: SafeMode::Unsafe,
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("unsafe")));
    }

    #[test]
    fn test_build_args_with_attributes() {
        let config = Config {
            attributes: HashMap::from([
                (String::from("imagesdir"), String::from("images")),
            ]),
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("-a")));
        assert!(args.contains(&String::from("imagesdir=images")));
    }

    #[test]
    fn test_build_args_with_requires() {
        let config = Config {
            requires: vec![String::from("asciidoctor-diagram")],
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("-r")));
        assert!(args.contains(&String::from("asciidoctor-diagram")));
    }

    #[test]
    fn test_build_args_empty_attribute_value() {
        let config = Config {
            attributes: HashMap::from([
                (String::from("showtitle"), String::new()),
            ]),
            ..Config::default()
        };
        let renderer = Renderer::new(&config);
        let args = renderer.build_args("/tmp/test.adoc");
        assert!(args.contains(&String::from("showtitle")));
    }

    #[test]
    fn test_html_escape() {
        assert_eq!(
            html_escape("<script>alert('xss')</script>"),
            "&lt;script&gt;alert('xss')&lt;/script&gt;"
        );
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib renderer::tests
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/renderer.rs
git commit -m "feat: add asciidoctor subprocess renderer"
```

---

### Task 3: HTML processor — metadata extraction and TOC

**Files:**
- Create: `~/zensical-asciidoctor-backend/src/html.rs`

- [ ] **Step 1: Write tests for metadata extraction and TOC building**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_meta_title() {
        let html = r#"<h1 class="sect0">My Title</h1><p>content</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.meta.title, Some(String::from("My Title")));
    }

    #[test]
    fn test_extract_meta_description() {
        let html = r#"<meta name="description" content="A page description"/><p>content</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.meta.description, Some(String::from("A page description")));
    }

    #[test]
    fn test_toc_from_headings() {
        let html = r#"<h2 id="intro">Introduction</h2><p>text</p><h3 id="sub">Subsection</h3><p>more</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].title, "Introduction");
        assert_eq!(result.toc[0].id, "intro");
        assert_eq!(result.toc[0].level, 2);
        assert_eq!(result.toc[0].children.len(), 1);
        assert_eq!(result.toc[0].children[0].title, "Subsection");
    }

    #[test]
    fn test_toc_generates_id_when_missing() {
        let html = r#"<h2>No ID Heading</h2><p>text</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].id, "no-id-heading");
    }

    #[test]
    fn test_sect0_excluded_from_toc() {
        let html = r#"<h1 class="sect0">Title</h1><h2 id="s1">Section 1</h2>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].title, "Section 1");
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: FAIL — `HtmlProcessor` not defined.

- [ ] **Step 3: Implement HtmlProcessor with metadata extraction and TOC**

Write `src/html.rs`:

```rust
//! HTML post-processing for Asciidoctor output.

use regex::Regex;
use scraper::{Html, Selector};
use thiserror::Error;

/// Errors that can occur during HTML processing.
#[derive(Debug, Error)]
pub enum HtmlError {
    /// Failed to parse HTML.
    #[error("failed to parse HTML: {0}")]
    Parse(String),
}

/// Table of contents entry.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TocEntry {
    /// Section title.
    pub title: String,
    /// Section anchor ID.
    pub id: String,
    /// Heading level (1-6).
    pub level: u8,
    /// Child entries.
    pub children: Vec<TocEntry>,
}

/// Extracted document metadata.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct DocMeta {
    /// Document title.
    pub title: Option<String>,
    /// Document description.
    pub description: Option<String>,
}

/// Result of HTML processing.
#[derive(Clone, Debug)]
pub struct ProcessedDoc {
    /// Processed HTML content.
    pub html: String,
    /// Table of contents.
    pub toc: Vec<TocEntry>,
    /// Document metadata.
    pub meta: DocMeta,
}

/// Post-processes Asciidoctor HTML for Material theme compatibility.
pub struct HtmlProcessor {
    _private: (),
}

impl HtmlProcessor {
    /// Creates a new HTML processor.
    pub fn new() -> Self {
        Self { _private: () }
    }

    /// Processes HTML and returns the result.
    pub fn process(&self, html: &str, page_rel_path: Option<&str>) -> ProcessedDoc {
        let mut html_string = html.to_string();

        // Extract metadata before modifying the HTML
        let meta = self.extract_meta(&html_string);

        // Ensure headings have IDs (must happen before TOC extraction)
        html_string = self.ensure_heading_ids(&html_string);

        // Extract TOC from headings
        let toc = self.extract_toc(&html_string);

        // Apply transformations
        html_string = self.transform_admonitions(&html_string);
        html_string = self.transform_callout_lists(&html_string);
        html_string = self.clean_callouts_in_code(&html_string);
        html_string = self.transform_tables(&html_string);
        html_string = self.transform_figures(&html_string);
        html_string = self.fix_xref_urls(&html_string, page_rel_path);

        ProcessedDoc {
            html: html_string,
            toc,
            meta,
        }
    }

    /// Extracts metadata (title, description) from HTML.
    fn extract_meta(&self, html: &str) -> DocMeta {
        let doc = Html::parse_fragment(html);
        let mut meta = DocMeta::default();

        // Extract title from h1.sect0
        let title_sel = Selector::parse("h1.sect0").expect("valid selector");
        if let Some(el) = doc.select(&title_sel).next() {
            meta.title = Some(el.text().collect::<Vec<_>>().join(" ").trim().to_string());
        } else {
            // Fall back to any h1
            let h1_sel = Selector::parse("h1").expect("valid selector");
            if let Some(el) = doc.select(&h1_sel).next() {
                meta.title = Some(el.text().collect::<Vec<_>>().join(" ").trim().to_string());
            }
        }

        // Extract description from meta tag
        let meta_sel = Selector::parse(r#"meta[name="description"]"#).expect("valid selector");
        if let Some(el) = doc.select(&meta_sel).next() {
            if let Some(content) = el.value().attr("content") {
                if !content.is_empty() {
                    meta.description = Some(content.to_string());
                }
            }
        }

        meta
    }

    /// Ensures all headings have IDs, generating slugs for those without.
    fn ensure_heading_ids(&self, html: &str) -> String {
        let re = Regex::new(r"<(h[1-6])([^>]*)>([^<]*)</\1>").expect("valid regex");
        re.replace_all(html, |caps: &regex::Captures| {
            let tag = &caps[1];
            let attrs = &caps[2];
            let text = &caps[3];
            if attrs.contains("id=") {
                caps[0].to_string()
            } else {
                let id = slugify(text);
                format!("<{tag}{attrs} id=\"{id}\">{text}</{tag}>")
            }
        }).to_string()
    }

    /// Extracts table of contents from heading elements.
    fn extract_toc(&self, html: &str) -> Vec<TocEntry> {
        let doc = Html::parse_fragment(html);
        let heading_sel = Selector::parse("h1, h2, h3, h4, h5, h6").expect("valid selector");

        let mut entries = Vec::new();
        let mut stack: Vec<(u8, usize)> = Vec::new(); // (level, index into parent's children)

        for el in doc.select(&heading_sel) {
            // Skip sect0 title
            let classes = el.value().attr("class").unwrap_or("");
            if el.value().name() == "h1" && classes.contains("sect0") {
                continue;
            }

            let level = el.value().name()[1..].parse::<u8>().unwrap_or(1);
            let id = el.value().attr("id").unwrap_or("").to_string();
            let title = el.text().collect::<Vec<_>>().join(" ").trim().to_string();

            let entry = TocEntry {
                title,
                id,
                level,
                children: Vec::new(),
            };

            // Pop stack entries at same level or deeper
            while let Some(&(stack_level, _)) = stack.last() {
                if stack_level >= level {
                    stack.pop();
                } else {
                    break;
                }
            }

            if stack.is_empty() {
                let idx = entries.len();
                entries.push(entry);
                stack.push((level, idx));
            } else {
                // Find the parent to add this entry to
                let parent = self.get_entry_mut(&mut entries, &stack);
                let idx = parent.children.len();
                parent.children.push(entry);
                stack.push((level, idx));
            }
        }

        entries
    }

    /// Gets a mutable reference to a TOC entry by following the stack path.
    fn get_entry_mut<'a>(
        &self, entries: &'a mut Vec<TocEntry>, stack: &[(u8, usize)],
    ) -> &'a mut TocEntry {
        let mut current = &mut entries[stack[0].1];
        for &(_, idx) in &stack[1..] {
            current = &mut current.children[idx];
        }
        current
    }

    // Placeholder methods — implemented in subsequent tasks
    fn transform_admonitions(&self, html: &str) -> String { html.to_string() }
    fn transform_callout_lists(&self, html: &str) -> String { html.to_string() }
    fn clean_callouts_in_code(&self, html: &str) -> String { html.to_string() }
    fn transform_tables(&self, html: &str) -> String { html.to_string() }
    fn transform_figures(&self, html: &str) -> String { html.to_string() }
    fn fix_xref_urls(&self, html: &str, _page_rel_path: Option<&str>) -> String { html.to_string() }
}

/// Converts text to a URL-friendly slug.
pub fn slugify(text: &str) -> String {
    let mut slug = String::new();
    for ch in text.trim().chars() {
        if ch.is_alphanumeric() {
            slug.push(ch.to_ascii_lowercase());
        } else if ch == ' ' || ch == '-' || ch == '_' {
            if !slug.ends_with('-') {
                slug.push('-');
            }
        }
    }
    slug.trim_end_matches('-').to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_meta_title() {
        let html = r#"<h1 class="sect0">My Title</h1><p>content</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.meta.title, Some(String::from("My Title")));
    }

    #[test]
    fn test_extract_meta_description() {
        let html = r#"<meta name="description" content="A page description"/><p>content</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.meta.description, Some(String::from("A page description")));
    }

    #[test]
    fn test_toc_from_headings() {
        let html = r#"<h2 id="intro">Introduction</h2><p>text</p><h3 id="sub">Subsection</h3><p>more</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].title, "Introduction");
        assert_eq!(result.toc[0].id, "intro");
        assert_eq!(result.toc[0].level, 2);
        assert_eq!(result.toc[0].children.len(), 1);
        assert_eq!(result.toc[0].children[0].title, "Subsection");
    }

    #[test]
    fn test_toc_generates_id_when_missing() {
        let html = r#"<h2>No ID Heading</h2><p>text</p>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].id, "no-id-heading");
    }

    #[test]
    fn test_sect0_excluded_from_toc() {
        let html = r#"<h1 class="sect0">Title</h1><h2 id="s1">Section 1</h2>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert_eq!(result.toc.len(), 1);
        assert_eq!(result.toc[0].title, "Section 1");
    }

    #[test]
    fn test_slugify() {
        assert_eq!(slugify("Hello World"), "hello-world");
        assert_eq!(slugify("Some  Spaces"), "some-spaces");
        assert_eq!(slugify("trailing- "), "trailing");
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/html.rs
git commit -m "feat: add HTML processor with metadata extraction and TOC"
```

---

### Task 4: HTML processor — admonition transformation

**Files:**
- Modify: `~/zensical-asciidoctor-backend/src/html.rs`

- [ ] **Step 1: Write tests for admonition transformation**

Add to the `tests` module in `src/html.rs`:

```rust
    #[test]
    fn test_transform_admonition_note() {
        let html = r#"<div class="admonitionblock note"><table><tr><td class="content">Some note content</td></tr></table></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"class="admonition note""#));
        assert!(result.html.contains(r#"class="admonition-title""#));
        assert!(result.html.contains("Note"));
        assert!(result.html.contains("Some note content"));
    }

    #[test]
    fn test_transform_admonition_caution_maps_to_warning() {
        let html = r#"<div class="admonitionblock caution"><table><tr><td class="content">Be careful</td></tr></table></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"class="admonition warning""#));
    }

    #[test]
    fn test_transform_admonition_important_maps_to_danger() {
        let html = r#"<div class="admonitionblock important"><table><tr><td class="content">Critical info</td></tr></table></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"class="admonition danger""#));
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests::test_transform_admonition
```

Expected: FAIL — admonitions pass through untransformed.

- [ ] **Step 3: Implement admonition transformation**

Replace the `transform_admonitions` placeholder in `src/html.rs`:

```rust
    /// Transforms Asciidoctor admonition blocks to Material style.
    fn transform_admonitions(&self, html: &str) -> String {
        let doc = Html::parse_fragment(html);
        let sel = Selector::parse("div.admonitionblock").expect("valid selector");

        let mut result = html.to_string();

        for el in doc.select(&sel) {
            let classes: Vec<&str> = el.value().attr("class")
                .unwrap_or("")
                .split_whitespace()
                .collect();

            let kinds = ["note", "tip", "important", "caution", "warning"];
            let kind = classes.iter()
                .find(|c| kinds.contains(c))
                .copied()
                .unwrap_or("note");

            let material_kind = match kind {
                "caution" => "warning",
                "important" => "danger",
                other => other,
            };

            let title = kind[..1].to_uppercase() + &kind[1..];

            // Extract content from the .content cell
            let content_sel = Selector::parse("td.content, .content").expect("valid selector");
            let content_html = el.select(&content_sel)
                .next()
                .map(|c| c.inner_html())
                .unwrap_or_default();

            let replacement = format!(
                "<div class=\"admonition {material_kind}\">\
                 <p class=\"admonition-title\">{title}</p>\
                 {content_html}\
                 </div>"
            );

            let original = el.html();
            result = result.replace(&original, &replacement);
        }

        result
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/html.rs
git commit -m "feat: add admonition transformation"
```

---

### Task 5: HTML processor — callout lists and code callout cleanup

**Files:**
- Modify: `~/zensical-asciidoctor-backend/src/html.rs`

- [ ] **Step 1: Write tests for callout list transformation**

Add to the `tests` module:

```rust
    #[test]
    fn test_transform_callout_list() {
        let html = r#"<div class="colist"><table><tbody><tr><td>1</td><td>First item</td></tr><tr><td>2</td><td>Second item</td></tr></tbody></table></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains("<ol"));
        assert!(result.html.contains("colist"));
        assert!(result.html.contains("<li>"));
        assert!(result.html.contains("First item"));
        assert!(result.html.contains("Second item"));
        assert!(!result.html.contains("<table>"));
    }

    #[test]
    fn test_clean_callout_markers() {
        let html = r#"<div class="listingblock"><pre>code line <span class="conum" data-value="1"></span>(1)
more code</pre></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        // Textual marker (1) should be removed
        assert!(!result.html.contains("(1)"));
        // But the conum span should remain
        assert!(result.html.contains("conum"));
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests::test_transform_callout html::tests::test_clean_callout
```

Expected: FAIL — callouts pass through untransformed.

- [ ] **Step 3: Implement callout list transformation**

Replace the `transform_callout_lists` placeholder:

```rust
    /// Transforms callout tables to ordered lists.
    fn transform_callout_lists(&self, html: &str) -> String {
        let doc = Html::parse_fragment(html);
        let sel = Selector::parse("div.colist").expect("valid selector");
        let tr_sel = Selector::parse("tr").expect("valid selector");
        let td_sel = Selector::parse("td").expect("valid selector");

        let mut result = html.to_string();

        for el in doc.select(&sel) {
            let mut items = Vec::new();
            for tr in el.select(&tr_sel) {
                let tds: Vec<_> = tr.select(&td_sel).collect();
                if tds.len() >= 2 {
                    items.push(tds[1].inner_html());
                }
            }

            if items.is_empty() {
                continue;
            }

            let li_html: String = items.iter()
                .map(|item| format!("<li>{item}</li>"))
                .collect();

            let replacement = format!(r#"<ol class="colist">{li_html}</ol>"#);
            let original = el.html();
            result = result.replace(&original, &replacement);
        }

        result
    }
```

- [ ] **Step 4: Implement code callout cleanup**

Replace the `clean_callouts_in_code` placeholder:

```rust
    /// Cleans textual callout markers from code blocks.
    fn clean_callouts_in_code(&self, html: &str) -> String {
        // Remove textual callout patterns like (1), <1>, &lt;1&gt; that follow conum spans
        let re = Regex::new(r#"(<span[^>]*class="conum"[^>]*>[^<]*</span>)\s*(\(\d+\)|<\d+>|&lt;\d+&gt;)"#)
            .expect("valid regex");
        re.replace_all(html, "$1").to_string()
    }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/html.rs
git commit -m "feat: add callout list and code callout transformations"
```

---

### Task 6: HTML processor — tables and figures

**Files:**
- Modify: `~/zensical-asciidoctor-backend/src/html.rs`

- [ ] **Step 1: Write tests for table and figure transformations**

Add to the `tests` module:

```rust
    #[test]
    fn test_transform_table_wraps_with_typeset() {
        let html = r#"<table class="tableblock"><tr><td>data</td></tr></table>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains("md-typeset__table"));
    }

    #[test]
    fn test_transform_table_moves_title_to_caption() {
        let html = r#"<div class="tableblock"><div class="title">Table 1</div><table class="tableblock"><tr><td>data</td></tr></table></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains("<caption>Table 1</caption>"));
        // Original title div should be gone
        assert!(!result.html.contains(r#"<div class="title">Table 1</div>"#));
    }

    #[test]
    fn test_transform_figure() {
        let html = r#"<div class="imageblock"><div class="content"><img src="pic.png" alt="A picture"></div><div class="title">Figure 1</div></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains("<figure"));
        assert!(result.html.contains("adoc-figure"));
        assert!(result.html.contains("<figcaption>Figure 1</figcaption>"));
        assert!(result.html.contains(r#"src="pic.png""#));
    }

    #[test]
    fn test_transform_figure_without_title() {
        let html = r#"<div class="imageblock"><div class="content"><img src="pic.png" alt="A picture"></div></div>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains("<figure"));
        assert!(result.html.contains("adoc-figure"));
        assert!(!result.html.contains("<figcaption>"));
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests::test_transform_table html::tests::test_transform_figure
```

Expected: FAIL.

- [ ] **Step 3: Implement table transformation**

Replace the `transform_tables` placeholder:

```rust
    /// Transforms tables: wraps with Material CSS class and moves title to caption.
    fn transform_tables(&self, html: &str) -> String {
        let doc = Html::parse_fragment(html);
        let sel = Selector::parse("table.tableblock").expect("valid selector");
        let title_sel = Selector::parse("div.title").expect("valid selector");

        let mut result = html.to_string();

        // First handle tables inside a div.tableblock parent with a title
        let block_sel = Selector::parse("div.tableblock").expect("valid selector");
        for block in doc.select(&block_sel) {
            let title_text = block.select(&title_sel)
                .next()
                .map(|t| t.text().collect::<Vec<_>>().join(" ").trim().to_string());

            let table = block.select(&sel).next();
            if let Some(table) = table {
                let mut table_html = table.html();

                // Insert caption if title exists
                if let Some(ref title) = title_text {
                    // Insert caption right after the opening <table> tag
                    if let Some(pos) = table_html.find('>') {
                        table_html.insert_str(pos + 1, &format!("<caption>{title}</caption>"));
                    }
                }

                let replacement = format!(r#"<div class="md-typeset__table">{table_html}</div>"#);
                let original = block.html();
                result = result.replace(&original, &replacement);
            }
        }

        // Handle standalone tables (no div.tableblock parent)
        let doc2 = Html::parse_fragment(&result);
        for table in doc2.select(&sel) {
            // Skip if already wrapped
            let table_outer = table.html();
            if result.contains(&format!(r#"md-typeset__table">{table_outer}"#)) {
                continue;
            }
            let replacement = format!(r#"<div class="md-typeset__table">{table_outer}</div>"#);
            result = result.replace(&table_outer, &replacement);
        }

        result
    }
```

- [ ] **Step 4: Implement figure transformation**

Replace the `transform_figures` placeholder:

```rust
    /// Transforms image blocks to HTML5 figure elements.
    fn transform_figures(&self, html: &str) -> String {
        let doc = Html::parse_fragment(html);
        let sel = Selector::parse("div.imageblock").expect("valid selector");
        let content_sel = Selector::parse("div.content").expect("valid selector");
        let title_sel = Selector::parse("div.title").expect("valid selector");

        let mut result = html.to_string();

        for el in doc.select(&sel) {
            let content = match el.select(&content_sel).next() {
                Some(c) => c.inner_html(),
                None => continue,
            };

            let title = el.select(&title_sel)
                .next()
                .map(|t| t.text().collect::<Vec<_>>().join(" ").trim().to_string());

            let caption = title
                .map(|t| format!("<figcaption>{t}</figcaption>"))
                .unwrap_or_default();

            let replacement = format!(
                r#"<figure class="adoc-figure">{caption}{content}</figure>"#
            );

            let original = el.html();
            result = result.replace(&original, &replacement);
        }

        result
    }
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/html.rs
git commit -m "feat: add table and figure transformations"
```

---

### Task 7: HTML processor — xref URL fixing

**Files:**
- Modify: `~/zensical-asciidoctor-backend/src/html.rs`

- [ ] **Step 1: Write tests for xref URL rewriting**

Add to the `tests` module:

```rust
    #[test]
    fn test_xref_adoc_to_trailing_slash() {
        let html = r#"<a href="other.adoc">Link</a>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, Some("docs/page.adoc"));
        // other.adoc should become other/ (directory URL)
        assert!(result.html.contains(r#"href="../other/""#) || result.html.contains(r#"href="other/""#));
    }

    #[test]
    fn test_xref_preserves_fragment() {
        let html = r#"<a href="other.adoc#section">Link</a>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, Some("page.adoc"));
        assert!(result.html.contains("#section"));
    }

    #[test]
    fn test_xref_absolute_url_unchanged() {
        let html = r#"<a href="https://example.com">Link</a>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"href="https://example.com""#));
    }

    #[test]
    fn test_xref_fragment_only_unchanged() {
        let html = r#"<a href="#section">Link</a>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"href="#section""#));
    }

    #[test]
    fn test_xref_html_extension_to_trailing_slash() {
        let html = r#"<a href="page.html">Link</a>"#;
        let processor = HtmlProcessor::new();
        let result = processor.process(html, None);
        assert!(result.html.contains(r#"href="page/""#));
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests::test_xref
```

Expected: FAIL.

- [ ] **Step 3: Implement xref URL fixing**

Replace the `fix_xref_urls` placeholder:

```rust
    /// Fixes cross-reference URLs for directory-URL routing.
    fn fix_xref_urls(&self, html: &str, page_rel_path: Option<&str>) -> String {
        let re = Regex::new(r#"<a\s+([^>]*?)href="([^"]*)"([^>]*)>"#).expect("valid regex");

        re.replace_all(html, |caps: &regex::Captures| {
            let pre = &caps[1];
            let href = &caps[2];
            let post = &caps[3];
            let new_href = self.rewrite_href(href, page_rel_path);
            format!(r#"<a {pre}href="{new_href}"{post}>"#)
        }).to_string()
    }

    /// Rewrites a single href for directory-URL compatibility.
    fn rewrite_href(&self, href: &str, page_rel_path: Option<&str>) -> String {
        // Skip absolute URLs, fragments, mailto, tel
        if href.is_empty()
            || href.starts_with('#')
            || href.starts_with("http://")
            || href.starts_with("https://")
            || href.starts_with("mailto:")
            || href.starts_with("tel:")
        {
            return href.to_string();
        }

        // Split off fragment and query
        let (path_and_query, fragment) = match href.split_once('#') {
            Some((p, f)) => (p, Some(f)),
            None => (href, None),
        };

        let (path_only, query) = match path_and_query.split_once('?') {
            Some((p, q)) => (p, Some(q)),
            None => (path_and_query, None),
        };

        // Convert file extensions to directory URLs
        let mut new_path = if path_only.ends_with("/index.html") {
            path_only.trim_end_matches("index.html").to_string()
        } else if path_only.ends_with(".html") {
            format!("{}/", path_only.trim_end_matches(".html"))
        } else if path_only.ends_with(".adoc") {
            format!("{}/", path_only.trim_end_matches(".adoc"))
        } else {
            path_only.to_string()
        };

        // Resolve relative paths against source file location
        if let Some(page_path) = page_rel_path {
            if !new_path.starts_with('/') {
                let src_dir = parent_path(page_path);
                let had_trailing_slash = new_path.ends_with('/');

                // Resolve relative to source directory
                let abs_path = normalize_path(&format!(
                    "{}/{}",
                    src_dir,
                    new_path.trim_end_matches('/')
                ));

                // Determine the page's directory-URL base
                let page_basename = file_stem(page_path);
                let page_url_dir = if page_basename == "index" {
                    src_dir.to_string()
                } else {
                    format!("{}/{}", src_dir, page_basename)
                };

                // Recompute relative path from directory-URL location
                new_path = relative_path(&abs_path, &page_url_dir);
                if had_trailing_slash && !new_path.ends_with('/') {
                    new_path.push('/');
                }
            }
        }

        // Reassemble
        let mut result = new_path;
        if let Some(q) = query {
            result.push('?');
            result.push_str(q);
        }
        if let Some(f) = fragment {
            result.push('#');
            result.push_str(f);
        }
        result
    }
}

/// Returns the parent directory of a path (POSIX-style).
fn parent_path(path: &str) -> &str {
    match path.rfind('/') {
        Some(pos) => &path[..pos],
        None => "",
    }
}

/// Returns the file stem (name without extension) of a path.
fn file_stem(path: &str) -> &str {
    let name = match path.rfind('/') {
        Some(pos) => &path[pos + 1..],
        None => path,
    };
    match name.rfind('.') {
        Some(pos) => &name[..pos],
        None => name,
    }
}

/// Normalizes a path by resolving `.` and `..` components.
fn normalize_path(path: &str) -> String {
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "." | "" => {}
            ".." => { parts.pop(); }
            _ => parts.push(part),
        }
    }
    parts.join("/")
}

/// Computes a relative path from `from_dir` to `to_path`.
fn relative_path(to_path: &str, from_dir: &str) -> String {
    let to_parts: Vec<&str> = to_path.split('/').filter(|s| !s.is_empty()).collect();
    let from_parts: Vec<&str> = from_dir.split('/').filter(|s| !s.is_empty()).collect();

    // Find common prefix length
    let common = to_parts.iter()
        .zip(from_parts.iter())
        .take_while(|(a, b)| a == b)
        .count();

    let ups = from_parts.len() - common;
    let mut result = String::new();
    for _ in 0..ups {
        result.push_str("../");
    }
    for (i, part) in to_parts[common..].iter().enumerate() {
        if i > 0 {
            result.push('/');
        }
        result.push_str(part);
    }

    if result.is_empty() {
        String::from(".")
    } else {
        result
    }
}
```

Note: Move the closing `}` of `impl HtmlProcessor` to be after `rewrite_href`, and place the free functions `parent_path`, `file_stem`, `normalize_path`, `relative_path` outside the impl block, before the `#[cfg(test)]` module.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib html::tests
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/html.rs
git commit -m "feat: add xref URL rewriting for directory URLs"
```

---

### Task 8: Module trait implementation and RenderedDoc type

**Files:**
- Modify: `~/zensical-asciidoctor-backend/src/lib.rs`

- [ ] **Step 1: Write test for AsciiDoc module construction**

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_asciidoc_module_default_config() {
        let module = AsciiDoc::new(Config::default());
        assert_eq!(module.config.asciidoctor_cmd, "asciidoctor");
    }

    #[test]
    fn test_asciidoc_module_custom_config() {
        let config = Config {
            asciidoctor_cmd: String::from("/usr/local/bin/asciidoctor"),
            ..Config::default()
        };
        let module = AsciiDoc::new(config);
        assert_eq!(module.config.asciidoctor_cmd, "/usr/local/bin/asciidoctor");
    }

    #[test]
    fn test_rendered_doc_value_impl() {
        // Verify RenderedDoc satisfies the trait bounds required by Value:
        // Any + Clone + Debug + Send + Sync
        fn assert_value<T: zrx::stream::Value>() {}
        assert_value::<RenderedDoc>();
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --lib tests
```

Expected: FAIL — `AsciiDoc` and `RenderedDoc` not defined.

- [ ] **Step 3: Implement lib.rs with AsciiDoc module and RenderedDoc**

Write `src/lib.rs`:

```rust
//! Zensical module for AsciiDoc support.
//!
//! This crate provides a Zensical module that renders AsciiDoc files using
//! the `asciidoctor` CLI and post-processes the HTML output for Material
//! theme compatibility.

pub mod config;
pub mod html;
pub mod renderer;

pub use config::Config;
pub use html::{DocMeta, ProcessedDoc, TocEntry};
pub use renderer::Renderer;

use std::collections::BTreeMap;

use zrx::module::{Context, Module};
use zrx::stream::Value;

/// Rendered document — compatible with Zensical's `Markdown` struct shape.
///
/// When Zensical exposes a public content type for modules, this struct
/// will be replaced with the canonical type.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RenderedDoc {
    /// Document title.
    pub title: String,
    /// Document metadata.
    pub meta: BTreeMap<String, String>,
    /// Rendered HTML content.
    pub content: String,
    /// Table of contents.
    pub toc: Vec<TocEntry>,
}

impl Value for RenderedDoc {}

/// Zensical module that adds AsciiDoc support via Asciidoctor.
pub struct AsciiDoc {
    config: Config,
}

impl AsciiDoc {
    /// Creates a new AsciiDoc module with the given configuration.
    pub fn new(config: Config) -> Self {
        Self { config }
    }
}

impl Module for AsciiDoc {
    fn setup(&self, ctx: &mut Context) -> zrx::module::Result {
        let files = ctx.add::<String>();

        // Filter for .adoc files
        let adoc_files = files.filter(|path: &String| {
            Ok(path.ends_with(".adoc"))
        });

        // Render and post-process
        let config = self.config.clone();
        adoc_files.map(move |path: &String| {
            let renderer = Renderer::new(&config);
            let raw_html = renderer.render(path)
                .map_err(|e| zrx::scheduler::step::Error::Panic(Box::new(e)))?;

            let processor = html::HtmlProcessor::new();
            let processed = processor.process(&raw_html, Some(path));

            let mut meta = BTreeMap::new();
            if let Some(title) = &processed.meta.title {
                meta.insert(String::from("title"), title.clone());
            }
            if let Some(desc) = &processed.meta.description {
                meta.insert(String::from("description"), desc.clone());
            }

            let title = processed.meta.title.clone()
                .unwrap_or_else(|| file_stem_title(path));

            Ok(RenderedDoc {
                title,
                meta,
                content: processed.html,
                toc: processed.toc,
            })
        });

        Ok(())
    }
}

/// Extracts a title from a file path by taking the stem and title-casing it.
fn file_stem_title(path: &str) -> String {
    let name = path.rsplit('/').next().unwrap_or(path);
    let stem = name.rsplit_once('.').map(|(s, _)| s).unwrap_or(name);
    let mut title = String::new();
    let mut capitalize_next = true;
    for ch in stem.chars() {
        if ch == '-' || ch == '_' {
            title.push(' ');
            capitalize_next = true;
        } else if capitalize_next {
            title.extend(ch.to_uppercase());
            capitalize_next = false;
        } else {
            title.push(ch);
        }
    }
    title
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_asciidoc_module_default_config() {
        let module = AsciiDoc::new(Config::default());
        assert_eq!(module.config.asciidoctor_cmd, "asciidoctor");
    }

    #[test]
    fn test_asciidoc_module_custom_config() {
        let config = Config {
            asciidoctor_cmd: String::from("/usr/local/bin/asciidoctor"),
            ..Config::default()
        };
        let module = AsciiDoc::new(config);
        assert_eq!(module.config.asciidoctor_cmd, "/usr/local/bin/asciidoctor");
    }

    #[test]
    fn test_rendered_doc_value_impl() {
        fn assert_value<T: Value>() {}
        assert_value::<RenderedDoc>();
    }

    #[test]
    fn test_file_stem_title() {
        assert_eq!(file_stem_title("docs/my-page.adoc"), "My Page");
        assert_eq!(file_stem_title("index.adoc"), "Index");
        assert_eq!(file_stem_title("getting_started.adoc"), "Getting Started");
    }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd ~/zensical-asciidoctor-backend && cargo test
```

Expected: all tests PASS. If compile errors occur due to zrx API differences (e.g., `filter` closure signature, `RendererError` not implementing the right conversion), fix the specific issues — the exact API may differ slightly from what's shown in the release notes.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add src/lib.rs
git commit -m "feat: add Module impl and RenderedDoc type"
```

---

### Task 9: Integration tests

**Files:**
- Create: `~/zensical-asciidoctor-backend/tests/integration.rs`
- Create: `~/zensical-asciidoctor-backend/tests/fixtures/simple.adoc`

- [ ] **Step 1: Create test fixture**

Create `tests/fixtures/simple.adoc`:

```asciidoc
= Simple Test Document
:description: A test document for integration testing

== Introduction

This is a simple test document.

NOTE: This is a note admonition.

== Code Example

[source,rust]
----
fn main() {
    println!("Hello"); // <1>
}
----
<1> Prints a greeting

== See Also

See xref:other.adoc[Other Page] for more info.

.A test table
|===
| Column 1 | Column 2

| data 1
| data 2
|===

.A test image
image::test.png[Test image]
```

- [ ] **Step 2: Create integration test**

Create `tests/integration.rs`:

```rust
//! Integration tests — require `asciidoctor` to be installed.
//! Run with: cargo test --features integration

#![cfg(feature = "integration")]

use zensical_asciidoctor_backend::config::Config;
use zensical_asciidoctor_backend::html::HtmlProcessor;
use zensical_asciidoctor_backend::renderer::Renderer;

#[test]
fn test_full_pipeline() {
    let config = Config::default();
    let renderer = Renderer::new(&config);

    let fixture = concat!(env!("CARGO_MANIFEST_DIR"), "/tests/fixtures/simple.adoc");
    let raw_html = renderer.render(fixture)
        .expect("asciidoctor should render successfully");

    assert!(!raw_html.is_empty());
    assert!(raw_html.contains("Simple Test Document"));

    let processor = HtmlProcessor::new();
    let result = processor.process(&raw_html, Some("docs/simple.adoc"));

    // Metadata
    assert_eq!(result.meta.title.as_deref(), Some("Simple Test Document"));
    assert_eq!(result.meta.description.as_deref(), Some("A test document for integration testing"));

    // TOC
    assert!(result.toc.len() >= 2);
    assert_eq!(result.toc[0].title, "Introduction");

    // Admonitions transformed
    assert!(result.html.contains("admonition note"));
    assert!(result.html.contains("admonition-title"));

    // Tables wrapped
    assert!(result.html.contains("md-typeset__table"));

    // Figures transformed
    assert!(result.html.contains("adoc-figure"));

    // Xref rewritten
    assert!(!result.html.contains("other.adoc"));
}

#[test]
fn test_renderer_error_on_missing_file() {
    let config = Config {
        fail_on_error: true,
        ..Config::default()
    };
    let renderer = Renderer::new(&config);
    let result = renderer.render("/nonexistent/file.adoc");
    assert!(result.is_err());
}

#[test]
fn test_renderer_graceful_on_missing_file() {
    let config = Config {
        fail_on_error: false,
        ..Config::default()
    };
    let renderer = Renderer::new(&config);
    let result = renderer.render("/nonexistent/file.adoc");
    // Should return an HTML error block rather than an error
    match result {
        Ok(html) => assert!(html.contains("admonition") || html.contains("Error")),
        Err(_) => panic!("should not error when fail_on_error is false"),
    }
}
```

- [ ] **Step 3: Run integration tests (if asciidoctor is available)**

```bash
cd ~/zensical-asciidoctor-backend && cargo test --features integration
```

Expected: PASS if asciidoctor is installed, skip if not.

- [ ] **Step 4: Run all unit tests to confirm nothing is broken**

```bash
cd ~/zensical-asciidoctor-backend && cargo test
```

Expected: all unit tests PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/zensical-asciidoctor-backend
git add tests/
git commit -m "feat: add integration tests with asciidoc fixture"
```

---

### Task 10: Final verification and cleanup

**Files:**
- Review: all files in `~/zensical-asciidoctor-backend/src/`

- [ ] **Step 1: Run clippy**

```bash
cd ~/zensical-asciidoctor-backend && cargo clippy -- -W clippy::pedantic 2>&1
```

Fix any warnings.

- [ ] **Step 2: Run all tests**

```bash
cd ~/zensical-asciidoctor-backend && cargo test
```

Expected: all tests PASS.

- [ ] **Step 3: Verify cargo doc builds**

```bash
cd ~/zensical-asciidoctor-backend && cargo doc --no-deps 2>&1
```

Expected: no errors.

- [ ] **Step 4: Remove unused imports and dead code**

Review each file for unused `use` statements or `#[allow(dead_code)]` that can be cleaned up.

- [ ] **Step 5: Final commit if any cleanup was done**

```bash
cd ~/zensical-asciidoctor-backend
git add -A
git commit -m "chore: clippy fixes and cleanup"
```

- [ ] **Step 6: Verify project structure matches spec**

```bash
ls -la ~/zensical-asciidoctor-backend/src/
# Expected: lib.rs, config.rs, renderer.rs, html.rs
```
