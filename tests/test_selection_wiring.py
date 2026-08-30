"""El run diario pasa el historial entero, no una rebanada."""

from scripts import content_scraper, ebird_client, generate, i18n, image_fetcher


ENTRIES = [
    {"speciesCode": f"sp{i}", "date": f"2026-01-{i:02d}"} for i in range(1, 61)
]


def _stub_fetchers(monkeypatch, tmp_path):
    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(image_fetcher, "new_session", lambda **k: None)
    monkeypatch.setattr(
        image_fetcher, "fetch_image",
        lambda *a, **k: image_fetcher.ImageResult(
            url="https://cdn/asset/1/1200", asset_id="1", photographer="P",
            attribution="P / Macaulay Library", search_url="s",
        ),
    )
    monkeypatch.setattr(image_fetcher, "save_cached_image", lambda *a, **k: None)
    monkeypatch.setattr(
        content_scraper, "scrape_species_content",
        lambda *a, **k: content_scraper.SpeciesContent(
            description="Texto.", description_source="ebird", bow_intro="",
            taxonomy={},
        ),
    )
    monkeypatch.setattr(content_scraper, "save_cached_content", lambda *a, **k: None)


def test_selection_receives_the_whole_history(monkeypatch, tmp_path):
    seen = {}

    def fake_select(config, published_codes, date_str, cache_dir=None,
                    exclude=frozenset(), notes=None):
        seen["codes"] = list(published_codes)
        seen["exclude"] = exclude
        if notes is not None:
            notes.append("pool madrid clamped")
        return {"speciesCode": "sp1", "comName": "A", "sciName": "Aa"}

    monkeypatch.setattr(ebird_client, "select_species", fake_select)
    _stub_fetchers(monkeypatch, tmp_path)

    notes = []
    generate._select_and_fetch(
        {"max_skip_retries": 0}, ENTRIES, "2026-03-01",
        i18n.Catalog.load("es"), "es", "foreign_fallback", notes=notes,
    )
    assert len(seen["codes"]) == 60
    assert seen["exclude"] == frozenset()
    assert notes == ["pool madrid clamped"]


def test_skip_reroll_excludes_what_it_already_tried(monkeypatch, tmp_path):
    """La re-tirada de la política skip ya no contamina la ventana."""
    calls = []

    def fake_select(config, published_codes, date_str, cache_dir=None,
                    exclude=frozenset(), notes=None):
        calls.append(exclude)
        return {"speciesCode": f"sp{len(calls)}", "comName": "A", "sciName": "Aa"}

    monkeypatch.setattr(ebird_client, "select_species", fake_select)
    _stub_fetchers(monkeypatch, tmp_path)
    monkeypatch.setattr(
        content_scraper, "scrape_species_content",
        lambda *a, **k: content_scraper.SpeciesContent(
            description="", description_source="", bow_intro="", taxonomy={},
        ),
    )

    generate._select_and_fetch(
        {"max_skip_retries": 2}, ENTRIES, "2026-03-01",
        i18n.Catalog.load("es"), "es", "skip",
    )
    assert calls[0] == frozenset()
    assert calls[1] == frozenset({"sp1"})
    assert calls[2] == frozenset({"sp1", "sp2"})


def _image(url):
    return image_fetcher.ImageResult(
        url=url, asset_id="1" if url else None, photographer="P",
        attribution="P / Macaulay Library", search_url="s",
    )


def _picker(monkeypatch, codes):
    """Selección que va devolviendo `codes` en orden."""
    seen = []

    def fake_select(config, published_codes, date_str, cache_dir=None,
                    exclude=frozenset(), notes=None):
        code = codes[len(seen)]
        seen.append(code)
        return {"speciesCode": code, "comName": code.upper(), "sciName": "X y"}

    monkeypatch.setattr(ebird_client, "select_species", fake_select)
    return seen


class TestPhotoReroll:
    """Un ave del día sin ave no cumple lo que el sitio promete.

    Salió en producción el 2026-08-30: el Atlapetes de Vilcabamba, que
    eBird no tiene curado y que Macaulay no pudo responder por estar tras
    su muro anti-bot, ocupó la portada con un marco vacío.
    """

    def _stub_photos(self, monkeypatch, tmp_path, by_code):
        _stub_fetchers(monkeypatch, tmp_path)
        monkeypatch.setattr(
            image_fetcher, "fetch_image",
            lambda code, *a, **k: _image(by_code.get(code)),
        )

    def test_a_species_without_a_photograph_is_rerolled(
        self, monkeypatch, tmp_path
    ):
        seen = _picker(monkeypatch, ["nofoto", "confoto"])
        self._stub_photos(monkeypatch, tmp_path, {
            "nofoto": None, "confoto": "https://cdn/asset/9/1200",
        })
        notes = []
        species, image, _ = generate._select_and_fetch(
            {"max_skip_retries": 5}, ENTRIES, "2026-03-01",
            i18n.Catalog.load("es"), "es", "foreign_fallback", notes=notes,
        )
        assert seen == ["nofoto", "confoto"]
        assert species["speciesCode"] == "confoto"
        assert image.url
        assert any("no photograph" in n for n in notes)

    def test_the_reroll_does_not_depend_on_the_description_policy(
        self, monkeypatch, tmp_path
    ):
        """`skip` re-tira por texto; la foto re-tira bajo cualquier política."""
        for policy in ("strict", "foreign_fallback", "skip"):
            seen = _picker(monkeypatch, ["nofoto", "confoto"])
            self._stub_photos(monkeypatch, tmp_path, {
                "nofoto": None, "confoto": "https://cdn/asset/9/1200",
            })
            species, _, _ = generate._select_and_fetch(
                {"max_skip_retries": 5}, ENTRIES, "2026-03-01",
                i18n.Catalog.load("es"), "es", policy,
            )
            assert species["speciesCode"] == "confoto", policy

    def test_the_rerolled_species_is_excluded_from_the_next_draw(
        self, monkeypatch, tmp_path
    ):
        excludes = []

        def fake_select(config, published_codes, date_str, cache_dir=None,
                        exclude=frozenset(), notes=None):
            excludes.append(sorted(exclude))
            code = ["a", "b", "c"][len(excludes) - 1]
            return {"speciesCode": code, "comName": "X", "sciName": "X y"}

        monkeypatch.setattr(ebird_client, "select_species", fake_select)
        self._stub_photos(monkeypatch, tmp_path, {
            "a": None, "b": None, "c": "https://cdn/asset/9/1200",
        })
        generate._select_and_fetch(
            {"max_skip_retries": 5}, ENTRIES, "2026-03-01",
            i18n.Catalog.load("es"), "es", "strict",
        )
        assert excludes == [[], ["a"], ["a", "b"]]

    def test_exhausting_the_retries_publishes_the_gap(
        self, monkeypatch, tmp_path
    ):
        """Un día sin entrada es peor que un día con una entrada flaca."""
        _picker(monkeypatch, ["a", "b", "c"])
        self._stub_photos(monkeypatch, tmp_path, {})
        notes = []
        species, image, _ = generate._select_and_fetch(
            {"max_skip_retries": 2}, ENTRIES, "2026-03-01",
            i18n.Catalog.load("es"), "es", "strict", notes=notes,
        )
        assert species["speciesCode"] == "c"
        assert image.url is None
        assert any("exhausted" in n for n in notes)
