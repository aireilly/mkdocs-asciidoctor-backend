# asciidoctor_backend/plugin.py

"""
Main plugin module

The primary MkDocs plugin class that orchestrates all AsciiDoc processing:
- Plugin configuration and lifecycle management
- Integration with MkDocs hooks and events
- Coordination between file processing, rendering, and HTML processing
- Multi-threaded rendering support
- Asset deployment and management
"""

import os
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from mkdocs.config import config_options
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import Files
from mkdocs.structure.pages import Page

from .config import ConfigurationManager
from .file_processor import FileProcessor
from .renderer import AsciiDoctorRenderer
from .utils import safe_mtime


class AsciiDoctorPlugin(BasePlugin):
    """
    AsciiDoc backend for MkDocs 1.6+
    - Renders .adoc via Asciidoctor (content-only)
    - Injects HTML/TOC/meta
    - Ships CSS, copy-cleaner JS, and a small Ruby helper for "edit include" links
    """

    # User-facing configuration
    config_scheme = (
        ("asciidoctor_cmd", config_options.Type(str, default="asciidoctor")),
        ("safe_mode", config_options.Choice(["unsafe", "safe", "server", "secure"], default="safe")),
        ("base_dir", config_options.Type(str, default=None)),
        ("attributes", config_options.Type(dict, default={})),
        ("requires", config_options.Type(list, default=[])),
        ("fail_on_error", config_options.Type(bool, default=True)),
        ("trace", config_options.Type(bool, default=False)),
        ("max_workers", config_options.Type(int, default=0)),
        ("ignore_missing", config_options.Type(bool, default=False)),
        ("symlink_dirs", config_options.Type(list, default=["partials", "snippets", "modules", "assemblies"])),
        # Edit-includes feature
        ("edit_includes", config_options.Type(bool, default=False)),
        ("edit_base_url", config_options.Type(str, default="")),
        ("repo_root", config_options.Type(str, default=None)),
        # Long-running server feature
        ("use_server", config_options.Type(bool, default=True)),
        ("server_socket", config_options.Type(str, default="/tmp/asciidoctor.sock")),
    )

    def __init__(self):
        super().__init__()
        self.config_manager: Optional[ConfigurationManager] = None
        self.file_processor: Optional[FileProcessor] = None
        self.renderer: Optional[AsciiDoctorRenderer] = None

    # ---------- MkDocs lifecycle ----------

    def on_config(self, config: MkDocsConfig):
        # Initialize components
        self.config_manager = ConfigurationManager(self.config)
        self.file_processor = FileProcessor(
            ignore_missing=self.config["ignore_missing"],
            symlink_dirs=self.config["symlink_dirs"]
        )

        # Configure from MkDocs config
        config = self.config_manager.configure_from_mkdocs_config(config)

        # Initialize renderer with configuration
        self.renderer = AsciiDoctorRenderer(
            cmd=self.config_manager.cmd,
            safe_mode=self.config_manager.safe_mode,
            base_dir=self.config_manager.base_dir,
            attributes=self.config_manager.attributes,
            requires=self.config_manager.requires,
            fail_on_error=self.config_manager.fail_on_error,
            trace=self.config_manager.trace,
            edit_includes=self.config_manager.edit_includes,
            edit_base_url=self.config_manager.edit_base_url,
            use_dir_urls=bool(config.use_directory_urls),
            use_server=self.config["use_server"],
            server_socket=self.config["server_socket"]
        )

        # Start the server if enabled
        self.renderer.start_server()

        return config

    def on_files(self, files: Files, config: MkDocsConfig) -> Files:
        """Register .adoc pages and prune broken files if requested."""
        return self.file_processor.process_files(files, config)

    def on_nav(self, nav, config: MkDocsConfig, files: Files):
        """Render (or re-render) needed .adoc sources upfront (cache-aware)."""
        self.renderer.clear_memo()
        self.file_processor.clean_invalid_pages()

        to_build: List[pathlib.Path] = []

        for rel, p in list(self.file_processor.adoc_pages.items()):
            key = str(p)
            mtime = safe_mtime(p)
            if mtime is None:
                del self.file_processor.adoc_pages[rel]
                continue
            cached = self.renderer._cache.get(key)
            if not (cached and cached[0] == mtime):
                to_build.append(p)

        if not to_build:
            return

        # Use all available cores if max_workers is 0 (auto), otherwise respect the limit
        if self.config_manager.max_workers == 0:
            workers = os.cpu_count() or 1
        else:
            workers = max(1, min(self.config_manager.max_workers, (os.cpu_count() or 2)))
        if workers == 1:
            for p in to_build:
                src, rendered = self.renderer.render_fresh(p)
                mt = safe_mtime(src)
                if mt is not None:
                    self.renderer._cache[str(src)] = (mt, rendered)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(self.renderer.render_fresh, p): p for p in to_build}
                for fut in as_completed(futs):
                    src, rendered = fut.result()
                    mt = safe_mtime(src)
                    if mt is not None:
                        self.renderer._cache[str(src)] = (mt, rendered)

    def on_post_build(self, config: MkDocsConfig):
        """Write packaged CSS/JS into site/ so extra_css/extra_javascript resolve."""
        site_dir = pathlib.Path(config.site_dir)
        self.config_manager.write_assets_to_site(site_dir)

    # ---------- Page hooks ----------

    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        if self.file_processor.is_adoc_page(page):
            return ""  # prevent Markdown read
        return None

    def on_page_markdown(self, markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str:
        if not self.file_processor.is_adoc_page(page):
            return markdown
        src_abs = self.file_processor.get_adoc_path(page)
        rendered = self.renderer.render_adoc_cached(src_abs)
        page.meta = rendered.meta or {}
        page.file.abs_src_path = str(src_abs)
        return ""  # skip Markdown pipeline

    def on_page_content(self, html: str, page: Page, config: MkDocsConfig, files: Files) -> str:
        if not self.file_processor.is_adoc_page(page):
            return html
        src_abs = self.file_processor.get_adoc_path(page)
        rendered = self.renderer.render_adoc_cached(src_abs)
        page.toc = rendered.toc
        return rendered.html
