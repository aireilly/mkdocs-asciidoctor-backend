# asciidoc_backend/__init__.py
import pathlib
import subprocess
import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List

from bs4 import BeautifulSoup
from importlib import resources
from mkdocs.plugins import BasePlugin
from mkdocs.config import config_options
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.structure.files import Files, File
from mkdocs.structure.pages import Page
from mkdocs.structure.toc import TableOfContents as Toc, AnchorLink  # MkDocs 1.6+

@dataclass
class Rendered:
    html: str
    toc: Toc
    meta: dict


class AsciiDocPlugin(BasePlugin):
    """
    True AsciiDoc backend for MkDocs 1.6+
    - Renders .adoc via Asciidoctor
    - Injects HTML/TOC/meta
    - Ships CSS and an Antora-like copy cleaner JS (no user config needed)
    """
    config_scheme = (
        ("asciidoctor_cmd", config_options.Type(str, default="asciidoctor")),
        ("safe_mode", config_options.Choice(["unsafe", "safe", "server", "secure"], default="safe")),
        ("base_dir", config_options.Type(str, default=None)),
        ("attributes", config_options.Type(dict, default={})),
        ("requires", config_options.Type(list, default=[])),
        ("fail_on_error", config_options.Type(bool, default=True)),
        ("trace", config_options.Type(bool, default=False)),
    )

    _cache: Dict[str, Tuple[float, str, Rendered]]

    def on_config(self, config: MkDocsConfig):
        self._cache = {}
        self._adoc_pages: Dict[str, pathlib.Path] = {}

        self._project_dir = pathlib.Path(config.config_file_path).parent.resolve()
        self._docs_dir = pathlib.Path(config.docs_dir).resolve()

        base_dir_opt = self.config.get("base_dir")
        self._base_dir = (self._project_dir / base_dir_opt).resolve() if base_dir_opt else self._docs_dir

        self._cmd = self.config["asciidoctor_cmd"]
        self._safe = self.config["safe_mode"]
        self._attrs = self.config["attributes"] or {}
        self._reqs = self.config["requires"] or []
        self._fail = self.config["fail_on_error"]
        self._trace = self.config["trace"]

        # Ship CSS + JS from our package
        self._pkg_css_res = resources.files(__package__) / "assets" / "asciidoc.css"
        self._pkg_js_res  = resources.files(__package__) / "assets" / "strip_callouts.js"
        self._pkg_css_href = "assets/asciidoc.css"
        self._pkg_js_href  = "assets/strip_callouts_like_antora.js"

        # Auto-include into the theme
        config.extra_css.append(self._pkg_css_href)
        config.extra_javascript.append(self._pkg_js_href)
        return config

    def on_files(self, files: Files, config: MkDocsConfig) -> Files:
        src_dir = pathlib.Path(config.docs_dir).resolve()
        site_dir = pathlib.Path(config.site_dir)

        # Remove .adoc that MkDocs may have treated as media
        for f in list(files):
            if f.src_path.endswith(".adoc"):
                files.remove(f)

        # Add .adoc as documentation pages (exclude common partials)
        for p in src_dir.rglob("*.adoc"):
            rel = p.relative_to(src_dir).as_posix()
            if rel.startswith(("partials/", "snippets/", "modules/")):
                continue

            f = File(
                rel,
                src_dir=str(src_dir),
                dest_dir=config.site_dir,
                use_directory_urls=config.use_directory_urls,
            )

            # MkDocs 1.6 expects a callable
            f.is_documentation_page = (lambda f=f: True)

            self._adoc_pages[rel] = p

            # Compute dest_path + url like Markdown pages
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
                        dest_path = f"{stem}.html"; url = dest_path
                    else:
                        dest_path = f"{parent}/{stem}.html"; url = dest_path

            f.dest_path = dest_path
            f.abs_dest_path = str(site_dir / dest_path)
            f.url = url
            files.append(f)

        return files

    def on_post_build(self, config: MkDocsConfig):
        """Write packaged CSS/JS into site/ so extra_css/extra_javascript resolve."""
        site_dir = pathlib.Path(config.site_dir)

        for res, href in ((self._pkg_css_res, self._pkg_css_href),
                          (self._pkg_js_res,  self._pkg_js_href)):
            out = site_dir / href
            out.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(res) as src_path:
                out.write_bytes(pathlib.Path(src_path).read_bytes())

    # ---------- Page pipeline ----------

    def _is_adoc_page(self, page: Page) -> bool:
        return page.file.src_uri in self._adoc_pages

    def on_page_read_source(self, page: Page, config: MkDocsConfig) -> Optional[str]:
        if self._is_adoc_page(page):
            return ""  # prevent Markdown read
        return None

    def on_page_markdown(self, markdown: str, page: Page, config: MkDocsConfig, files: Files) -> str:
        if not self._is_adoc_page(page):
            return markdown
        src_abs = self._adoc_pages[page.file.src_uri]
        rendered = self._render_adoc_cached(src_abs)
        page.meta = rendered.meta or {}
        page.file.abs_src_path = str(src_abs)
        return ""  # skip Markdown pipeline

    def on_page_content(self, html: str, page: Page, config: MkDocsConfig, files: Files) -> str:
        if not self._is_adoc_page(page):
            return html
        src_abs = self._adoc_pages[page.file.src_uri]
        rendered = self._render_adoc_cached(src_abs)
        page.toc = rendered.toc  # populate RHS ToC

        fixed = self._admonitions_to_material(rendered.html)
        fixed = self._callout_table_to_ol(fixed)
        fixed = self._strip_conum_from_code(fixed)  # visible bubbles; not copied
        return fixed

    # ---------- Internals ----------

    def _render_adoc_cached(self, src_path: pathlib.Path) -> Rendered:
        key = str(src_path)
        mtime = src_path.stat().st_mtime
        sha1 = self._sha1_file(src_path)
        cached = self._cache.get(key)
        if cached and cached[0] == mtime and cached[1] == sha1:
            return cached[2]
        html, meta = self._run_asciidoctor(src_path)
        toc = self._build_toc(html)
        rendered = Rendered(html=html, toc=toc, meta=meta)
        self._cache[key] = (mtime, sha1, rendered)
        return rendered

    def _run_asciidoctor(self, src: pathlib.Path) -> Tuple[str, dict]:
        args = [self._cmd, "-b", "html5", "-s", "-o", "-", str(src)]
        args[1:1] = ["-S", self._safe]
        args.extend(["-B", str(self._base_dir)])
        for r in self._reqs:
            args.extend(["-r", r])
        for k, v in (self._attrs or {}).items():
            args.extend(["-a", f"{k}={v}"])
        if self._trace:
            args.append("--trace")
        try:
            proc = subprocess.run(args, check=True, capture_output=True)
        except FileNotFoundError:
            msg = f"Asciidoctor not found: '{self._cmd}'. Install with: gem install asciidoctor"
            if self._fail:
                raise SystemExit(msg)
            return f"<pre>{self._escape(msg)}</pre>", {}
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore")
            msg = f"Asciidoctor failed for {src}:\n{stderr}"
            if self._fail:
                raise SystemExit(msg)
            return f"<pre>{self._escape(msg)}</pre>", {}
        html = proc.stdout.decode("utf-8", errors="ignore")
        meta = self._extract_meta_from_html(html)
        return html, meta

    def _build_toc(self, html: str) -> Toc:
        soup = BeautifulSoup(html, "html.parser")
        # Skip Asciidoctor doc title (sect0)
        headings = [
            h for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if not (h.name == "h1" and "sect0" in (h.get("class") or []))
        ]
        for h in headings:
            if not h.get("id"):
                h["id"] = self._slugify(h.get_text(" ", strip=True))

        # MkDocs 1.6: AnchorLink(title, id_without_hash, children)
        def make_anchor(title: str, hid: str) -> AnchorLink:
            return AnchorLink(title, hid, [])

        items: List[AnchorLink] = []
        stack: List[Tuple[int, AnchorLink]] = []
        for h in headings:
            level = int(h.name[1])
            node = make_anchor(h.get_text(" ", strip=True), h["id"])
            while stack and stack[-1][0] >= level:
                stack.pop()
            (items if not stack else stack[-1][1].children).append(node)
            stack.append((level, node))
        return Toc(items)

    def _admonitions_to_material(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        kinds = {"note", "tip", "important", "caution", "warning"}
        for blk in soup.select("div.admonitionblock"):
            classes = set(blk.get("class", []))
            kind = next((k for k in kinds if k in classes), "note")
            content = blk.select_one(".content") or blk
            title_el = content.select_one(".title")
            title_text = title_el.get_text(" ", strip=True) if title_el else kind.capitalize()
            if title_el:
                title_el.extract()
            new = soup.new_tag("div"); new["class"] = ["admonition", kind]
            title_p = soup.new_tag("p"); title_p["class"] = ["admonition-title"]; title_p.string = title_text
            new.append(title_p)
            for child in list(content.children):
                new.append(child.extract())
            blk.replace_with(new)
        return str(soup)

    def _callout_table_to_ol(self, html: str) -> str:
        """Rewrite <div class='colist'><table>…</table></div> -> <ol class='colist'>…</ol>."""
        soup = BeautifulSoup(html, "html.parser")
        for colist in soup.select("div.colist"):
            table = colist.find("table")
            if not table:
                continue
            rows = table.find_all("tr")
            if not rows:
                continue
            ol = soup.new_tag("ol", **{"class": "colist"})
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                li = soup.new_tag("li")
                li.append(BeautifulSoup(tds[1].decode_contents(), "html.parser"))
                ol.append(li)
            table.replace_with(ol)
        return str(soup)

    def _strip_conum_from_code(self, html: str) -> str:
        """
        Keep visible callout bubbles but prevent copying any numbers:
        - remove textual fallback nodes (.conum without data-value)
        - empty real markers (.conum[data-value]) so they add no textContent
        - strip literal ' (n)' or '<n>' at EOL inside listings
        """
        soup = BeautifulSoup(html, "html.parser")

        for pre in soup.select("div.listingblock pre"):
            for node in pre.select(".conum:not([data-value])"):
                node.decompose()
            for node in pre.select(".conum[data-value]"):
                node.clear()
                node["aria-hidden"] = "true"

            raw = pre.decode_contents()
            cleaned = re.sub(r"[ \t]*(\(\d+\)|<\d+>)[ \t]*(?=\n|$)", "", raw, flags=re.M)
            if cleaned != raw:
                pre.clear()
                pre.append(BeautifulSoup(cleaned, "html.parser"))

        return str(soup)

    def _extract_meta_from_html(self, html: str) -> dict:
        soup = BeautifulSoup(html, "html.parser")
        meta: dict = {}
        title_el = soup.find("h1", class_="sect0") or soup.find("h1") or soup.find("title")
        if title_el:
            meta["title"] = title_el.get_text(" ", strip=True)
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            meta["description"] = desc["content"]
        return meta

    # ---------- Helpers ----------

    def _sha1_file(self, path: pathlib.Path) -> str:
        h = hashlib.sha1()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def _escape(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    _nonword = re.compile(r"[^0-9A-Za-z _-]+")
    _spaces = re.compile(r"[ _]+")

    def _slugify(self, text: str) -> str:
        t = text.strip().lower()
        t = self._nonword.sub("", t)
        t = self._spaces.sub("-", t)
        return t
