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
