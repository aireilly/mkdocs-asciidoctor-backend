# asciidoctor_backend/config.py

"""
Configuration management module

Handles all configuration aspects of the AsciiDoctor plugin including:
- Plugin configuration parsing and validation
- Asset management (CSS, JS, Ruby helpers)
- Edit includes configuration
- Path resolution and setup
- Integration with MkDocs configuration
"""

import pathlib
from typing import Dict, List, Optional

from importlib import resources
from mkdocs.config.defaults import MkDocsConfig

from .utils import discover_git_root


class ConfigurationManager:
    def __init__(self, plugin_config: Dict):
        self.plugin_config = plugin_config
        self._setup_paths()
        self._setup_asciidoctor_config()
        self._setup_edit_includes_config()
        self._setup_assets()

    def _setup_paths(self):
        """Setup project and documentation paths."""
        # Will be set during on_config
        self.project_dir: Optional[pathlib.Path] = None
        self.docs_dir: Optional[pathlib.Path] = None
        self.base_dir: Optional[pathlib.Path] = None

    def _setup_asciidoctor_config(self):
        """Setup Asciidoctor command configuration."""
        self.cmd = self.plugin_config["asciidoctor_cmd"]
        self.safe_mode = self.plugin_config["safe_mode"]
        self.attributes = self.plugin_config["attributes"] or {}
        self.requires = self.plugin_config["requires"] or []
        self.fail_on_error = self.plugin_config["fail_on_error"]
        self.trace = self.plugin_config["trace"]
        self.max_workers = self.plugin_config["max_workers"]
        self.ignore_missing = self.plugin_config["ignore_missing"]

    def _setup_edit_includes_config(self):
        """Setup edit includes configuration."""
        self.edit_includes = bool(self.plugin_config.get("edit_includes", False))
        self.edit_base_url = ""
        self.repo_root: Optional[pathlib.Path] = None

    def _setup_assets(self):
        """Setup packaged assets configuration."""
        assets = resources.files(__package__) / "assets"
        self.pkg_css_href = "assets/asciidoc.css"
        self.pkg_css_res = assets / "asciidoc.css"
        self.pkg_js_href = "assets/strip_callouts.js"
        self.pkg_js_res = assets / "strip_callouts.js"
        self.ruby_inc_helper_res = assets / "include_edit.rb"

    def configure_from_mkdocs_config(self, config: MkDocsConfig) -> MkDocsConfig:
        """Configure plugin from MkDocs configuration."""
        # Setup paths
        self.project_dir = pathlib.Path(config.config_file_path).parent.resolve()
        self.docs_dir = pathlib.Path(config.docs_dir).resolve()

        # Determine base directory
        base_dir_opt = self.plugin_config.get("base_dir")
        self.base_dir = (
            (self.project_dir / base_dir_opt).resolve()
            if base_dir_opt
            else self.docs_dir
        )

        # Configure edit includes
        if self.edit_includes:
            self._configure_edit_includes(config)

        # Add CSS/JS to MkDocs config
        config.extra_css.append(self.pkg_css_href)
        config.extra_javascript.append(self.pkg_js_href)

        return config

    def _configure_edit_includes(self, config: MkDocsConfig):
        """Configure edit includes functionality."""
        base = (getattr(config, "repo_url", "") or "").rstrip("/")
        edit_uri = (getattr(config, "edit_uri", "") or "").lstrip("/")
        override = (self.plugin_config.get("edit_base_url") or "").strip()

        if base and edit_uri:
            self.edit_base_url = f"{base}/{edit_uri}".rstrip("/") + "/"
        elif override:
            self.edit_base_url = override.rstrip("/") + "/"

        repo_root_opt = self.plugin_config.get("repo_root")
        self.repo_root = (
            pathlib.Path(repo_root_opt).resolve()
            if repo_root_opt
            else discover_git_root(self.project_dir) or self.project_dir
        )

        if self.edit_base_url:
            self.attributes["edit-base"] = self.edit_base_url
            self.attributes["repo-root"] = str(self.repo_root)
        else:
            # No valid base: disable feature silently
            self.edit_includes = False

    def write_assets_to_site(self, site_dir: pathlib.Path):
        """Write packaged CSS/JS to site directory."""
        for res, href in ((self.pkg_css_res, self.pkg_css_href), (self.pkg_js_res, self.pkg_js_href)):
            out = site_dir / href
            out.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(res) as src_path:
                out.write_bytes(pathlib.Path(src_path).read_bytes())
