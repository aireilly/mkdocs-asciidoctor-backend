# asciidoctor_backend/file_processor.py

"""
File processing module

Handles file discovery, validation, and processing:
- AsciiDoc file discovery and registration
- File validation and missing file handling
- URL and destination path computation
- Integration with MkDocs file system
- Page type detection and management
"""

import os
import pathlib
from typing import Dict

from mkdocs.structure.files import File, Files
from mkdocs.config.defaults import MkDocsConfig

from .utils import is_valid_adoc_path


class FileProcessor:
    def __init__(self, ignore_missing: bool = False):
        self.ignore_missing = ignore_missing
        self.adoc_pages: Dict[str, pathlib.Path] = {}

    def process_files(self, files: Files, config: MkDocsConfig) -> Files:
        """Process files: remove .adoc from static files, add as documentation pages."""
        src_dir = pathlib.Path(config.docs_dir).resolve()
        site_dir = pathlib.Path(config.site_dir)

        # Remove .adoc files that were discovered through symlinked directories
        # But allow static files (images, etc.) through symlinks
        for f in list(files):
            try:
                # Only filter out .adoc files from symlinked directories
                if not f.src_path.endswith('.adoc'):
                    continue

                src_path = pathlib.Path(f.abs_src_path) if hasattr(f, 'abs_src_path') and f.abs_src_path else (pathlib.Path(f.src_dir) / f.src_path)
                if self._is_inside_symlink(src_path.resolve(), src_dir):
                    files.remove(f)
                    continue
            except (OSError, ValueError):
                # If we can't resolve the path, skip it
                pass

        # Remove .adoc files that MkDocs may have detected as static
        for f in list(files):
            if f.src_path.endswith(".adoc"):
                files.remove(f)

        # Optionally remove missing files that belong to docs_dir
        if self.ignore_missing:
            self._remove_missing_files(files, src_dir)

        # Add .adoc as documentation pages (exclude partials)
        self._add_adoc_pages(files, src_dir, site_dir, config)

        return files

    def _remove_missing_files(self, files: Files, src_dir: pathlib.Path):
        """Remove missing files from the file collection."""
        for f in list(files):
            try:
                base = pathlib.Path(f.src_dir).resolve()
            except Exception:
                continue
            if base != src_dir:
                continue
            abs_src = (
                pathlib.Path(getattr(f, "abs_src_path", ""))
                if getattr(f, "abs_src_path", None)
                else (base / f.src_path)
            )
            try:
                if (not abs_src.exists()) or abs_src.is_dir():
                    files.remove(f)
            except OSError:
                files.remove(f)

    def _is_inside_symlink(self, path: pathlib.Path, base: pathlib.Path) -> bool:
        """Check if path is inside a symlinked directory.

        Returns True if any parent directory component is a symlink.
        """
        try:
            rel_parts = path.relative_to(base).parts[:-1]  # exclude filename
            current = base
            for part in rel_parts:
                current = current / part
                if current.is_symlink():
                    return True
            return False
        except (ValueError, OSError):
            return False

    def _add_adoc_pages(self, files: Files, src_dir: pathlib.Path, site_dir: pathlib.Path, config: MkDocsConfig):
        """Add .adoc files as documentation pages."""
        for root, dirs, filenames in os.walk(src_dir, followlinks=False):
            for filename in filenames:
                if not filename.endswith('.adoc'):
                    continue
                p = pathlib.Path(root) / filename
                if not is_valid_adoc_path(p):
                    continue

                # Skip files inside symlinked directories
                if self._is_inside_symlink(p, src_dir):
                    continue

                rel = p.relative_to(src_dir).as_posix()

                f = File(
                    rel,
                    src_dir=str(src_dir),
                    dest_dir=config.site_dir,
                    use_directory_urls=config.use_directory_urls
                )
                f.is_documentation_page = (lambda f=f: True)  # MkDocs 1.6

                # Set abs_src_path so watchdog can track changes
                f.abs_src_path = str(p)

                self.adoc_pages[rel] = p

                # Compute dest_path + url (mirror Markdown behavior)
                dest_path, url = self._compute_dest_path_and_url(f, config)
                f.dest_path = dest_path
                f.abs_dest_path = str(site_dir / dest_path)
                f.url = url
                files.append(f)

    def _compute_dest_path_and_url(self, f: File, config: MkDocsConfig) -> tuple[str, str]:
        """Compute destination path and URL for an AsciiDoc file."""
        src = pathlib.Path(f.src_path)
        stem, parent = src.stem, src.parent.as_posix()

        if stem == "index":
            if parent in ("", "."):
                dest_path, url = "index.html", ""
            else:
                dest_path, url = f"{parent}/index.html", f"{parent}/"
        else:
            if config.use_directory_urls:
                if parent in ("", "."):
                    dest_path, url = f"{stem}/index.html", f"{stem}/"
                else:
                    dest_path, url = f"{parent}/{stem}/index.html", f"{parent}/{stem}/"
            else:
                if parent in ("", "."):
                    dest_path = f"{stem}.html"
                    url = dest_path
                else:
                    dest_path = f"{parent}/{stem}.html"
                    url = dest_path

        return dest_path, url

    def is_adoc_page(self, page) -> bool:
        """Check if a page is an AsciiDoc page."""
        return page.file.src_uri in self.adoc_pages

    def get_adoc_path(self, page) -> pathlib.Path:
        """Get the absolute path for an AsciiDoc page."""
        return self.adoc_pages[page.file.src_uri]

    def clean_invalid_pages(self):
        """Remove invalid AsciiDoc pages from the collection."""
        for rel, p in list(self.adoc_pages.items()):
            if not is_valid_adoc_path(p):
                del self.adoc_pages[rel]
