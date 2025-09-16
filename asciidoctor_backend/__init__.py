# asciidoctor_backend/__init__.py

"""
MkDocs AsciiDoctor backend plugin

A plugin that adds AsciiDoc support to MkDocs by rendering .adoc files
through Asciidoctor and integrating them seamlessly with MkDocs themes.

Features:
- Renders .adoc files via Asciidoctor
- Converts AsciiDoc content to MkDocs-compatible HTML
- Generates table of contents from headings
- Transforms admonitions to Material Design style
- Supports edit-includes functionality
- Processes callouts, tables, and figures
"""

# Import the main plugin class and data models
from .plugin import AsciiDoctorPlugin
from .models import Rendered

# Make these available at package level
__all__ = ["AsciiDoctorPlugin", "Rendered"]
