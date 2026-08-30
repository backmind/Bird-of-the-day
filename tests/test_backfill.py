"""Tests for the self-healing backfill step."""

import json
from unittest.mock import MagicMock, patch

from scripts import image_fetcher
from scripts.backfill import run_backfill
from scripts.distribution_map import MATCH_ERROR, MATCH_NONE, MATCH_OK
from scripts.image_fetcher import CDN_BASE, ImageResult
from scripts.llm_enricher import EnrichedContent


def _history(*codes_dates, image_url=CDN_BASE + "/1/900"):
    """A history whose entries all carry a usable photograph.

    A real entry always has an ``imageUrl`` key, and these tests are about
    the other two healers, so the default keeps photographs out of the
    way. Pass a URL with no asset id to make an entry healable, or
    ``image_url=None`` for the resolved "looked, found nothing" state.
    """
    return {"entries": [
        {"speciesCode": c, "comName": c.upper(), "sciName": f"Genus {c}",
         "date": d, "imageUrl": image_url, "photographer": "P",
         "attribution": "P / Macaulay Library"}
        for c, d in codes_dates
    ]}


def _write_content(tmp_path, code, **overrides):
    data = {
        "description": "texto", "description_source": "ebird",
        "bow_intro": "", "taxonomy": {}, "gbif_taxon_key": 1,
        "distribution_map_url": "http://gbif/x.png", "gbif_match": MATCH_OK,
    }
    data.update(overrides)
    (tmp_path / f"{code}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


def _write_enrichment(tmp_path, code):
    (tmp_path / f"{code}.enriched.json").write_text(json.dumps({
        "prose": "p", "identification": ["a"], "model": "m", "timestamp": "t",
    }), encoding="utf-8")


CFG = {"llm": {"endpoint": "http://fake", "models": ["m"]}}
ENRICHED = EnrichedContent(
    prose="nuevo", identification=["a", "b", "c"], model="m", timestamp="t"
)


def _run(history, tmp_path, limit=3, cfg=CFG):
    return run_backfill(
        history, cfg, MagicMock(language="es"), str(tmp_path), {}, {}, limit
    )


class TestEnrichmentBackfill:
    def test_heals_missing_enrichment(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=ENRICHED) as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert enrich.call_count == 1
        assert [(a.kind, a.ok) for a in actions] == [("enrichment", True)]
        assert (tmp_path / "aaa.enriched.json").exists()

    def test_newest_first_and_limit(self, tmp_path):
        for code in ("old", "mid", "new"):
            _write_content(tmp_path, code)
        history = _history(
            ("old", "2026-01-01"), ("mid", "2026-01-02"), ("new", "2026-01-03")
        )
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=ENRICHED) as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path, limit=2)
        called = [c.args[0] for c in enrich.call_args_list]
        assert called == ["new", "mid"]
        assert len(actions) == 2

    def test_skips_already_enriched(self, tmp_path):
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.llm_enricher.enrich_species") as enrich:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert enrich.call_count == 0
        assert actions == []

    def test_no_llm_configured_skips_enrichment(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch.dict("os.environ", {}, clear=True):
            actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert actions == []

    def test_failed_attempt_counts_against_limit(self, tmp_path):
        for code in ("aaa", "bbb"):
            _write_content(tmp_path, code)
        history = _history(("aaa", "2026-01-01"), ("bbb", "2026-01-02"))
        with patch("scripts.backfill.llm_enricher.enrich_species",
                   return_value=None):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path, limit=1)
        assert len(actions) == 1
        assert actions[0].ok is False


class TestGbifBackfill:
    def test_retries_transient_error(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)):
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert [(a.kind, a.ok) for a in actions] == [("gbif", True)]
        data = json.loads((tmp_path / "aaa.json").read_text(encoding="utf-8"))
        assert data["gbif_taxon_key"] == 42
        assert "taxonKey=42" in data["distribution_map_url"]
        assert data["iucn_code"] == "LC"

    def test_authoritative_none_not_retried(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_NONE,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex") as m:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert m.call_count == 0
        assert actions == []

    def test_zero_limit_disables(self, tmp_path):
        _write_content(tmp_path, "aaa")
        with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
            actions = _run(_history(("aaa", "2026-01-01")), tmp_path, limit=0)
        assert actions == []

    def test_gbif_consumes_last_slot_before_enrichment(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)):
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch("scripts.backfill.llm_enricher.enrich_species") as enrich:
                    with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                        actions = _run(
                            _history(("aaa", "2026-01-01")), tmp_path, limit=1
                        )
        assert [(a.kind, a.ok) for a in actions] == [("gbif", True)]
        assert enrich.call_count == 0

    def test_gbif_failure_persists_state(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(None, MATCH_ERROR)):
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert [(a.kind, a.ok) for a in actions] == [("gbif", False)]
        data = json.loads((tmp_path / "aaa.json").read_text(encoding="utf-8"))
        assert data["gbif_match"] == "error"
        assert data["gbif_taxon_key"] is None

    def test_legacy_empty_state_retries(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None,
            distribution_map_url="", gbif_match="",
        )
        _write_enrichment(tmp_path, "aaa")
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)) as m:
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=("LC", "LEAST_CONCERN", "http://bl")):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    _run(_history(("aaa", "2026-01-01")), tmp_path)
        assert m.call_count == 1

    def test_empty_sciname_skips_gbif(self, tmp_path):
        _write_content(
            tmp_path, "aaa", gbif_taxon_key=None, gbif_match=MATCH_ERROR,
        )
        _write_enrichment(tmp_path, "aaa")
        history = {"entries": [
            {"speciesCode": "aaa", "comName": "AAA", "sciName": "",
             "date": "2026-01-01", "imageUrl": CDN_BASE + "/1/900"},
        ]}
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex") as m:
            with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                actions = _run(history, tmp_path)
        assert actions == []
        assert m.call_count == 0


class TestImageBackfill:
    """Una entrada sin foto, o con una foto rota, se vuelve a pedir.

    Llegó a producción dos veces: eBird sirve la etiqueta del héroe
    incluso para especies de las que no tiene héroe, con el id vacío, y
    ".../asset//900" es un 404 que el lector ve como un agujero en la
    lámina. El arreglo de `image_fetcher` evita el siguiente caso; esto
    repara los que ya están escritos en el historial.
    """

    def _fake_fetch(self, monkeypatch, result, calls=None):
        def _fetch(code, session=None, locale="en", *, ordinal=0,
                   seen_asset_ids=frozenset()):
            if calls is not None:
                calls.append((code, ordinal, sorted(seen_asset_ids)))
            return result

        monkeypatch.setattr(image_fetcher, "fetch_image", _fetch)

    def test_a_url_without_an_asset_id_is_healed(self, tmp_path, monkeypatch):
        history = _history(("aaa", "2026-01-01"), image_url=CDN_BASE + "//900")
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/777/1200", asset_id="777", photographer="R",
            attribution="R / Macaulay Library", search_url="s",
        ))
        actions = _run(history, tmp_path)
        assert ("image", True) in [(a.kind, a.ok) for a in actions]
        entry = history["entries"][0]
        assert entry["imageUrl"] == CDN_BASE + "/777/1200"
        assert entry["photographer"] == "R"

    def test_a_healthy_url_is_left_alone(self, tmp_path, monkeypatch):
        history = _history(("aaa", "2026-01-01"))
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        calls = []
        self._fake_fetch(monkeypatch, ImageResult(
            url="x", asset_id="9", photographer="", attribution="",
            search_url="s",
        ), calls)
        _run(history, tmp_path)
        assert calls == []

    def test_a_failed_retry_clears_the_broken_url(self, tmp_path, monkeypatch):
        """Un hueco honesto es mejor que una imagen rota."""
        history = _history(("aaa", "2026-01-01"), image_url=CDN_BASE + "//900")
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        self._fake_fetch(monkeypatch, ImageResult(
            url=None, asset_id=None, photographer="",
            attribution="Macaulay Library / Cornell Lab of Ornithology",
            search_url="s",
        ))
        actions = _run(history, tmp_path)
        assert ("image", False) in [(a.kind, a.ok) for a in actions]
        assert history["entries"][0]["imageUrl"] is None

    def test_the_cache_moves_with_the_history(self, tmp_path, monkeypatch):
        """El sitio renderiza desde la caché cuando la hay, así que curar
        solo el historial no arreglaría nada."""
        history = _history(("aaa", "2026-01-01"), image_url=CDN_BASE + "//900")
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/777/1200", asset_id="777", photographer="R",
            attribution="R / Macaulay Library", search_url="s",
        ))
        _run(history, tmp_path)
        cached = image_fetcher.load_cached_image("aaa", str(tmp_path), ordinal=0)
        assert cached is not None and cached.asset_id == "777"

    def test_a_repeat_heals_its_own_publication_only(self, tmp_path, monkeypatch):
        """La misma especie dos veces: se repara la publicación rota, con
        su ordinal, y sin repetir la foto de la otra."""
        history = _history(("aaa", "2026-01-01"), ("aaa", "2026-05-01"))
        history["entries"][0]["imageUrl"] = CDN_BASE + "/111/900"
        history["entries"][1]["imageUrl"] = CDN_BASE + "//900"
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        calls = []
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/222/1200", asset_id="222", photographer="R",
            attribution="R / Macaulay Library", search_url="s",
        ), calls)
        _run(history, tmp_path)
        assert calls == [("aaa", 1, ["111"])]
        assert history["entries"][0]["imageUrl"] == CDN_BASE + "/111/900"
        assert history["entries"][1]["imageUrl"] == CDN_BASE + "/222/1200"

    def test_images_take_half_the_budget_newest_first(
        self, tmp_path, monkeypatch
    ):
        history = _history(
            ("aaa", "2026-01-01"), ("bbb", "2026-01-02"), ("ccc", "2026-01-03"),
            image_url=CDN_BASE + "//900",
        )
        for code in ("aaa", "bbb", "ccc"):
            _write_content(tmp_path, code)
            _write_enrichment(tmp_path, code)
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/9/1200", asset_id="9", photographer="R",
            attribution="R / Macaulay Library", search_url="s",
        ))
        actions = _run(history, tmp_path, limit=4)
        assert [a.species_code for a in actions] == ["ccc", "bbb"]

    def test_one_image_slot_survives_the_smallest_budget(
        self, tmp_path, monkeypatch
    ):
        """Con limit=1 la mitad sería cero, y una foto rota no se curaría
        nunca. El suelo de una ranura existe para eso."""
        history = _history(("aaa", "2026-01-01"), image_url=CDN_BASE + "//900")
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/9/1200", asset_id="9", photographer="R",
            attribution="R / Macaulay Library", search_url="s",
        ))
        actions = _run(history, tmp_path, limit=1)
        assert [(a.kind, a.ok) for a in actions] == [("image", True)]

    def test_a_failed_retry_also_removes_the_stale_cache(
        self, tmp_path, monkeypatch
    ):
        """Borrar la URL del historial no basta: el render prefiere la
        caché, así que una caché rota sobreviviría a la limpieza."""
        history = _history(("aaa", "2026-01-01"), image_url=CDN_BASE + "//900")
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        image_fetcher.save_cached_image(
            "aaa", ImageResult(
                url=CDN_BASE + "//900", asset_id="x", photographer="",
                attribution="a", search_url="s",
            ), str(tmp_path), ordinal=0,
        )
        assert image_fetcher.image_cache_path("aaa", str(tmp_path), 0).exists()
        self._fake_fetch(monkeypatch, ImageResult(
            url=None, asset_id=None, photographer="", attribution="a",
            search_url="s",
        ))
        _run(history, tmp_path)
        assert not image_fetcher.image_cache_path("aaa", str(tmp_path), 0).exists()
        assert history["entries"][0]["imageUrl"] is None

    def test_a_healed_debut_skips_a_later_publications_photo(
        self, tmp_path, monkeypatch
    ):
        """Curar un estreno cuya especie ya volvió no puede repetir la
        foto de la vuelta, aunque su ordinal sea 0."""
        history = _history(("aaa", "2026-01-01"), ("aaa", "2026-05-01"))
        history["entries"][0]["imageUrl"] = CDN_BASE + "//900"
        history["entries"][1]["imageUrl"] = CDN_BASE + "/555/900"
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        calls = []
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/666/1200", asset_id="666", photographer="R",
            attribution="a", search_url="s",
        ), calls)
        _run(history, tmp_path)
        assert calls == [("aaa", 0, ["555"])]

    def test_photographs_cannot_starve_the_other_healers(
        self, tmp_path, monkeypatch
    ):
        """Media asignación para fotos, y nunca menos de una. Sin esto,
        tres fotos irreparables apagaban GBIF y enriquecimiento para
        siempre, sin más señal que un aviso repetido."""
        history = _history(
            ("aaa", "2026-01-01"), ("bbb", "2026-01-02"), ("ccc", "2026-01-03"),
            image_url=CDN_BASE + "//900",
        )
        for code in ("aaa", "bbb", "ccc"):
            _write_content(tmp_path, code, gbif_taxon_key=None,
                           distribution_map_url="", gbif_match=MATCH_ERROR)
            _write_enrichment(tmp_path, code)
        self._fake_fetch(monkeypatch, ImageResult(
            url=None, asset_id=None, photographer="", attribution="a",
            search_url="s",
        ))
        with patch("scripts.backfill.distribution_map.gbif_taxon_match_ex",
                   return_value=(42, MATCH_OK)):
            with patch("scripts.backfill.distribution_map.fetch_iucn_category",
                       return_value=None):
                with patch.dict("os.environ", {"BOTD_LLM_API_KEY": "k"}):
                    actions = _run(history, tmp_path, limit=3)
        kinds = [a.kind for a in actions]
        assert kinds.count("image") == 1
        assert kinds.count("gbif") == 2

    def test_an_absent_photograph_is_not_retried(self, tmp_path, monkeypatch):
        """Sin foto significa que se preguntó a todas las vías y ninguna
        respondió. Es el mismo "no hay nada que encontrar" que impide al
        curado de GBIF reintentar MATCH_NONE para siempre."""
        history = _history(("aaa", "2026-01-01"), image_url=None)
        _write_content(tmp_path, "aaa")
        _write_enrichment(tmp_path, "aaa")
        calls = []
        self._fake_fetch(monkeypatch, ImageResult(
            url=None, asset_id=None, photographer="", attribution="a",
            search_url="s",
        ), calls)
        actions = _run(history, tmp_path)
        assert calls == []
        assert [a.kind for a in actions] == []

    def test_an_older_broken_entry_is_reached(self, tmp_path, monkeypatch):
        """Con una sola ranura, reintentar las vacías dejaba ganar siempre
        a la más nueva y una rota más vieja no se curaba nunca."""
        history = _history(("aaa", "2026-01-01"), ("bbb", "2026-06-01"))
        history["entries"][0]["imageUrl"] = CDN_BASE + "//900"
        history["entries"][1]["imageUrl"] = None
        for code in ("aaa", "bbb"):
            _write_content(tmp_path, code)
            _write_enrichment(tmp_path, code)
        calls = []
        self._fake_fetch(monkeypatch, ImageResult(
            url=CDN_BASE + "/9/1200", asset_id="9", photographer="R",
            attribution="a", search_url="s",
        ), calls)
        actions = _run(history, tmp_path, limit=1)
        assert [a.species_code for a in actions] == ["aaa"]
        assert history["entries"][0]["imageUrl"] == CDN_BASE + "/9/1200"
