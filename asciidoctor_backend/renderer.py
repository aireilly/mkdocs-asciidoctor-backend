# asciidoctor_backend/renderer.py

"""
AsciiDoctor rendering module

Core rendering functionality for AsciiDoc files:
- Asciidoctor command execution and configuration
- HTML generation from AsciiDoc source
- Caching and memoization of rendered content
- Error handling for missing files and rendering failures
- Integration with HTML post-processing
"""

import pathlib
import subprocess
from typing import Dict, List, Optional, Tuple

from importlib import resources

from .html_processor import HtmlProcessor
from .models import Rendered
from .utils import escape_html, safe_mtime


class AsciiDoctorRenderer:
    def __init__(self, cmd: str = "asciidoctor", safe_mode: str = "safe",
                 base_dir: Optional[pathlib.Path] = None, attributes: Optional[Dict] = None,
                 requires: Optional[List[str]] = None, fail_on_error: bool = True,
                 trace: bool = False, ignore_missing: bool = False,
                 edit_includes: bool = False, edit_base_url: str = "",
                 repo_root: Optional[pathlib.Path] = None, use_dir_urls: bool = True):
        self.cmd = cmd
        self.safe_mode = safe_mode
        self.base_dir = base_dir
        self.attributes = attributes or {}
        self.requires = requires or []
        self.fail_on_error = fail_on_error
        self.trace = trace
        self.ignore_missing = ignore_missing
        self.edit_includes = edit_includes
        self.edit_base_url = edit_base_url
        self.repo_root = repo_root
        self.use_dir_urls = use_dir_urls

        # Initialize HTML processor
        self.html_processor = HtmlProcessor(
            use_dir_urls=use_dir_urls,
            edit_includes=edit_includes,
            edit_base_url=edit_base_url
        )

        # Cache for rendered content
        self._cache: Dict[str, Tuple[float, Rendered]] = {}
        self._memo: Dict[str, Rendered] = {}

    def clear_memo(self):
        """Clear the per-build memo cache."""
        self._memo = {}

    def render_adoc_cached(self, src_path: pathlib.Path) -> Rendered:
        """Render AsciiDoc file with caching."""
        key = str(src_path)

        # Check memo first
        memo_hit = self._memo.get(key)
        if memo_hit:
            return memo_hit

        mtime = safe_mtime(src_path)
        if mtime is None:
            msg = f"AsciiDoc source missing or broken symlink: {src_path}"
            if self.fail_on_error and not self.ignore_missing:
                raise SystemExit(msg)
            from mkdocs.structure.toc import TableOfContents as Toc
            return Rendered(html=f"<pre>{escape_html(msg)}</pre>", toc=Toc([]), meta={})

        # Check cache
        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            rendered = cached[1]
            self._memo[key] = rendered
            return rendered

        # Render fresh
        src, rendered = self.render_fresh(src_path)
        mt = safe_mtime(src)
        if mt is not None:
            self._cache[str(src)] = (mt, rendered)
        self._memo[key] = rendered
        return rendered

    def render_fresh(self, src: pathlib.Path) -> Tuple[pathlib.Path, Rendered]:
        """Render AsciiDoc file without caching."""
        html = self._run_asciidoctor(src)
        html, toc, meta = self.html_processor.postprocess_html(html)
        return src, Rendered(html=html, toc=toc, meta=meta)

    def _run_asciidoctor(self, src: pathlib.Path) -> str:
        """Execute asciidoctor command and return HTML."""
        args = [self.cmd, "-b", "html5", "-s", "-o", "-", str(src)]
        args[1:1] = ["-S", self.safe_mode]

        if self.base_dir:
            args.extend(["-B", str(self.base_dir)])

        for r in self.requires:
            args.extend(["-r", r])

        for k, v in self.attributes.items():
            args.extend(["-a", f"{k}={v}"])

        if self.trace:
            args.append("--trace")

        if self.ignore_missing:
            args.extend(["--failure-level", "FATAL"])

        # Enable include-edit helper when configured
        if self.edit_includes and self.edit_base_url:
            args.extend(["-a", "sourcemap"])
            try:
                assets = resources.files("asciidoctor_backend") / "assets"
                ruby_helper_res = assets / "include_edit.rb"
                with resources.as_file(ruby_helper_res) as helper_path:
                    args.extend(["-r", str(helper_path)])
            except FileNotFoundError:
                pass  # helper missing; continue without markers

        try:
            proc = subprocess.run(args, check=True, capture_output=True)
            return proc.stdout.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            msg = f"Asciidoctor not found: '{self.cmd}'. Install with: gem install asciidoctor"
            if self.fail_on_error and not self.ignore_missing:
                raise SystemExit(msg)
            return f"<pre>{escape_html(msg)}</pre>"
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore")
            if self.ignore_missing or not self.fail_on_error:
                if any(s in stderr.lower() for s in ("no such file or directory", "include file not found", "enoent", "cannot open")):
                    return (
                        f"<pre>{escape_html(f'Asciidoctor warning for {src} (missing content ignored):')}\n"
                        f"{escape_html(stderr)}</pre>"
                    )
            raise SystemExit(f"Asciidoctor failed for {src}:\n{stderr}")
