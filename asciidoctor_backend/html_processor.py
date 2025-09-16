# asciidoctor_backend/html_processor.py

"""
HTML processing module

Handles post-processing of HTML output from Asciidoctor:
- Metadata extraction from HTML
- Table of contents generation
- Admonition transformation to Material Design style
- Callout list processing
- Code block callout cleanup
- Table and figure transformations
- Cross-reference URL fixing
- Edit include marker processing
"""

import re
from typing import List, Tuple

from bs4 import BeautifulSoup, NavigableString
from mkdocs.structure.toc import AnchorLink, TableOfContents as Toc

from .utils import slugify


class HtmlProcessor:
    def __init__(self, bs_parser: str = "html.parser", use_dir_urls: bool = True,
                 edit_includes: bool = False, edit_base_url: str = ""):
        self.bs_parser = bs_parser
        self.use_dir_urls = use_dir_urls
        self.edit_includes = edit_includes
        self.edit_base_url = edit_base_url

    def postprocess_html(self, html: str) -> Tuple[str, Toc, dict]:
        """Process HTML and return processed HTML, table of contents, and metadata."""
        soup = BeautifulSoup(html, self.bs_parser)

        # Extract metadata
        meta = self._extract_meta(soup)

        # Process headings and create ToC
        headings = self._process_headings(soup)
        toc = self._toc_from_headings(headings)

        # Transform various elements
        self._transform_admonitions(soup)
        self._transform_callout_lists(soup)
        self._clean_callouts_in_code(soup)
        self._transform_tables(soup)
        self._transform_figures(soup)
        self._fix_xref_urls(soup)

        if self.edit_includes and self.edit_base_url:
            self._process_include_edit_markers(soup)

        return str(soup), toc, meta

    def _extract_meta(self, soup: BeautifulSoup) -> dict:
        """Extract metadata from HTML."""
        meta = {}

        # Extract title
        title_el = soup.find("h1", class_="sect0") or soup.find("h1") or soup.find("title")
        if title_el:
            meta["title"] = title_el.get_text(" ", strip=True)

        # Extract description
        desc = soup.find("meta", attrs={"name": "description"})
        if desc and desc.get("content"):
            meta["description"] = desc["content"]

        return meta

    def _process_headings(self, soup: BeautifulSoup) -> List:
        """Process headings and ensure they have IDs."""
        headings = [
            h for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
            if not (h.name == "h1" and "sect0" in (h.get("class") or []))
        ]

        for h in headings:
            if not h.get("id"):
                h["id"] = slugify(h.get_text(" ", strip=True))

        return headings

    def _toc_from_headings(self, headings: List) -> Toc:
        """Generate table of contents from headings."""
        def make_anchor(title: str, hid: str) -> AnchorLink:
            return AnchorLink(title, hid, [])

        items = []
        stack = []

        for h in headings:
            level = int(h.name[1])
            node = make_anchor(h.get_text(" ", strip=True), h["id"])

            while stack and stack[-1][0] >= level:
                stack.pop()

            (items if not stack else stack[-1][1].children).append(node)
            stack.append((level, node))

        return Toc(items)

    def _transform_admonitions(self, soup: BeautifulSoup):
        """Transform Asciidoctor admonitions to Material style."""
        kinds = {"note", "tip", "important", "caution", "warning"}
        alias = {"caution": "warning", "important": "danger"}

        for blk in soup.select("div.admonitionblock"):
            classes = set(blk.get("class", []))
            kind = next((k for k in kinds if k in classes), "note")
            material_kind = alias.get(kind, kind)

            content = blk.select_one(".content") or blk
            title_el = content.select_one(".title")
            title_text = title_el.get_text(" ", strip=True) if title_el else kind.capitalize()
            if title_el:
                title_el.extract()

            new = soup.new_tag("div")
            new["class"] = ["admonition", material_kind]

            title_p = soup.new_tag("p")
            title_p["class"] = ["admonition-title"]
            title_p.string = title_text
            new.append(title_p)

            for child in list(content.children):
                new.append(child.extract())
            blk.replace_with(new)

    def _transform_callout_lists(self, soup: BeautifulSoup):
        """Transform callout tables to ordered lists."""
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
                li.append(BeautifulSoup(tds[1].decode_contents(), self.bs_parser))
                ol.append(li)
            table.replace_with(ol)

    def _clean_callouts_in_code(self, soup: BeautifulSoup):
        """Clean up callouts in code listings."""
        _WS_ONLY = re.compile(r"^[\s\u00A0]+$")
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

    def _transform_tables(self, soup: BeautifulSoup):
        """Transform tables: wrap and move title to caption."""
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

    def _transform_figures(self, soup: BeautifulSoup):
        """Transform image blocks to HTML5 figures."""
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

    def _fix_xref_urls(self, soup: BeautifulSoup):
        """Fix cross-reference URLs to match MkDocs routing."""
        def _to_dir_url(href: str) -> str:
            if not href or href.startswith(("#", "http://", "https://", "mailto:", "tel:")):
                return href
            if not self.use_dir_urls:
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

    def _process_include_edit_markers(self, soup: BeautifulSoup):
        """Move include-edit markers into headings and render edit icon."""
        markers = list(soup.select("span.adoc-include-edit[data-edit]"))
        seen = set()

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
                self.bs_parser,
            )
            a.append(svg)
            h.append(a)
            marker.decompose()
