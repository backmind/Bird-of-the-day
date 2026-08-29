"""Ordinal y fecha anterior, derivados del historial."""

from scripts import generate


HISTORY = {
    "entries": [
        {"speciesCode": "a", "comName": "A", "sciName": "Aa", "date": "2026-01-01",
         "imageUrl": "https://cdn/asset/1/1200", "photographer": "P1",
         "attribution": "P1 / Macaulay Library"},
        {"speciesCode": "b", "comName": "B", "sciName": "Bb", "date": "2026-01-02",
         "imageUrl": "https://cdn/asset/2/1200", "photographer": "P2",
         "attribution": "P2 / Macaulay Library"},
        {"speciesCode": "a", "comName": "A", "sciName": "Aa", "date": "2026-01-03",
         "imageUrl": "https://cdn/asset/3/1200", "photographer": "P3",
         "attribution": "P3 / Macaulay Library"},
    ]
}


def test_debut_is_ordinal_zero_with_no_previous_date():
    context = generate._publication_context(HISTORY["entries"])
    assert context[0] == (0, "")
    assert context[1] == (0, "")


def test_repeat_counts_and_remembers_the_previous_date():
    context = generate._publication_context(HISTORY["entries"])
    assert context[2] == (1, "2026-01-01")


def test_third_publication_points_at_the_second():
    entries = HISTORY["entries"] + [
        {"speciesCode": "a", "comName": "A", "sciName": "Aa", "date": "2026-02-01"}
    ]
    assert generate._publication_context(entries)[3] == (2, "2026-01-03")


def test_context_survives_entries_without_a_code():
    entries = [{"date": "2026-01-01"}, {"speciesCode": "a", "date": "2026-01-02"}]
    assert generate._publication_context(entries)[1] == (0, "")


def test_site_entries_carry_the_previous_date(monkeypatch, tmp_path):
    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path)
    entries = generate._build_site_entries(HISTORY)
    # _build_site_entries devuelve la más reciente primero.
    assert entries[0].species_code == "a"
    assert entries[0].previous_date == "2026-01-01"
    assert entries[1].previous_date == ""
    assert entries[2].previous_date == ""


def test_site_entries_use_the_photo_history_recorded(monkeypatch, tmp_path):
    """Sin caché por ordinal, la verdad de cada entrada es su historial."""
    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path)
    entries = generate._build_site_entries(HISTORY)
    assert entries[0].image_url == "https://cdn/asset/3/1200"
    assert entries[2].image_url == "https://cdn/asset/1/1200"


def test_site_entries_prefer_the_ordinal_cache(monkeypatch, tmp_path):
    from scripts import image_fetcher

    monkeypatch.setattr(generate, "CACHE_DIR", tmp_path)
    image_fetcher.save_cached_image(
        "a",
        image_fetcher.ImageResult(
            url="https://cdn/asset/99/1200", asset_id="99", photographer="Z",
            attribution="Z / Macaulay Library", search_url="s",
        ),
        str(tmp_path),
        ordinal=1,
    )
    entries = generate._build_site_entries(HISTORY)
    assert entries[0].image_url == "https://cdn/asset/99/1200"


def test_seen_assets_are_read_from_history():
    seen = generate._seen_asset_ids(HISTORY["entries"], "a")
    assert seen == frozenset({"1", "3"})
