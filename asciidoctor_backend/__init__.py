# asciidoctor_backend/__init__.py
import os
import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup, NavigableString
from importlib import resources
from mkdocs.config import config_options
from mkdocs.config.defaults import MkDocsConfig
from mkdocs.plugins import BasePlugin
from mkdocs.structure.files import File, Files
from mkdocs.structure.pages import Page
from mkdocs.structure.toc import AnchorLink
from mkdocs.structure.toc import TableOfContents as Toc  # MkDocs 1.6+


# ---------- Data types ----------

@dataclass
class Rendered:
    html: str
    toc: Toc
    meta: dict


# ---------- Plugin ----------

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
        ("max_workers", config_options.Type(int, default=8)),
        ("ignore_missing", config_options.Type(bool, default=False)),
        # Edit-includes feature
        ("edit_includes", config_options.Type(bool, default=False)),
        ("edit_base_url", config_options.Type(str, default="")),
        ("repo_root", config_options.Type(str, default=None)),
    )

    # Caches
    _cache: Dict[str, Tuple[float, Rendered]]  # (mtime, Rendered)
    _memo: Dict[str, Rendered]                 # per-build memo of Rendered
    _adoc_pages: Dict[str, pathlib.Path]       # src_uri -> absolute path

    # ---------- MkDocs lifecycle ----------

    def on_config(self, config: MkDocsConfig):
        # Runtime state
        self._cache = {}
        self._memo = {}
        self._adoc_pages = {}
        self._use_dir_urls = bool(config.use_directory_urls)

        # Project paths
        self._project_dir = pathlib.Path(config.config_file_path).parent.resolve()
        self._docs_dir = pathlib.Path(config.docs_dir).resolve()

        # Asciidoctor command + options
        self._cmd = self.config["asciidoctor_cmd"]
        self._safe = self.config["safe_mode"]
        self._attrs = self.config["attributes"] or {}
        self._reqs = self.config["requires"] or []
        self._fail = self.config["fail_on_error"]
        self._trace = self.config["trace"]
        self._max_workers = self.config["max_workers"]
        self._ignore_missing = self.config["ignore_missing"]

        # Asciidoctor base dir
        base_dir_opt = self.config.get("base_dir")
        self._base_dir = (self._project_dir / base_dir_opt).resolve() if base_dir_opt else self._docs_dir

        # BeautifulSoup parser (keep it simple; no lxml)
        self._bs_parser = "html.parser"

        # Packaged assets
        assets = resources.files(__package__) / "assets"
        self._pkg_css_res = assets / "asciidoc.css"
        self._pkg_js_res = assets / "strip_callouts.js"
        self._pkg_css_href = "assets/asciidoc.css"
        self._pkg_js_href = "assets/strip_callouts.js"

        # Ruby helper for include-edit markers
        self._ruby_inc_helper_res = assets / "include_edit.rb"

        # Edit-includes wiring (prefer repo_url + edit_uri)
        self._edit_includes = bool(self.config.get("edit_includes", False))
        self._edit_base_url = ""
        self._repo_root = self._project_dir  # default; auto-detect git root below

        if self._edit_includes:
            base = (getattr(config, "repo_url", "") or "").rstrip("/")
            edit_uri = (getattr(config, "edit_uri", "") or "").lstrip("/")
            override = (self.config.get("edit_base_url") or "").strip()

            if base and edit_uri:
                self._edit_base_url = f"{base}/{edit_uri}".rstrip("/") + "/"
            elif override:
                self._edit_base_url = override.rstrip("/") + "/"

            repo_root_opt = self.config.get("repo_root")
            self._repo_root = (
                pathlib.Path(repo_root_opt).resolve()
                if repo_root_opt
                else self._discover_git_root(self._project_dir) or self._project_dir
            )

            if self._edit_base_url:
                self._attrs["edit-base"] = self._edit_base_url
                self._attrs["repo-root"] = str(self._repo_root)
            else:
                # No valid base: disable feature silently
                self._edit_includes = False

        # Ensure our CSS/JS are included
        config.extra_css.append(self._pkg_css_href)
        config.extra_javascript.append(self._pkg_js_href)
        return config

    def on_files(self, files: Files, config: MkDocsConfig) -> Files:
        """Register .adoc pages and prune broken files if requested."""
        src_dir = pathlib.Path(config.docs_dir).resolve()
        site_dir = pathlib.Path(config.site_dir)

        # Remove .adoc files that MkDocs may have detected as static
        for f in list(files):
            if f.src_path.endswith(".adoc"):
                files.remove(f)

        # Optionally remove missing files that belong to docs_dir
        if self._ignore_missing:
            for f in list(files):
                try:
                    base = pathlib.Path(f.src_dir).resolve()
                except Exception:
                    continue
                if base != src_dir:
                    continue
                abs_src = (
                    pathlib.Path(getattr(f, "abs_src_path", "")) if getattr(f, "abs_src_path", None) else (base / f.src_path)
                )
                try:
                    if (not abs_src.exists()) or abs_src.is_dir():
                        files.remove(f)
                except OSError:
                    files.remove(f)

        # Add .adoc as documentation pages (exclude partials)
        for p in src_dir.rglob("*.adoc"):
            if not self._is_valid_adoc_path(p):
                continue
            rel = p.relative_to(src_dir).as_posix()
            if rel.startswith(("partials/", "snippets/", "modules/")):
                continue

            f = File(rel, src_dir=str(src_dir), dest_dir=config.site_dir, use_directory_urls=config.use_directory_urls)
            f.is_documentation_page = (lambda f=f: True)  # MkDocs 1.6

            self._adoc_pages[rel] = p

            # Compute dest_path + url (mirror Markdown behavior)
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

            f.dest_path = dest_path
            f.abs_dest_path = str(site_dir / dest_path)
            f.url = url
            files.append(f)

        return files

    def on_nav(self, nav, config: MkDocsConfig, files: Files):
        """Render (or re-render) needed .adoc sources upfront (cache-aware)."""
        self._memo = {}
        to_build: List[pathlib.Path] = []

        for rel, p in list(self._adoc_pages.items()):
            if not self._is_valid_adoc_path(p):
                del self._adoc_pages[rel]
                continue
            key = str(p)
            mtime = self._safe_mtime(p)
            if mtime is None:
                del self._adoc_pages[rel]
                continue
            cached = self._cache.get(key)
            if not (cached and cached[0] == mtime):
                to_build.append(p)

        if not to_build:
            return

        workers = max(1, min(self._max_workers, (os.cpu_count() or 2)))
        if workers == 1:
            for p in to_build:
                src, rendered = self._render_fresh(p)
                mt = self._safe_mtime(src)
                if mt is not None:
                    self._cache[str(src)] = (mt, rendered)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(self._render_fresh, p): p for p in to_build}
                for fut in as_completed(futs):
                    src, rendered = fut.result()
                    mt = self._safe_mtime(src)
                    if mt is not None:
                        self._cache[str(src)] = (mt, rendered)

    def on_post_build(self, config: MkDocsConfig):
        """Write packaged CSS/JS into site/ so extra_css/extra_javascript resolve."""
        site_dir = pathlib.Path(config.site_dir)
        for res, href in ((self._pkg_css_res, self._pkg_css_href), (self._pkg_js_res, self._pkg_js_href)):
            out = site_dir / href
            out.parent.mkdir(parents=True, exist_ok=True)
            with resources.as_file(res) as src_path:
                out.write_bytes(pathlib.Path(src_path).read_bytes())

    # ---------- Page hooks ----------

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
        page.toc = rendered.toc
        return rendered.html

    # ---------- Render helpers ----------

    def _render_adoc_cached(self, src_path: pathlib.Path) -> Rendered:
        key = str(src_path)

        memo_hit = self._memo.get(key)
        if memo_hit:
            return memo_hit

        mtime = self._safe_mtime(src_path)
        if mtime is None:
            msg = f"AsciiDoc source missing or broken symlink: {src_path}"
            if self._fail and not self._ignore_missing:
                raise SystemExit(msg)
            return Rendered(html=f"<pre>{self._escape(msg)}</pre>", toc=Toc([]), meta={})

        cached = self._cache.get(key)
        if cached and cached[0] == mtime:
            rendered = cached[1]
            self._memo[key] = rendered
            return rendered

        src, rendered = self._render_fresh(src_path)
        mt = self._safe_mtime(src)
        if mt is not None:
            self._cache[str(src)] = (mt, rendered)
        self._memo[key] = rendered
        return rendered

    def _render_fresh(self, src: pathlib.Path) -> Tuple[pathlib.Path, Rendered]:
        html = self._run_asciidoctor(src)
        html, toc, meta = self._postprocess_once(html)
        return src, Rendered(html=html, toc=toc, meta=meta)

    def _run_asciidoctor(self, src: pathlib.Path) -> str:
        args = [self._cmd, "-b", "html5", "-s", "-o", "-", str(src)]
        args[1:1] = ["-S", self._safe]
        args.extend(["-B", str(self._base_dir)])
        for r in self._reqs:
            args.extend(["-r", r])
        for k, v in (self._attrs or {}).items():
            args.extend(["-a", f"{k}={v}"])
        if self._trace:
            args.append("--trace")

        if self._ignore_missing:
            args.extend(["--failure-level", "FATAL"])

        # Enable include-edit helper when configured
        if self._edit_includes and self._edit_base_url:
            args.extend(["-a", "sourcemap"])
            try:
                with resources.as_file(self._ruby_inc_helper_res) as helper_path:
                    args.extend(["-r", str(helper_path)])
            except FileNotFoundError:
                pass  # helper missing; continue without markers

        try:
            proc = subprocess.run(args, check=True, capture_output=True)
            return proc.stdout.decode("utf-8", errors="ignore")
        except FileNotFoundError:
            msg = f"Asciidoctor not found: '{self._cmd}'. Install with: gem install asciidoctor"
            if self._fail and not self._ignore_missing:
                raise SystemExit(msg)
            return f"<pre>{self._escape(msg)}</pre>"
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="ignore")
            if self._ignore_missing or not self._fail:
                if any(s in stderr.lower() for s in ("no such file or directory", "include file not found", "enoent", "cannot open")):
                    return (
                        f"<pre>{self._escape(f'Asciidoctor warning for {src} (missing content ignored):')}\n"
                        f"{self._escape(stderr)}</pre>"
                    )
            raise SystemExit(f"Asciidoctor failed for {src}:\n{stderr}")

    # ---------- HTML post-processing ----------

    def _postprocess_once(self, html: str) -> Tuple[str, Toc, dict]:
        soup = BeautifulSoup(html, self._bs_parser)

        # Meta
        meta: dict = {}
        title_el = soup.find("h1", class_="sect0") or soup.find("h1") or soup.find("title")
        if title_el:
            meta["title"] = title_el.get_text(" ", strip=True)
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            meta["description"] = desc["content"]

        # IDs + ToC
        headings = [h for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]) if not (h.name == "h1" and "sect0" in (h.get("class") or []))]
        for h in headings:
            if not h.get("id"):
                h["id"] = self._slugify(h.get_text(" ", strip=True))
        toc = self._toc_from_headings(headings)

        # Admonitions -> Material style
        kinds = {"note", "tip", "important", "caution", "warning"}
        alias = {"caution": "warning", "important": "danger"}  # color intent

        for blk in soup.select("div.admonitionblock"):
            classes = set(blk.get("class", []))
            kind = next((k for k in kinds if k in classes), "note")
            material_kind = alias.get(kind, kind)

            content = blk.select_one(".content") or blk
            title_el2 = content.select_one(".title")
            title_text = title_el2.get_text(" ", strip=True) if title_el2 else kind.capitalize()
            if title_el2:
                title_el2.extract()

            new = soup.new_tag("div")
            new["class"] = ["admonition", material_kind]

            title_p = soup.new_tag("p")
            title_p["class"] = ["admonition-title"]
            title_p.string = title_text
            new.append(title_p)

            for child in list(content.children):
                new.append(child.extract())
            blk.replace_with(new)

        # Callout table -> ordered list
        for colist in soup.select("div.colist"):
            table = colist.find("table")
            if not table:
                continue
            rows = table.find_all("tr") or []
            if not rows:
                continue
            ol = soup.new_tag("ol", **{"class": "colist"})
            for tr in rows:
                tds = tr.find_all("td")
                if len(tds) < 2:
                    continue
                li = soup.new_tag("li")
                li.append(BeautifulSoup(tds[1].decode_contents(), self._bs_parser))
                ol.append(li)
            table.replace_with(ol)

        # Callouts in code listings
        _WS_ONLY = re.compile(r"^[\s\u00A0]+$")  # incl. NBSP
        _CALLOUT_TXT = re.compile(r"^\s*(\(\d+\)|<\d+>|&lt;\d+&gt;)\s*$")

        for pre in soup.select("div.listingblock pre"):
            # Normalize the bubble nodes
            for node in pre.select(".conum"):
                val = node.get("data-value")
                if not val:
                    txt = node.get_text("", strip=True)
                    m = re.search(r"(\d+)", txt or "")
                    if m:
                        val = m.group(1)
                node.clear()
                if val:
                    node["data-value"] = val
                node["aria-hidden"] = "true"

            # Remove textual fallback after the bubble
            for node in pre.select(".conum"):
                sib = node.next_sibling
                while isinstance(sib, NavigableString) and _WS_ONLY.match(str(sib) or ""):
                    nxt = sib.next_sibling
                    sib.extract()
                    sib = nxt
                if sib is None:
                    continue
                if isinstance(sib, NavigableString):
                    if _CALLOUT_TXT.match(str(sib)):
                        sib.extract()
                    else:
                        new_text = _CALLOUT_TXT.sub("", str(sib), count=1)
                        if new_text != str(sib):
                            sib.replace_with(new_text)
                    continue
                if getattr(sib, "name", None) in {"span", "em", "i", "b", "code", "strong", "small"}:
                    txt = sib.get_text("", strip=False)
                    if _CALLOUT_TXT.match(txt):
                        sib.extract()
                        continue
                    txt2 = "".join(ch if isinstance(ch, str) else ch.get_text("", strip=False) for ch in sib.contents)
                    if _CALLOUT_TXT.match(txt2):
                        sib.extract()

        # Tables: wrap block and move title to <caption>
        for tbl in soup.select("table.tableblock"):
            block = tbl.find_parent("div", class_="tableblock")
            title = block.find("div", class_="title") if block else None

            if title and not tbl.find("caption"):
                cap = soup.new_tag("caption")
                cap.string = title.get_text(" ", strip=True)
                tbl.insert(0, cap)
                title.decompose()

            wrapper = soup.new_tag("div", **{"class": "md-typeset__table"})
            if block:
                tbl.extract()
                wrapper.append(tbl)
                block.replace_with(wrapper)
            else:
                tbl.replace_with(wrapper)
                wrapper.append(tbl)

        # Figures -> <figure> + top figcaption
        for ib in soup.select("div.imageblock"):
            title_el = ib.find("div", class_="title")
            content_el = ib.find("div", class_="content")
            if not content_el:
                continue

            fig = soup.new_tag("figure")
            for cls in (ib.get("class") or []):
                if cls != "imageblock":
                    fig["class"] = (fig.get("class") or []) + [cls]
            fig["class"] = (fig.get("class") or []) + ["adoc-figure"]

            for child in list(content_el.children):
                fig.append(child.extract())

            if title_el:
                cap = soup.new_tag("figcaption")
                cap.string = title_el.get_text(" ", strip=True)
                fig.insert(0, cap)
                title_el.decompose()

            content_el.decompose()
            ib.replace_with(fig)

        # Fix xref URLs to match MkDocs routing
        def _to_dir_url(href: str) -> str:
            if not href or href.startswith(("#", "http://", "https://", "mailto:", "tel:")):
                return href
            if not self._use_dir_urls:
                # replace ".../name.adoc" -> ".../name.html"
                return re.sub(r"(^|/)([^/#?]+)\.adoc(?=($|[#?]))", r"\1\2.html", href)
            # dir-urls
            path, frag = (href.split("#", 1) + [""])[:2]
            path_q, query = (path.split("?", 1) + [""])[:2]
            path_only = path_q
            if path_only.endswith("/index.html"):
                path_only = path_only[:-len("index.html")]
            elif path_only.endswith(".html"):
                path_only = path_only[:-len(".html")] + "/"
            elif path_only.endswith(".adoc"):
                path_only = path_only[:-len(".adoc")] + "/"
            new = path_only
            if query:
                new += "?" + query
            if frag:
                new += "#" + frag
            return new

        for a in soup.find_all("a", href=True):
            a["href"] = _to_dir_url(a["href"])

        # Move include-edit markers into headings and render edit icon
        if getattr(self, "_edit_includes", False) and self._edit_base_url:
            markers = list(soup.select("span.adoc-include-edit[data-edit]"))
            seen: set = set()  # (id(heading), href)

            for marker in markers:
                href = marker.get("data-edit")
                if not href:
                    marker.decompose()
                    continue

                sect = marker.find_parent(
                    lambda t: hasattr(t, "get") and "class" in t.attrs and any(str(c).startswith("sect") for c in t["class"])
                )

                h = None
                if sect:
                    h = sect.find(re.compile(r"^h[1-6]$"), recursive=False)
                    if h is None:
                        for child in sect.children:
                            if getattr(child, "name", "") in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                                h = child
                                break
                if h is None:
                    for prev in marker.previous_elements:
                        if getattr(prev, "name", "") in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                            h = prev
                            break
                if h is None:
                    marker.decompose()
                    continue

                key = (id(h), href)
                if key in seen or h.select_one(f'a.adoc-edit-include[href="{href}"]'):
                    marker.decompose()
                    continue
                seen.add(key)

                if "class" in h.attrs:
                    if "adoc-flex" not in h["class"]:
                        h["class"].append("adoc-flex")
                else:
                    h["class"] = ["adoc-flex"]

                a = soup.new_tag(
                    "a",
                    href=href,
                    **{
                        "class": "md-content__button md-icon adoc-edit-include",
                        "title": "Edit included file",
                        "target": "_blank",
                        "rel": "noopener",
                    },
                )
                svg = BeautifulSoup(
                    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
                    '<path d="M10 20H6V4h7v5h5v3.1l2-2V8l-6-6H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h4zm10.2-7c.1 0 .3.1.4.2l1.3 1.3c.2.2.2.6 0 .8l-1 1-2.1-2.1 1-1c.1-.1.2-.2.4-.2m0 3.9L14.1 23H12v-2.1l6.1-6.1z"></path>'
                    "</svg>",
                    self._bs_parser,
                )
                a.append(svg)
                h.append(a)
                marker.decompose()

        return str(soup), toc, meta

    def _toc_from_headings(self, headings: List) -> Toc:
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

    # ---------- Utilities ----------

    def _discover_git_root(self, start: pathlib.Path) -> Optional[pathlib.Path]:
        """Walk upward from `start` to find a directory containing .git. Return the path or None."""
        p = start
        try:
            for candidate in [p, *p.parents]:
                if (candidate / ".git").exists():
                    return candidate.resolve()
        except Exception:
            pass
        return None

    def _is_valid_adoc_path(self, p: pathlib.Path) -> bool:
        try:
            if not p.exists():
                return False
            if p.is_dir():
                return False
            return True
        except OSError:
            return False

    def _safe_mtime(self, p: pathlib.Path) -> Optional[float]:
        try:
            return p.stat().st_mtime
        except (FileNotFoundError, OSError):
            return None

    def _escape(self, s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    _nonword = re.compile(r"[^0-9A-Za-z _-]+")
    _spaces = re.compile(r"[ _]+")

    def _slugify(self, text: str) -> str:
        t = text.strip().lower()
        t = self._nonword.sub("", t)
        t = self._spaces.sub("-", t)
        return t
