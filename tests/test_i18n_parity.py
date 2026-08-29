"""Every catalog must define every key: a missing key renders as the raw
key name on a live page, and only the language that lost it would show it."""

import json

from scripts.i18n import CATALOG_DIR, discover_languages

NEW_KEYS = [
    *(f"month.{n}" for n in range(1, 13)),
    "page.bucket_title_template",
    "page.species_title_template",
    "archive.month_subtitle_template",
    "archive.months_heading",
    "nav.pagination_aria",
    "nav.older_month",
    "nav.newer_month",
    "nav.back_to_archive",
    "nav.older_plate",
    "nav.newer_plate",
    "species.history_heading",
]


def _load(lang):
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def test_all_catalogs_share_the_same_key_set():
    languages = discover_languages()
    assert len(languages) >= 2
    reference = set(_load("en"))
    for lang in languages:
        assert set(_load(lang)) == reference, f"{lang}.json key set differs"


def test_new_page_keys_exist_everywhere():
    for lang in discover_languages():
        catalog = _load(lang)
        for key in NEW_KEYS:
            assert key in catalog, f"{lang}.json misses {key}"
            assert catalog[key].strip(), f"{lang}.json has an empty {key}"


def test_templates_keep_their_placeholders():
    for lang in discover_languages():
        catalog = _load(lang)
        assert "{month}" in catalog["page.bucket_title_template"]
        assert "{name}" in catalog["page.species_title_template"]
        assert "{count}" in catalog["archive.month_subtitle_template"]
