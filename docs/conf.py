"""Sphinx configuration for the UK WSR Visualizer documentation."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

project = "UK WSR Visualizer"
author = "UK WSR Visualizer developers"
copyright = "2026, UK WSR Visualizer developers"

try:
    release = package_version("uk-wsr-visualizer")
except PackageNotFoundError:
    release = "0.1.0"

version = ".".join(release.split(".")[:2])

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
    "sphinx_design",
]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "fieldlist",
]

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
templates_path = ["_templates"]

nitpicky = False
autosummary_generate = True
autodoc_typehints = "description"
autodoc_member_order = "bysource"

html_theme = "pydata_sphinx_theme"
html_title = "UK WSR Visualizer"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "github_url": "https://github.com/rrniii/uk-wsr-visualizer",
    "show_toc_level": 2,
    "navbar_align": "left",
    "navigation_with_keys": True,
}
