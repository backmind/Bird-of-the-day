"""La segunda vez que sale una especie, la foto es otra."""

from scripts import image_fetcher
from scripts.image_fetcher import (
    ImageResult,
    _image_cache_path,
    asset_id_from_url,
)


def test_debut_keeps_the_historic_cache_name():
    assert _image_cache_path("cometi1", "cache").name == "cometi1.image.json"
    assert _image_cache_path("cometi1", "cache", 0).name == "cometi1.image.json"


def test_republications_get_their_own_cache_file():
    assert _image_cache_path("cometi1", "cache", 1).name == "cometi1.image-2.json"
    assert _image_cache_path("cometi1", "cache", 2).name == "cometi1.image-3.json"


def test_asset_id_is_read_back_from_the_url():
    url = "https://cdn.download.ams.birds.cornell.edu/api/v2/asset/12345/1200"
    assert asset_id_from_url(url) == "12345"
    assert asset_id_from_url("") is None
    assert asset_id_from_url(None) is None
    assert asset_id_from_url("https://example.com/photo.jpg") is None


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, timeout=None, **kwargs):
        self.urls.append(url)

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                pass

            def json(self):
                return self._payload

        return _Resp(self.payload)


def _catalog(*asset_ids):
    return {
        "results": {
            "content": [
                {"assetId": a, "userDisplayName": f"P{a}"} for a in asset_ids
            ]
        }
    }


def test_macaulay_skips_assets_already_published():
    session = _Session(_catalog("1", "2", "3"))
    result = image_fetcher._try_macaulay_api(
        "cometi1", session, count=5, skip=frozenset({"1", "2"})
    )
    assert result.asset_id == "3"
    assert "count=5" in session.urls[0]


def test_macaulay_returns_none_when_everything_is_seen():
    session = _Session(_catalog("1"))
    assert image_fetcher._try_macaulay_api(
        "cometi1", session, skip=frozenset({"1"})
    ) is None


def test_debut_still_prefers_the_ebird_hero(monkeypatch):
    hero = ImageResult(
        url="https://cdn/asset/9/1200", asset_id="9", photographer="H",
        attribution="H / Macaulay Library", search_url="s",
    )
    monkeypatch.setattr(
        image_fetcher, "_try_ebird_og_image", lambda *a, **k: hero
    )
    monkeypatch.setattr(
        image_fetcher, "_try_macaulay_api",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("not reached")),
    )
    assert image_fetcher.fetch_image(
        "cometi1", session=_Session({}), ordinal=0
    ).asset_id == "9"


def test_republication_goes_straight_to_the_rated_list(monkeypatch):
    calls = {}

    def fake_macaulay(code, session, *, count=1, skip=frozenset()):
        calls["count"] = count
        calls["skip"] = skip
        return ImageResult(
            url="https://cdn/asset/7/1200", asset_id="7", photographer="P",
            attribution="P / Macaulay Library", search_url="s",
        )

    monkeypatch.setattr(
        image_fetcher, "_try_ebird_og_image",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("not reached")),
    )
    monkeypatch.setattr(image_fetcher, "_try_macaulay_api", fake_macaulay)
    result = image_fetcher.fetch_image(
        "cometi1", session=_Session({}), ordinal=1,
        seen_asset_ids=frozenset({"9"}),
    )
    assert result.asset_id == "7"
    # The exact arithmetic, not just "more than one": asking for a fixed
    # count would still satisfy a loose assertion while starving the
    # fourth or fifth publication of a species.
    assert calls["count"] == 1 + image_fetcher.MACAULAY_LOOKAHEAD
    assert calls["skip"] == frozenset({"9"})


def test_republication_falls_back_when_the_library_has_nothing_new(monkeypatch):
    """Mejor repetir foto que publicar sin foto."""
    hero = ImageResult(
        url="https://cdn/asset/9/1200", asset_id="9", photographer="H",
        attribution="H / Macaulay Library", search_url="s",
    )
    monkeypatch.setattr(image_fetcher, "_try_ebird_og_image", lambda *a, **k: hero)
    monkeypatch.setattr(image_fetcher, "_try_macaulay_api", lambda *a, **k: None)
    result = image_fetcher.fetch_image(
        "cometi1", session=_Session({}), ordinal=3,
        seen_asset_ids=frozenset({"9"}),
    )
    assert result.asset_id == "9"


def test_cached_photos_do_not_collide(tmp_path):
    first = ImageResult(
        url="https://cdn/asset/1/1200", asset_id="1", photographer="A",
        attribution="A / Macaulay Library", search_url="s",
    )
    second = ImageResult(
        url="https://cdn/asset/2/1200", asset_id="2", photographer="B",
        attribution="B / Macaulay Library", search_url="s",
    )
    image_fetcher.save_cached_image("cometi1", first, str(tmp_path))
    image_fetcher.save_cached_image("cometi1", second, str(tmp_path), ordinal=1)
    assert image_fetcher.load_cached_image("cometi1", str(tmp_path)).asset_id == "1"
    assert image_fetcher.load_cached_image(
        "cometi1", str(tmp_path), ordinal=1
    ).asset_id == "2"
