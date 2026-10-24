"""La lámina es 3:2 y una foto vertical pierde al pájaro en el recorte.

El 2026-10-23 el Picamaderos Negro (blawoo1) salió con la foto por defecto
de iNaturalist, 816x1024, y la cresta quedó fuera del marco. La segunda
foto curada del taxón era 1204x804. Desde entonces se rota a la primera
candidata apaisada de cualquier fuente, y la vertical solo se publica
cuando no hay ninguna.
"""

import io

from PIL import Image

from scripts import image_fetcher
from scripts.image_fetcher import ImageResult, crops_badly


def test_the_threshold_is_four_to_three():
    assert not crops_badly(1204, 804)
    assert not crops_badly(4, 3)
    assert crops_badly(5, 4)
    assert crops_badly(816, 1024)
    # Sin tamaño conocido se recorta como siempre, sin rotar.
    assert not crops_badly(None, 800)
    assert not crops_badly(None, None)


def _photo(n, width, height, licence="cc-by"):
    return {
        "id": n, "license_code": licence,
        "attribution": f"(c) P{n}, some rights reserved (CC BY)",
        "medium_url": f"https://inaturalist-open-data.s3.amazonaws.com/photos/{n}/medium.jpg",
        "original_dimensions": {"width": width, "height": height},
    }


class _Resp:
    def __init__(self, payload=None, text="<html>challenge</html>"):
        self._payload = payload
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class _Session:
    """iNaturalist y Commons con fotos de tamaño conocido; Cornell, con su
    pasarela anti-bots, como hoy."""

    def __init__(self, default, curated=(), commons=None):
        self.default = default
        self.curated = list(curated)
        self.commons = commons
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        params = dict(params or {})
        self.calls.append(url)
        if "api.inaturalist.org/v1/taxa/" in url:
            return _Resp({"results": [{"id": 1, "taxon_photos": [
                {"photo": p} for p in [self.default, *self.curated]
            ]}]})
        if "api.inaturalist.org" in url:
            return _Resp({"results": [{
                "id": 1, "name": "Dryocopus martius", "default_photo": self.default,
            }]})
        if "wikipedia.org" in url and self.commons is not None:
            if params.get("prop") == "pageimages|images":
                return _Resp({"query": {"pages": [
                    {"title": "Dryocopus martius", "pageimage": "Picus.jpg"}
                ]}})
            width, height = self.commons
            return _Resp({"query": {"pages": [{"title": "File:Picus.jpg", "imageinfo": [{
                "url": "https://upload.wikimedia.org/full.jpg",
                "thumburl": "https://upload.wikimedia.org/900px-Picus.jpg",
                "thumbwidth": width, "thumbheight": height, "mime": "image/jpeg",
                "extmetadata": {"Artist": {"value": "Ana"},
                                "LicenseShortName": {"value": "CC BY-SA 4.0"}},
            }]}]}})
        return _Resp()


def _fetch(session):
    return image_fetcher.fetch_image(
        "blawoo1", session, scientific_name="Dryocopus martius"
    )


def test_a_portrait_default_gives_way_to_a_landscape_curated_photo():
    session = _Session(_photo(31574109, 1156, 1450), [_photo(150466350, 1204, 804)])
    result = _fetch(session)
    assert "/150466350/large.jpg" in result.url
    assert (result.width, result.height) == (1204, 804)


def test_a_landscape_default_is_taken_without_asking_for_more():
    session = _Session(_photo(1, 2048, 1365), [_photo(2, 2048, 1365)])
    assert "/1/large.jpg" in _fetch(session).url
    assert not any("/v1/taxa/" in url for url in session.calls)


def test_commons_is_asked_before_settling_for_a_portrait():
    session = _Session(_photo(1, 800, 1000), [_photo(2, 900, 1000)], commons=(900, 600))
    result = _fetch(session)
    assert result.url == "https://upload.wikimedia.org/900px-Picus.jpg"
    assert (result.width, result.height) == (900, 600)


def test_with_no_landscape_anywhere_the_first_portrait_is_published():
    session = _Session(_photo(1, 800, 1000), [_photo(2, 900, 1000)], commons=(600, 900))
    result = _fetch(session)
    assert "/1/large.jpg" in result.url
    assert crops_badly(result.width, result.height)


def test_cornell_photos_are_measured_and_rotated(monkeypatch):
    hero = ImageResult(url="https://cdn/asset/9/900", asset_id="9",
                       photographer="H", attribution="H / Macaulay Library",
                       search_url="s")
    rated = ImageResult(url="https://cdn/asset/7/900", asset_id="7",
                        photographer="R", attribution="R / Macaulay Library",
                        search_url="s")
    sizes = {hero.url: (600, 900), rated.url: (900, 600)}
    monkeypatch.setattr(image_fetcher, "_try_ebird_og_image", lambda *a, **k: [hero])
    monkeypatch.setattr(image_fetcher, "_try_macaulay_api", lambda *a, **k: [rated])
    monkeypatch.setattr(image_fetcher, "measure", lambda url, s: sizes[url])
    result = image_fetcher.fetch_image("cometi1", object())
    assert result.asset_id == "7"
    assert (result.width, result.height) == (900, 600)


def test_an_unmeasurable_photo_is_taken_as_it_comes(monkeypatch):
    hero = ImageResult(url="https://cdn/asset/9/900", asset_id="9",
                       photographer="H", attribution="H / Macaulay Library",
                       search_url="s")
    monkeypatch.setattr(image_fetcher, "_try_ebird_og_image", lambda *a, **k: [hero])
    monkeypatch.setattr(image_fetcher, "measure", lambda url, s: None)
    result = image_fetcher.fetch_image("cometi1", object())
    assert result.asset_id == "9"
    assert result.width is None


class _StreamSession:
    def __init__(self, data):
        self.data = data
        self.read = 0

    def get(self, url, timeout=None, stream=False, **kwargs):
        session = self

        class _Stream:
            def raise_for_status(self):
                pass

            def iter_content(self, size):
                for i in range(0, len(session.data), size):
                    session.read += size
                    yield session.data[i:i + size]

            def close(self):
                pass

        return _Stream()


def test_measure_reads_the_header_and_stops():
    buf = io.BytesIO()
    Image.effect_noise((900, 675), 64).convert("RGB").save(buf, "JPEG", quality=95)
    session = _StreamSession(buf.getvalue())
    assert image_fetcher.measure("https://cdn/asset/1/900", session) == (900, 675)
    assert session.read < len(buf.getvalue())


def test_measure_gives_up_on_what_is_not_an_image():
    assert image_fetcher.measure("u", _StreamSession(b"<html>gate</html>")) is None


def test_the_size_survives_the_cache(tmp_path):
    result = ImageResult(url="u", asset_id=None, photographer="P",
                         attribution="P / iNaturalist (CC BY)", search_url="s",
                         width=1204, height=804)
    image_fetcher.save_cached_image("blawoo1", result, str(tmp_path))
    cached = image_fetcher.load_cached_image("blawoo1", str(tmp_path))
    assert (cached.width, cached.height) == (1204, 804)


# --- La lámina -------------------------------------------------------------

def _plate(width, height):
    from scripts import site_builder
    from scripts.i18n import Catalog

    entry = site_builder.SiteEntry(
        species_code="blawoo1", common_name="Picamaderos Negro",
        scientific_name="Dryocopus martius", date="2026-10-23",
        image_url="https://x/p.jpg", photographer="P", attribution="P",
        description="d", description_source="ebird", bow_intro="",
        taxonomy={}, ml_search_url="s", image_width=width, image_height=height,
    )
    ctx = site_builder.RenderContext(catalog=Catalog.load("es"), feed_link="")
    return site_builder.render_plate(entry, ctx, hero=True)


def test_a_narrow_photo_is_shown_whole_over_a_blurred_copy():
    html = _plate(816, 1024)
    assert 'class="plate-image is-whole"' in html
    assert '<img class="plate-backdrop" src="https://x/p.jpg" alt="" aria-hidden="true"' in html


def test_a_landscape_or_unmeasured_photo_fills_the_frame_as_before():
    for width, height in ((1204, 804), (None, None)):
        html = _plate(width, height)
        assert 'class="plate-image"' in html
        assert "plate-backdrop" not in html


# --- Las entradas ya publicadas ------------------------------------------

def _old_history(url):
    return {"entries": [{
        "speciesCode": "blawoo1", "comName": "Picamaderos Negro",
        "sciName": "Dryocopus martius", "date": "2026-10-23",
        "imageUrl": url, "photographer": "Old", "attribution": "Old / iNaturalist (CC BY)",
    }]}


def _heal(history, tmp_path, monkeypatch, size, fresh):
    from scripts import backfill

    monkeypatch.setattr(image_fetcher, "measure", lambda url, s: size)
    monkeypatch.setattr(image_fetcher, "fetch_image", lambda *a, **k: fresh)
    return backfill._heal_image_sizes(history, str(tmp_path), "es", object(), 5)


_FRESH = ImageResult(url="https://x/new.jpg", asset_id=None, photographer="New",
                     attribution="New / iNaturalist (CC BY-NC-SA)", search_url="s",
                     width=1204, height=804)


def test_an_old_narrow_photo_is_replaced_when_a_landscape_one_exists(tmp_path, monkeypatch):
    history = _old_history("https://x/old.jpg")
    actions = _heal(history, tmp_path, monkeypatch, (816, 1024), _FRESH)
    entry = history["entries"][0]
    assert [(a.kind, a.ok) for a in actions] == [("image-size", True)]
    assert (entry["imageUrl"], entry["photographer"]) == ("https://x/new.jpg", "New")
    assert (entry["imageWidth"], entry["imageHeight"]) == (1204, 804)
    cached = image_fetcher.load_cached_image("blawoo1", str(tmp_path))
    assert cached.url == "https://x/new.jpg" and cached.width == 1204


def test_an_old_narrow_photo_stays_when_there_is_no_alternative(tmp_path, monkeypatch):
    history = _old_history("https://x/old.jpg")
    narrow = ImageResult(url="https://x/old.jpg", asset_id=None, photographer="Old",
                         attribution="Old", search_url="s", width=816, height=1024)
    _heal(history, tmp_path, monkeypatch, (816, 1024), narrow)
    entry = history["entries"][0]
    assert (entry["imageUrl"], entry["photographer"]) == ("https://x/old.jpg", "Old")
    assert (entry["imageWidth"], entry["imageHeight"]) == (816, 1024)


def test_an_old_landscape_photo_only_gets_its_size(tmp_path, monkeypatch):
    history = _old_history("https://x/old.jpg")
    monkeypatch.setattr(image_fetcher, "fetch_image",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no refetch")))
    from scripts import backfill
    monkeypatch.setattr(image_fetcher, "measure", lambda url, s: (900, 600))
    backfill._heal_image_sizes(history, str(tmp_path), "es", object(), 5)
    entry = history["entries"][0]
    assert (entry["imageUrl"], entry["imageWidth"]) == ("https://x/old.jpg", 900)


def test_an_unmeasurable_old_photo_waits_for_the_next_run(tmp_path, monkeypatch):
    history = _old_history("https://x/old.jpg")
    actions = _heal(history, tmp_path, monkeypatch, None, _FRESH)
    # Sin gastar cupo: una foto que ya no existe no puede bloquear la cola.
    assert actions == []
    assert "imageWidth" not in history["entries"][0]


# --- Lo que encontró la revisión -------------------------------------------

def test_the_same_photo_handed_back_is_not_a_replacement(tmp_path, monkeypatch):
    """Sin nada nuevo, fetch_image devuelve la misma foto, sin medir: el
    sanador no debe borrar el tamaño que acaba de leer."""
    history = _old_history("https://x/old.jpg")
    same = ImageResult(url="https://x/old.jpg", asset_id=None, photographer="Old",
                       attribution="Old", search_url="s")
    _heal(history, tmp_path, monkeypatch, (816, 1024), same)
    entry = history["entries"][0]
    assert (entry["imageWidth"], entry["imageHeight"]) == (816, 1024)


def test_an_unmeasured_photo_does_not_replace_a_known_narrow_one(tmp_path, monkeypatch):
    history = _old_history("https://x/old.jpg")
    unknown = ImageResult(url="https://x/other.jpg", asset_id="5", photographer="U",
                          attribution="U", search_url="s")
    _heal(history, tmp_path, monkeypatch, (816, 1024), unknown)
    assert history["entries"][0]["imageUrl"] == "https://x/old.jpg"


def test_an_unmeasurable_photo_does_not_starve_older_entries(tmp_path, monkeypatch):
    from scripts import backfill

    history = {"entries": [
        {"speciesCode": "old", "sciName": "A b", "date": "2026-10-01",
         "imageUrl": "https://x/fine.jpg", "photographer": "", "attribution": ""},
        {"speciesCode": "new", "sciName": "C d", "date": "2026-10-02",
         "imageUrl": "https://x/gone.jpg", "photographer": "", "attribution": ""},
    ]}
    sizes = {"https://x/fine.jpg": (900, 600), "https://x/gone.jpg": None}
    monkeypatch.setattr(image_fetcher, "measure", lambda url, s: sizes[url])
    actions = backfill._heal_image_sizes(history, str(tmp_path), "es", object(), 1)
    assert [a.species_code for a in actions] == ["old"]
    assert history["entries"][0]["imageWidth"] == 900


def test_a_republication_does_not_repeat_the_debut_inat_photo():
    """Sin asset id, una foto de iNaturalist solo se reconoce por su URL."""
    debut = "https://inaturalist-open-data.s3.amazonaws.com/photos/1/large.jpg"
    session = _Session(_photo(1, 2048, 1365), [_photo(2, 2048, 1365)])
    result = image_fetcher.fetch_image(
        "blawoo1", session, ordinal=1, seen_urls=frozenset({debut}),
        scientific_name="Dryocopus martius",
    )
    assert "/2/large.jpg" in result.url


def test_measure_honours_the_exif_rotation():
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (1600, 1200)).save(buf, "JPEG", exif=exif.tobytes())
    assert image_fetcher.measure("u", _StreamSession(buf.getvalue())) == (1200, 1600)
