# Getting started

Use AsciiDoc with Material for MkDocs.

This MkDocs plugin replaces the MkDocs default Markdown processor with [Asciidoctor](https://asciidoctor.org/) for AsciiDoc files, allowing you to write documentation in AsciiDoc while keeping full compatibility with Material for MkDocs. 

It runs the Ruby Asciidoctor CLI to render `*.adoc` files, normalizes the output HTML with BeautifulSoup, and adjusts it to match MkDocs conventions.
The plugin ships some CSS/JS/RB and optionally injects "edit this page" links for included AsciiDoc modules when `repo_url` and `edit_uri` are configured.

Supports hot reload on the development server for all AsciiDoc source files  when writing.

Asciidoctor attributes can be injected via the `mkdocs.yml`:

```yaml
plugins:
  - asciidoctor_backend:
      edit_includes: true
      fail_on_error: false
      ignore_missing: true
      safe_mode: safe
      base_dir: docs
      attributes:
        imagesdir: images
        showtitle: true
        sectanchors: true
        sectlinks: true
        icons: font
        idprefix: ""
        idseparator: "-"
        outfilesuffix: .html
        source-highlighter: rouge
```
