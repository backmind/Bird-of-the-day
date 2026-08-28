"""Tests for http_client, the shared session and download helpers."""

from io import BytesIO
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

from scripts.http_client import build_session, download_image


def _png_bytes(size=(4, 4), color=(10, 20, 30, 255)) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


class TestBuildSession:
    def test_mounts_retry_adapter(self):
        s = build_session(total_retries=4, backoff_factor=2.0)
        adapter = s.get_adapter("https://example.org")
        retry = adapter.max_retries
        assert retry.total == 4
        assert retry.backoff_factor == 2.0
        assert 503 in retry.status_forcelist
        assert 429 in retry.status_forcelist
        assert retry.respect_retry_after_header is True

    def test_get_only_methods(self):
        s = build_session()
        retry = s.get_adapter("https://example.org").max_retries
        assert "GET" in retry.allowed_methods
        assert "POST" not in retry.allowed_methods

    def test_accept_language_header(self):
        s = build_session(accept_language="es-ES,es;q=0.9")
        assert s.headers["Accept-Language"] == "es-ES,es;q=0.9"


class TestDownloadImage:
    def _resp(self, content: bytes, status: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status
        resp.content = content
        resp.raise_for_status = MagicMock()
        return resp

    def test_valid_png(self):
        sess = MagicMock()
        sess.get.return_value = self._resp(_png_bytes())
        img = download_image("http://x/tile.png", session=sess)
        assert img is not None
        assert img.mode == "RGBA"

    def test_non_image_body_returns_none(self):
        sess = MagicMock()
        sess.get.return_value = self._resp(b"<html>API KEY REQUIRED</html>")
        assert download_image("http://x/tile.png", session=sess) is None

    def test_truncated_png_returns_none(self):
        sess = MagicMock()
        sess.get.return_value = self._resp(_png_bytes()[:20])
        assert download_image("http://x/tile.png", session=sess) is None

    def test_request_error_returns_none(self):
        sess = MagicMock()
        sess.get.side_effect = requests.ConnectionError("boom")
        assert download_image("http://x/tile.png", session=sess) is None
