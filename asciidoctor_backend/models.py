# asciidoctor_backend/models.py

"""
Data models module

Defines data structures used throughout the AsciiDoctor plugin.
Contains model classes for rendered content, metadata, and other
shared data types.
"""

from dataclasses import dataclass
from mkdocs.structure.toc import TableOfContents as Toc


@dataclass
class Rendered:
    html: str
    toc: Toc
    meta: dict
