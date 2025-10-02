# asciidoctor_backend/renderer.py

"""
AsciiDoctor rendering module
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
                 trace: bool = False, edit_includes: bool = False,
                 edit_base_url: str = "", use_dir_urls: bool = True,
                 use_server: bool = False, server_socket: str = "/tmp/asciidoctor.sock"):
        self.cmd = cmd
        self.safe_mode = safe_mode
        self.base_dir = base_dir
        self.attributes = attributes or {}
        self.requires = requires or []
        self.fail_on_error = fail_on_error
        self.trace = trace
        self.edit_includes = edit_includes
        self.edit_base_url = edit_base_url
        self.use_dir_urls = use_dir_urls
        self.use_server = use_server
        self.server_socket = server_socket

        # Initialize HTML processor
        self.html_processor = HtmlProcessor(
            use_dir_urls=use_dir_urls,
            edit_includes=edit_includes,
            edit_base_url=edit_base_url
        )

        # Cache for rendered content
        self._cache: Dict[str, Tuple[float, Rendered]] = {}
        self._memo: Dict[str, Rendered] = {}

        # Server client (lazy initialization)
        self._server_client = None

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

        # Check cache
        cached = self._cache.get(key)
        if cached and mtime is not None and cached[0] == mtime:
            rendered = cached[1]
            self._memo[key] = rendered
            return rendered

        # Render fresh
        rendered = self._render_file(src_path)

        # Cache the result
        if mtime is not None:
            self._cache[key] = (mtime, rendered)
        self._memo[key] = rendered

        return rendered


    def render_fresh(self, src_path: pathlib.Path) -> Tuple[pathlib.Path, Rendered]:
        """Render a file fresh and return (source_path, rendered_result)."""
        rendered = self._render_file(src_path)
        return src_path, rendered

    def _render_file(self, src_path: pathlib.Path) -> Rendered:
        """Render a single AsciiDoc file."""
        html = self._run_asciidoctor(src_path)
        html, toc, meta = self.html_processor.postprocess_html(html)
        return Rendered(html=html, toc=toc, meta=meta)

    def start_server(self):
        """Start the server if use_server is enabled."""
        if self.use_server and self._server_client is None:
            from .asciidoctor_client import AsciidoctorServerClient

            # Get server script path
            assets = resources.files("asciidoctor_backend") / "assets"
            server_script = assets / "asciidoctor_server.rb"

            with resources.as_file(server_script) as script_path:
                self._server_client = AsciidoctorServerClient(
                    socket_path=self.server_socket,
                    server_script=script_path,
                    auto_start=True
                )
                self._server_client.ensure_server_running()

    def _get_server_client(self):
        """Get the server client (must be initialized first)."""
        if self._server_client is None:
            raise RuntimeError("Server client not initialized. Call start_server() first.")
        return self._server_client

    def _run_asciidoctor(self, src_path: pathlib.Path) -> str:
        """Execute asciidoctor command and return HTML."""
        if self.use_server:
            return self._run_via_server(src_path)
        else:
            return self._run_via_command(src_path)

    def _run_via_server(self, src_path: pathlib.Path) -> str:
        """Run asciidoctor via the server."""
        try:
            client = self._get_server_client()

            # Build attributes with sourcemap if edit_includes is enabled
            attributes = self.attributes.copy()
            requires = self.requires.copy()

            if self.edit_includes and self.edit_base_url:
                attributes['sourcemap'] = ''
                # Add include_edit.rb helper to requires
                assets = resources.files("asciidoctor_backend") / "assets"
                ruby_helper_res = assets / "include_edit.rb"
                try:
                    with resources.as_file(ruby_helper_res) as helper_path:
                        requires.append(str(helper_path))
                except FileNotFoundError:
                    pass

            response = client.convert_file(
                file_path=src_path,
                safe_mode=self.safe_mode,
                attributes=attributes,
                requires=requires,
                base_dir=self.base_dir
            )
            return response['html']

        except Exception as e:
            msg = f"Asciidoctor server failed for {src_path}:\n{str(e)}"
            if self.fail_on_error:
                raise SystemExit(msg)
            return f"<pre>{escape_html(msg)}</pre>"

    def _run_via_command(self, src_path: pathlib.Path) -> str:
        """Execute asciidoctor command and return HTML."""
        args = self._build_asciidoctor_args(src_path)

        try:
            proc = subprocess.run(args, check=True, capture_output=True, text=True)
            return proc.stdout

        except FileNotFoundError:
            msg = f"Asciidoctor not found: '{self.cmd}'. Install with: gem install asciidoctor"
            if self.fail_on_error:
                raise SystemExit(msg)
            return f"<pre>{escape_html(msg)}</pre>"

        except subprocess.CalledProcessError as e:
            stderr = e.stderr
            msg = f"Asciidoctor failed for {src_path}:\n{stderr}"
            if self.fail_on_error:
                raise SystemExit(msg)
            return f"<pre>{escape_html(msg)}</pre>"

    def _build_asciidoctor_args(self, src_path: pathlib.Path) -> List[str]:
        """Build command line arguments for asciidoctor."""
        args = [self.cmd, "-b", "html5", "-s", "-o", "-", str(src_path)]

        # Safety mode
        args.extend(["-S", self.safe_mode])

        # Required libraries
        for r in self.requires:
            args.extend(["-r", r])

        # Attributes
        for k, v in self.attributes.items():
            args.extend(["-a", f"{k}={v}"])

        # Optional flags
        if self.trace:
            args.append("--trace")

        # Include edit helper
        if self.edit_includes and self.edit_base_url:
            args.extend(["-a", "sourcemap"])
            self._add_include_edit_helper(args)

        return args

    def _add_include_edit_helper(self, args: List[str]):
        """Add include edit helper if available."""
        try:
            assets = resources.files("asciidoctor_backend") / "assets"
            ruby_helper_res = assets / "include_edit.rb"
            with resources.as_file(ruby_helper_res) as helper_path:
                args.extend(["-r", str(helper_path)])
        except FileNotFoundError:
            pass
