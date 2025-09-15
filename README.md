# Getting started

Use AsciiDoc with Material for MkDocs.

> [!IMPORTANT]
> This is a very early Alpha release and not suitable for production

This MkDocs plugin replaces the MkDocs default Markdown processor with [Asciidoctor](https://asciidoctor.org/) for AsciiDoc files, allowing you to write documentation in AsciiDoc while keeping full compatibility with Material for MkDocs. 

It runs the Ruby Asciidoctor CLI to render `*.adoc` files, normalizes the output HTML with BeautifulSoup, and adjusts it to match MkDocs conventions.
The plugin ships some CSS/JS/RB and optionally injects "edit this page" links for included AsciiDoc modules when `repo_url` and `edit_uri` are configured.

Supports hot reload on the development server for all AsciiDoc source files  when writing.

Asciidoctor attributes can be injected via the `mkdocs.yml`.

## Installing

```cmd
pip install mkdocs-material
```

The following example `mkdocs.yml` can be dropped into the root of an existing AsciiDoc project. 

AsciiDoc must be in the MkDocs default `docs/` folder. To control the left hand navigation, add `nav` items to the `mkdocs.yml`.

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
      edit_includes: true
      fail_on_error: false
      ignore_missing: true
      safe_mode: safe
      base_dir: .
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
        "!toc": "" # Unset the TOC
```

Start the server:

```cmd
mkdocs serve -f mkdocs.yml
```