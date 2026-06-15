"""Regression tests for xref resolution.

Covers:
* Bug 1 — ``on_files`` refreshes ``renderer.docs_dir`` after a post-``on_config``
  ``docs_dir`` swap (as done by mkdocs-monorepo-plugin / mkdocs-techdocs-core).
* Bug 2 — links to index pages resolve to the directory root, not ``.../index/``.
"""

import pathlib
import types

from asciidoctor_backend.html_processor import HtmlProcessor


# --- Bug 2: index-target resolution -------------------------------------------

def test_xref_from_toplevel_page_to_root_index():
    # page.adoc is served at /page/; the site root is one level up.
    hp = HtmlProcessor(use_dir_urls=True)
    html = '<a href="index.adoc">home</a>'
    out, _, _ = hp.postprocess_html(html, "page.adoc")
    assert '<a href="../">home</a>' in out      # not "../index/"


def test_xref_from_nested_page_to_root_index():
    # sub/page.adoc is served at /sub/page/; the site root is two levels up.
    hp = HtmlProcessor(use_dir_urls=True)
    html = '<a href="../index.adoc">home</a>'
    out, _, _ = hp.postprocess_html(html, "sub/page.adoc")
    assert '<a href="../../">home</a>' in out    # not "../index/"


def test_xref_to_nested_index_resolves_to_section_dir():
    hp = HtmlProcessor(use_dir_urls=True)
    html = '<a href="section/index.adoc">section</a>'
    out, _, _ = hp.postprocess_html(html, "index.adoc")
    assert '<a href="section/">section</a>' in out   # not "section/index/"


def test_no_bogus_index_path_segment():
    hp = HtmlProcessor(use_dir_urls=True)
    html = '<a href="index.adoc">home</a>'
    out, _, _ = hp.postprocess_html(html, "guide.adoc")
    assert "index/" not in out


# --- Bug 1: docs_dir refresh in on_files --------------------------------------

def test_on_files_refreshes_renderer_docs_dir(tmp_path):
    from asciidoctor_backend.plugin import AsciiDoctorPlugin
    from asciidoctor_backend.file_processor import FileProcessor
    from mkdocs.structure.files import Files

    swapped_docs = tmp_path / "swapped_docs"
    swapped_docs.mkdir()

    plugin = AsciiDoctorPlugin()
    plugin.file_processor = FileProcessor()
    # Stand-in renderer holding a stale docs_dir, as after on_config.
    plugin.renderer = types.SimpleNamespace(docs_dir=pathlib.Path("/original/docs"))

    config = types.SimpleNamespace(
        docs_dir=str(swapped_docs),
        site_dir=str(tmp_path / "site"),
        use_directory_urls=True,
    )

    plugin.on_files(Files([]), config)

    assert plugin.renderer.docs_dir == swapped_docs.resolve()
