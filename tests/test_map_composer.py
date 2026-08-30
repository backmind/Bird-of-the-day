"""Tests for map_composer — server-side map composition for RSS feeds."""

from unittest.mock import MagicMock, patch

from PIL import Image

from scripts.http_client import NoImageAvailable
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
        alphas = list(result.split()[-1].get_flattened_data())
        assert all(a == 0 for a in alphas)

    def test_modifies_pixels(self):
        img = _make_rgba(color=(100, 150, 200, 255))
        result = _apply_filters(img)
        # Filters should change at least some pixel values.
        assert list(img.get_flattened_data()) != list(result.get_flattened_data())


class TestComposeMap:
    def test_success(self, tmp_path):
        basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        density = _make_rgba(size=(8, 8), color=(255, 100, 0, 128))

        out = tmp_path / "maps" / "test.png"

        with patch("scripts.map_composer.download_image", return_value=density):
            ok = compose_map("http://fake/density.png", out, basemap_image=basemap)

        assert ok is True
        assert out.exists()
        composed = Image.open(out)
        assert composed.size == (8, 8)

    def test_density_download_fails(self, tmp_path):
        basemap = _make_rgba()
        out = tmp_path / "fail.png"

        with patch("scripts.map_composer.download_image", return_value=None):
            ok = compose_map("http://fake/density.png", out, basemap_image=basemap)

        assert ok is False
        assert not out.exists()

    def test_no_basemap_loads_local_asset(self, tmp_path):
        fake_basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        fake_density = _make_rgba(size=(8, 8), color=(255, 0, 0, 128))
        out = tmp_path / "test.png"

        with patch("scripts.map_composer.download_image", return_value=fake_density):
            with patch("scripts.map_composer.load_basemap", return_value=fake_basemap):
                ok = compose_map("http://fake/density.png", out)

        assert ok is True

    def test_missing_local_asset_fails_gracefully(self, tmp_path):
        out = tmp_path / "test.png"
        with patch("scripts.map_composer.load_basemap", return_value=None):
            ok = compose_map("http://fake/density.png", out)
        assert ok is False
        assert not out.exists()

    def test_real_committed_asset_loads(self):
        from scripts.map_composer import load_basemap
        img = load_basemap()
        assert img is not None
        assert img.mode == "RGBA"
        assert img.size[0] == img.size[1]  # square world tile

    def test_resizes_density_to_match_basemap(self, tmp_path):
        basemap = _make_rgba(size=(8, 8), color=(200, 200, 200, 255))
        density = _make_rgba(size=(4, 4), color=(255, 0, 0, 128))
        out = tmp_path / "test.png"

        with patch("scripts.map_composer.download_image", return_value=density):
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

            with patch("scripts.map_composer.download_image", return_value=fake_img):
                with patch(
                    "scripts.map_composer.load_basemap",
                    return_value=_make_rgba(size=(8, 8)),
                ):
                    result = ensure_composed_maps(
                        entries, str(cache_dir), maps_dir
                    )

        assert "bird1" in result
        assert result["bird1"] == "maps/bird1.png"
        assert (maps_dir / "bird1.png").exists()


class TestGbifHasNothingToDraw:
    """GBIF contesta 204 para un taxón sin ocurrencias que dibujar.

    Es una respuesta definitiva, no una avería, y hay que anotarla: este
    bucle reintenta cada run todo lo que no tenga PNG compuesto, así que
    sin anotarla vuelve a preguntar todos los días para siempre. Le pasó
    a Pampusana salamonis durante setenta días.
    """

    def _content(self, url="http://gbif/map.png"):
        content = MagicMock()
        content.distribution_map_url = url
        return content

    def test_the_map_url_is_dropped_and_the_cache_saved(self, tmp_path):
        entries = [{"speciesCode": "bird1"}]
        content = self._content()
        with patch("scripts.map_composer.content_scraper") as mock_cs:
            mock_cs.load_cached_content.return_value = content
            with patch("scripts.map_composer.download_image",
                       side_effect=NoImageAvailable("http://gbif/map.png")):
                with patch("scripts.map_composer.load_basemap",
                           return_value=_make_rgba(size=(8, 8))):
                    result = ensure_composed_maps(
                        entries, str(tmp_path / "cache"), tmp_path / "maps"
                    )
        assert result == {}
        assert content.distribution_map_url == ""
        mock_cs.save_cached_content.assert_called_once()
        assert mock_cs.save_cached_content.call_args.args[0] == "bird1"

    def test_a_transient_failure_leaves_the_url_alone(self, tmp_path):
        """Solo el 204 es definitivo: una caída de red se reintenta."""
        entries = [{"speciesCode": "bird1"}]
        content = self._content()
        with patch("scripts.map_composer.content_scraper") as mock_cs:
            mock_cs.load_cached_content.return_value = content
            with patch("scripts.map_composer.download_image", return_value=None):
                with patch("scripts.map_composer.load_basemap",
                           return_value=_make_rgba(size=(8, 8))):
                    result = ensure_composed_maps(
                        entries, str(tmp_path / "cache"), tmp_path / "maps"
                    )
        assert result == {}
        assert content.distribution_map_url == "http://gbif/map.png"
        mock_cs.save_cached_content.assert_not_called()
