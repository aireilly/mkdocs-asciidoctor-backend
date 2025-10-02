# Getting started

Use AsciiDoc with Material for MkDocs.

> [!IMPORTANT]
> This package is an early release. The API may change without notice, and stability is not guaranteed. Use in production environments is not recommended. Feedback and testing are welcome.

This MkDocs plugin replaces the MkDocs default Markdown processor with [Asciidoctor](https://asciidoctor.org/) for AsciiDoc files, allowing you to write documentation in AsciiDoc while keeping full compatibility with Material for MkDocs.

It uses a long-running Ruby Asciidoctor backend server for fast rendering of `*.adoc` files, normalizes the output HTML with BeautifulSoup, and adjusts it to match MkDocs conventions.
The plugin ships some CSS/JS/RB and optionally injects "edit this page" links for included AsciiDoc modules when `repo_url` and `edit_uri` are configured.

Supports hot reload on the development server for all AsciiDoc source files when writing.

Asciidoctor attributes can be injected via the `mkdocs.yml`.

## Using mkdocs-asciidoctor-backend

```bash
pip install mkdocs-asciidoctor-backend --upgrade --pre
```

> [!IMPORTANT]
>
> - MkDocs expects docs source in a `docs/` folder. See [Strategy for including docs from repository root](https://github.com/mkdocs/mkdocs/discussions/3062) for further discussion.
> 
> - For larger doc sets, set up a `nav` element in the `mkdocs.yml`, and optionally a root `docs/index.adoc` file. See [nav](https://www.mkdocs.org/user-guide/configuration/#nav) for more details.
> 
> - Asciidoctor xrefs might require you to set `relfileprefix` either globally in `mkdocs.yml` or per section/assembly file.

The following example `mkdocs.yml` can be dropped into the root of an existing AsciiDoc project. 

```yaml
site_name: Example
repo_url: https://github.com/example/repo
repo_name: example-repo
edit_uri: edit/main/

theme:
  name: material
  features:
    - content.action.edit
    - content.code.annotate
    - content.code.copy
    - content.code.select
    - navigation.footer
    - navigation.top
    - navigation.tracking
    - palette.toggle
    - search.highlight
    - search.suggest
    - toc.follow
    - toc.sticky
  palette:
    - scheme: default
      primary: indigo
      accent: indigo
      toggle:
        icon: material/toggle-switch-off-outline
        name: Switch to dark mode
    - scheme: slate
      primary: indigo
      accent: indigo
      toggle:
        icon: material/toggle-switch
        name: Switch to light mode

exclude_docs: |
  partials/**
  snippets/**
  modules/**

plugins:
  - search
  - asciidoctor_backend:
      symlink_dirs: ["partials", "snippets", "modules", "assemblies"] #configure project symlink folders to ignore
      edit_includes: true
      fail_on_error: false
      ignore_missing: true
      safe_mode: safe
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

A demo docs site is published here: https://aireilly.github.io/mkdocs-asciidoctor-backend/
