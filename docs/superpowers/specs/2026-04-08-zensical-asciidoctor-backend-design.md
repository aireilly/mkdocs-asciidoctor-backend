# Design: zensical-asciidoctor-backend

**Date:** 2026-04-08
**Status:** Approved
**Context:** Zensical module system (ZRX v0.0.17, ZAP 007)

## Summary

A Zensical module that adds AsciiDoc support to Zensical-powered sites. The module subscribes to file streams, filters for `.adoc` files, renders them via the `asciidoctor` CLI subprocess, post-processes the HTML for Material theme compatibility, and produces `Markdown` structs that feed into Zensical's existing page generation pipeline. Mixed AsciiDoc + Markdown sites are supported from day one.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rendering engine | Subprocess (`asciidoctor` CLI) | Proven, full-featured, same as Python plugin |
| HTML post-processing | Port to Rust (`scraper` crate) | Core to module purpose, well-understood transformations |
| Repository location | Standalone at `~/zensical-asciidoctor-backend` | Third-party module, independent versioning |
| Configuration scope | Essential subset | `asciidoctor_cmd`, `safe_mode`, `attributes`, `requires`, `fail_on_error` |
| Pipeline integration | Produce `Markdown` structs | Works with existing Zensical pipeline, no core changes |
| Architecture | Single-module monolith | Simple, matches Zensical patterns, internal separation sufficient |
| Mixed sites | Supported | Filter by extension, Markdown pipeline handles `.md` files |

## Project Structure

```
~/zensical-asciidoctor-backend/
├── Cargo.toml
├── LICENSE.md                  # MIT (matching zensical ecosystem)
├── README.md
├── src/
│   ├── lib.rs                  # Module impl + public API
│   ├── config.rs               # AsciiDoc config struct
│   ├── renderer.rs             # Asciidoctor subprocess execution
│   └── html.rs                 # HTML post-processing
```

### Dependencies

- `zrx` — module system, streams, identifiers (git dependency on `zensical/zrx`)
- `scraper` — HTML parsing and transformation
- `thiserror` — error types
- `tracing` — logging/diagnostics

### Dev Dependencies

- `insta` — snapshot testing for HTML transformations
- `pretty_assertions` — readable test diffs

### Public API

The crate exposes a single public type: `AsciiDoc` (the module struct).

## Module Implementation

The `AsciiDoc` struct holds configuration and implements `zrx::module::Module`. In `setup`, it subscribes to the file stream, filters for `.adoc` files, and wires up the rendering pipeline as stream operators.

```rust
use zrx::id::Id;
use zrx::module::{Module, Context, Result};
use zrx::stream::Stream;

pub struct AsciiDoc {
    config: Config,
}

impl Module for AsciiDoc {
    fn setup(&self, ctx: &mut Context) -> Result {
        // Subscribe to file paths from other modules
        let files: Stream<Id, String> = ctx.add();

        // Filter for .adoc files only
        let adoc_files = files.filter(with_id(|id: &Id, _: &String| {
            id.location().ends_with(".adoc")
        }));

        // Render and post-process, producing Markdown structs
        let config = self.config.clone();
        adoc_files.map(with_id(move |id: &Id, path: String| {
            let renderer = Renderer::new(&config);
            let raw_html = renderer.render(&path)?;
            let processor = HtmlProcessor::new(&config);
            let markdown = processor.process(id, &raw_html)?;
            Ok(markdown)
        }));

        Ok(())
    }
}
```

- `ctx.add::<String>()` creates a typed subscription that receives file paths from other modules
- `with_id` gives the closure access to both the `Id` and the value
- The filter uses `Id::location()` to match `.adoc` extensions
- Other files pass through untouched to the core Markdown pipeline

## Renderer

The renderer shells out to `asciidoctor` and captures HTML from stdout.

```rust
pub struct Renderer {
    cmd: String,
    safe_mode: SafeMode,
    attributes: HashMap<String, String>,
    requires: Vec<String>,
    fail_on_error: bool,
}
```

### Command Construction

Builds args equivalent to:

```
asciidoctor -b html5 -s -o - -S safe -a key=value -r library <file>
```

- `-b html5` — HTML5 backend
- `-s` — standalone mode (no header/footer wrapping)
- `-o -` — output to stdout
- `-S <mode>` — safe mode
- `-a key=value` — for each configured attribute
- `-r library` — for each required library

### Execution

Uses `std::process::Command` with stdout captured, stderr piped. On failure:

- If `fail_on_error` is true: returns an error that propagates through the stream
- If false: returns an HTML error block (styled as an admonition) so the build continues

### Error Types

- `RendererError::NotFound` — asciidoctor binary not on PATH
- `RendererError::Failed` — non-zero exit with stderr contents
- `RendererError::Io` — other I/O errors

## HTML Post-Processing

The `HtmlProcessor` transforms Asciidoctor's HTML output into Material-theme-compatible HTML and extracts metadata. Uses the `scraper` crate for tree traversal and DOM manipulation.

### Processing Pipeline (in order)

1. **Parse HTML** — Load into `scraper::Html` document
2. **Extract metadata** — Pull title from `<h1 class="sect0">`, description from `<meta name="description">`
3. **Extract & build TOC** — Collect h1-h6 headings (excluding sect0 title), generate IDs where missing, build nested TOC structure compatible with Zensical's navigation
4. **Transform admonitions** — Convert `<div class="admonitionblock note">` to `<div class="admonition note"><p class="admonition-title">Note</p>...`. Map types: `caution` to `warning`, `important` to `danger`
5. **Transform callout lists** — Convert `<div class="colist"><table>...` to `<ol class="colist"><li>...`
6. **Clean code callouts** — Remove textual callout markers `(1)`, `<1>` from code blocks, preserve `<span class="conum">` with `data-value`
7. **Transform tables** — Move `<div class="title">` to `<caption>`, wrap with `<div class="md-typeset__table">`
8. **Transform images** — Convert `<div class="imageblock">` to `<figure class="adoc-figure"><figcaption>...</figcaption><img/></figure>`
9. **Fix xref URLs** — Rewrite `.adoc` cross-references to match Zensical's directory-URL routing, resolving relative paths against the source file location

### Output

A `Markdown`-compatible struct containing processed HTML, TOC, and metadata — ready for Zensical's page generation pipeline. Since `Markdown` is currently internal to the `zensical` crate, the module defines its own `RenderedDoc` struct with the same shape. If/when Zensical exposes a public content type for modules, this struct will be replaced with the canonical type.

### Why `scraper` over `lol_html`

The transformations require tree traversal and parent/sibling navigation (e.g., finding a heading's parent section, moving nodes between elements). `lol_html` is streaming/SAX-style which makes these patterns awkward.

## Configuration

```rust
#[derive(Clone, Debug)]
pub struct Config {
    /// Path to asciidoctor binary (default: "asciidoctor")
    pub asciidoctor_cmd: String,

    /// Safe mode: unsafe, safe, server, secure (default: safe)
    pub safe_mode: SafeMode,

    /// Asciidoctor attributes passed as -a key=value
    pub attributes: HashMap<String, String>,

    /// Ruby libraries to require via -r
    pub requires: Vec<String>,

    /// Whether to fail the build on render errors (default: true)
    pub fail_on_error: bool,
}

#[derive(Clone, Debug, Default)]
pub enum SafeMode {
    Unsafe,
    #[default]
    Safe,
    Server,
    Secure,
}
```

### Default Attributes

Applied unless overridden by user configuration:

- `showtitle: ""` — render document title
- `sectanchors: ""` — add anchors to sections
- `source-highlighter: rouge` — syntax highlighting

### Usage

```rust
let module = AsciiDoc::new(Config {
    attributes: HashMap::from([
        ("imagesdir".into(), "images".into()),
    ]),
    ..Config::default()
});
```

## Error Handling

Errors are layered to integrate with the module system's `zrx::module::Error` enum:

- `RendererError` — subprocess failures (not found, non-zero exit, I/O)
- `HtmlError` — malformed HTML that can't be processed (missing expected structure)
- Both convert into `zrx::module::Error::Other` via the `IntoError` trait provided by `zrx-module`

When `fail_on_error` is false, rendering errors produce a styled error admonition in the HTML output rather than propagating.

## Testing Strategy

- **Unit tests for HTML processing** — Each transformation (admonitions, callouts, tables, figures, xrefs) gets its own test with `insta` snapshots. Input: raw Asciidoctor HTML fragments. Output: transformed HTML. No subprocess needed.
- **Unit tests for renderer command construction** — Verify correct `asciidoctor` args for various config combinations. No actual subprocess execution.
- **Integration tests** — Small `.adoc` files rendered through the full pipeline (requires `asciidoctor` installed). Gated behind `#[cfg(feature = "integration")]` so CI can skip if Ruby isn't available.
- **No module system tests** — Testing `setup` wiring requires the full ZRX scheduler, which is out of scope. The module is thin glue; the real logic lives in renderer and HTML processor, both independently testable.
