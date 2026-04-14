"""Tests for map_composer — server-side map composition for RSS feeds."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

from scripts.map_composer import _apply_filters, compose_map, ensure_composed_maps


def _make_rgba(size=(4, 4), color=(128, 128, 128, 255)):
    """Create a tiny RGBA image for testing."""
    return Image.new("RGBA", size, color)


class TestApplyFilters:
    def test_returns_same_size(self):
        img = _make_rgba()
        result = _apply_filters(img)
        assert result.size == img.size

    def test_returns_rgba(self):
        img = _make_rgba()
        result = _apply_filters(img)
        assert result.mode == "RGBA"

    def test_preserves_alpha(self):
        img = _make_rgba(color=(128, 128, 128, 0))
        result = _apply_filters(img)
        # Fully transparent pixels stay transparent.
        alphas = list(result.split()[-1].getdata())
        assert all(a == 0 for a in alphas)

    def test_modifies_pixels(self):
        img = _make_rgba(color=(100, 150, 200, 255))
        result = _apply_filters(img)
        # Filters should change at least some pixel values.
        assert list(img.getdata()) != list(result.getdata())


class TestComposeMap:
    def test_success(self, tmp_path):
        basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        density = _make_rgba(size=(8, 8), color=(255, 100, 0, 128))

        out = tmp_path / "maps" / "test.png"

        with patch("scripts.map_composer._download_image", return_value=density):
            ok = compose_map("http://fake/density.png", out, basemap_image=basemap)

        assert ok is True
        assert out.exists()
        composed = Image.open(out)
        assert composed.size == (8, 8)

    def test_density_download_fails(self, tmp_path):
        basemap = _make_rgba()
        out = tmp_path / "fail.png"

        with patch("scripts.map_composer._download_image", return_value=None):
            ok = compose_map("http://fake/density.png", out, basemap_image=basemap)

        assert ok is False
        assert not out.exists()

    def test_no_basemap_downloads_it(self, tmp_path):
        fake_basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        fake_density = _make_rgba(size=(8, 8), color=(255, 0, 0, 128))
        out = tmp_path / "test.png"

        def side_effect(url, session=None):
            if "basemap" in url or "carto" in url:
                return fake_basemap
            return fake_density

        with patch("scripts.map_composer._download_image", side_effect=side_effect):
            with patch("scripts.map_composer.BASEMAP_URL", "http://carto/basemap.png"):
                ok = compose_map("http://fake/density.png", out)

        assert ok is True

    def test_resizes_density_to_match_basemap(self, tmp_path):
        basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        density = _make_rgba(size=(4, 4), color=(255, 0, 0, 128))
        out = tmp_path / "test.png"

        with patch("scripts.map_composer._download_image", return_value=density):
            ok = compose_map("http://fake/density.png", out, basemap_image=basemap)

        assert ok is True
        composed = Image.open(out)
        assert composed.size == (8, 8)


class TestEnsureComposedMaps:
    def test_skips_existing(self, tmp_path):
        maps_dir = tmp_path / "maps"
        maps_dir.mkdir()
        (maps_dir / "abc.png").write_bytes(b"fake")

        entries = [{"speciesCode": "abc"}]
        result = ensure_composed_maps(entries, str(tmp_path / "cache"), maps_dir)
        assert result == {"abc": "maps/abc.png"}

    def test_skips_no_distribution_url(self, tmp_path):
        maps_dir = tmp_path / "maps"
        cache_dir = tmp_path / "cache"

        entries = [{"speciesCode": "xyz"}]
        with patch("scripts.map_composer.content_scraper") as mock_cs:
            mock_content = MagicMock()
            mock_content.distribution_map_url = ""
            mock_cs.load_cached_content.return_value = mock_content
            result = ensure_composed_maps(entries, str(cache_dir), maps_dir)

        assert result == {}

    def test_composes_new_map(self, tmp_path):
        maps_dir = tmp_path / "maps"
        cache_dir = tmp_path / "cache"

        entries = [{"speciesCode": "bird1"}]
        fake_img = _make_rgba(size=(8, 8))

        with patch("scripts.map_composer.content_scraper") as mock_cs:
            mock_content = MagicMock()
            mock_content.distribution_map_url = "http://gbif/map.png"
            mock_cs.load_cached_content.return_value = mock_content

            with patch("scripts.map_composer._download_image", return_value=fake_img):
                result = ensure_composed_maps(
                    entries, str(cache_dir), maps_dir
                )

        assert "bird1" in result
        assert result["bird1"] == "maps/bird1.png"
        assert (maps_dir / "bird1.png").exists()
