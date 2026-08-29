"""With one page per month and one per species, inlining a 1000-line
stylesheet in every page would add megabytes to the tree and rewrite all
of it on any style change."""

from pathlib import Path

from scripts import archive_builder, site_builder, site_css
from scripts.i18n import Catalog


def test_css_constant_moved_out_of_site_builder():
    assert not hasattr(site_builder, "_CSS")
    assert ":root {" in site_css.CSS
    assert ".plate" in site_css.CSS


def test_pages_link_the_stylesheet_instead_of_inlining_it():
    ctx = site_builder.RenderContext(catalog=Catalog.load("en"), feed_link="")
    html = site_builder.build_index([], ctx)
    assert '<link rel="stylesheet" href="assets/site.css">' in html
    assert "--paper:" not in html


def test_write_site_publishes_the_stylesheet(tmp_path):
    archive_builder.write_site([], tmp_path, Catalog.load("en"))
    published = Path(tmp_path) / "assets" / "site.css"
    assert published.read_text(encoding="utf-8") == site_css.CSS
